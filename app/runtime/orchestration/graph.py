"""ConversationRuntime —— 顶层业务编排图（架构定稿 §1/§2.1）。

顶层 LangGraph 负责：会话/thread 生命周期、意图路由、分支选择、显式
fallback 状态转换、统一 checkpoint。FastPath 与 DeepAgent 是**平级子图**，
DeepAgent 不再是整个系统的根。

P0 落地：图拓扑 + 路由 + fallback 状态机 + 分支占位（FastPath 子图在 P1
实现，DeepAgent 子图在 P2 接入）。分支实现以「节点函数」注入，便于逐 PR
替换占位为真实实现。
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from app.runtime.orchestration.fallback import fallback_action, resolve_reason_code
from app.runtime.orchestration.router import ConversationRouter
from app.runtime.orchestration.state import (
    ConversationState,
    Failure,
    RouteDecision,
    new_state,
)

# 分支节点签名：输入/输出都是 state（LangGraph 节点约定）
BranchNode = Callable[[ConversationState], dict[str, Any]]


class ConversationRuntime:
    """组装并运行顶层编排图。

    fast_path_node / deep_agent_node / clarification_node 是分支实现
    （P0 为占位，P1/P2 替换为真实子图）。route/fallback/response 是
    本图自带的控制面逻辑。
    """

    def __init__(
        self,
        *,
        fast_path_enabled: bool = False,
        fast_path_node: BranchNode | None = None,
        deep_agent_node: BranchNode | None = None,
        clarification_node: BranchNode | None = None,
        router: ConversationRouter | None = None,
    ) -> None:
        self._fast_path_enabled = fast_path_enabled
        self._router = router or ConversationRouter()
        self._fast_path_node = fast_path_node or self._pending_fast_path
        if deep_agent_node is not None:
            self._deep_agent_node = deep_agent_node
        else:
            from app.runtime.orchestration.deep_agent import deep_agent_branch

            self._deep_agent_node = deep_agent_branch
        self._clarification_node = clarification_node or self._pending_clarification
        self._graph = self._build()

    # ------------------------------------------------------------------
    # 图拓扑
    # ------------------------------------------------------------------

    def _build(self):
        graph = StateGraph(ConversationState)
        graph.add_node("compile", self._compile_node)
        graph.add_node("route", self._route_node)
        graph.add_node("fast_path", self._fast_path_node)
        graph.add_node("deep_agent", self._deep_agent_node)
        graph.add_node("clarification", self._clarification_node)
        graph.add_node("response", self._response_node)
        graph.add_node("reject", self._reject_node)

        # 语义编译在路由之前（架构定稿：Semantic Compiler → Inheritance
        # Resolver → Plan Validator → route）。compile 失败 → 显式 failure
        # → 按 fallback 转 deep_agent（不宽泛 except）。
        graph.add_edge(START, "compile")
        graph.add_edge("compile", "route")
        # route 之后按 RouteDecision.route 分派（显式条件边）
        graph.add_conditional_edges(
            "route",
            self._dispatch,
            {
                "fast_path": "fast_path",
                "deep_agent": "deep_agent",
                "clarification": "clarification",
            },
        )
        # 分支结束后统一进 response（或 reject/fail_closed）
        graph.add_edge("fast_path", "response")
        graph.add_edge("deep_agent", "response")
        graph.add_edge("clarification", "response")
        graph.add_edge("response", END)
        graph.add_edge("reject", END)
        return graph.compile()

    def _dispatch(self, state: ConversationState) -> str:
        """route 节点后按 RouteDecision.route 选择分支（显式路由，非异常）。"""
        route = (state.get("route") or {}).get("route", "deep_agent")
        if route not in ("fast_path", "deep_agent", "clarification"):
            return "deep_agent"
        return route

    # ------------------------------------------------------------------
    # 控制面节点
    # ------------------------------------------------------------------

    def _compile_node(self, state: ConversationState) -> dict[str, Any]:
        """语义编译 + 继承解析（FastPath 分支的受限 LLM 步骤，在此统一执行）。

        编译失败/无法继承 → 不设 failure（避免卡死），让 route 基于空 plan
        走 deep_agent。plan_validate 的完整性判定由 router 承担。
        """
        from app.runtime.orchestration.fast_path import inheritance_resolve, semantic_compile

        carried: dict[str, Any] = {}
        for node in (semantic_compile, inheritance_resolve):
            result = node(state)
            if isinstance(result, dict) and "failure" in result:
                # 编译失败是明确失败，但仍给 route 机会（空 plan → deep_agent）
                continue
            carried.update(result)
            state.update(carried)
        return carried

    def _route_node(self, state: ConversationState) -> dict[str, Any]:
        decision = self._router.route(state, fast_path_enabled=self._fast_path_enabled)
        return {"route": decision}

    def _response_node(self, state: ConversationState) -> dict[str, Any]:
        """统一输出面：把分支产物折叠为最终 state（guardrail/呈现在 P3 接入）。

        v1：若分支已置 failure → fail_closed；否则标记 SUCCESS。
        """
        failure = state.get("failure")
        if failure is not None:
            return {
                "route": {
                    **(state.get("route") or {}),
                    "fallback_action": failure.get("action", "fail_closed"),
                }
            }
        return {
            "route": {
                **(state.get("route") or {}),
                "reason_code": "SUCCESS",
                "fallback_action": "respond",
            }
        }

    def _reject_node(self, state: ConversationState) -> dict[str, Any]:
        """PERMISSION_DENIED / fail_closed 的终止节点（不进入 response）。"""
        return {"failure": state.get("failure") or Failure(reason_code="REJECTED", action="reject")}

    # ------------------------------------------------------------------
    # 分支占位（P1/P2 替换为真实实现）
    # ------------------------------------------------------------------

    @staticmethod
    def _pending_fast_path(state: ConversationState) -> dict[str, Any]:
        # P1 替换：semantic_compile → authorize → execute → validate → response
        return {"failure": Failure(
            reason_code="FAST_PATH_NOT_IMPLEMENTED",
            action=fallback_action("FAST_PATH_NOT_IMPLEMENTED"),
            stage="fast_path",
        )}

    @staticmethod
    def _pending_deep_agent(state: ConversationState) -> dict[str, Any]:
        # P2 替换：create_deep_agent 子图
        return {"failure": Failure(
            reason_code="DEEP_AGENT_NOT_IMPLEMENTED",
            action=fallback_action("DEEP_AGENT_NOT_IMPLEMENTED"),
            stage="deep_agent",
        )}

    @staticmethod
    def _pending_clarification(state: ConversationState) -> dict[str, Any]:
        # 澄清分支：v1 直接产出缺 slot 说明（P0 占位可回答）
        plan = state.get("semantic_plan") or {}
        return {
            "failure": Failure(
                reason_code="MISSING_SLOT",
                action="clarify",
                message="需要补充必要信息后才能回答。",
                stage="clarification",
            ),
        }

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def invoke(self, *, question: str, **state_extra: Any) -> ConversationState:
        state = new_state(question=question)
        state.update(state_extra)
        return self._graph.invoke(state)

    def get_graph(self):
        return self._graph


def run_conversation(
    *,
    question: str,
    fast_path_enabled: bool = False,
    **branch_nodes: BranchNode,
) -> ConversationState:
    """便捷入口：一次调用完成整轮编排。branch_nodes 覆盖默认分支实现。"""
    runtime = ConversationRuntime(
        fast_path_enabled=fast_path_enabled,
        fast_path_node=branch_nodes.get("fast_path_node"),
        deep_agent_node=branch_nodes.get("deep_agent_node"),
        clarification_node=branch_nodes.get("clarification_node"),
    )
    return runtime.invoke(question=question)
