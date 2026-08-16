"""DeepAgent 子图节点（架构定稿 §9 P2）。

create_deep_agent 不再是系统根——它作为顶层编排图的 deep_agent 分支节点，
接收统一 ConversationState，跑 agent 后把结果折叠回 state
（evidence → state.evidence，reply → state.execution_result / presentation）。

P2 落地：deep_agent 节点函数，复用 schedule_agent._build_agent 构建 agent，
agent.invoke 后折叠输出。checkpoint/messages 统一由顶层图持有（P4 接入
checkpointer 时 DeepAgent 复用同一 thread）。
"""

from __future__ import annotations

from typing import Any

from app.runtime.orchestration.state import ConversationState, ExecutionResult, Failure


def deep_agent_branch(state: ConversationState) -> dict[str, Any]:
    """ConversationRuntime 的 deep_agent 分支实现。

    接收统一 state（question / messages / 执行上下文），跑 DeepAgent，
    把回复折叠为 execution_result（reply）+ evidence。

    v1：调用 schedule_agent._build_agent + agent.invoke；输出折叠为
    execution_result.payload.reply。evidence 提取在 P3 统一接入。
    """
    from app.services import schedule_agent

    question = state.get("question", "")
    tenant_id = state.get("tenant_id")
    if tenant_id is None:
        return {"failure": Failure(
            reason_code="EVIDENCE_FAILED", action="fail_closed", stage="deep_agent",
        )}

    try:
        agent = schedule_agent._build_agent(
            tenant_id,
            conversation_id=state.get("conversation_id"),
            permission_codes=state.get("permission_codes"),
            profiles=None,
        )
        result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    except Exception as exc:  # noqa: BLE001 - agent 内部异常统一折叠为显式 failure
        return {"failure": Failure(
            reason_code="TRANSIENT_FAILURE", action="retry",
            message=str(exc)[:200], stage="deep_agent",
        )}

    messages = result.get("messages") if isinstance(result, dict) else None
    reply = ""
    if messages:
        for m in reversed(messages):
            mtype = getattr(m, "type", None) or m.__class__.__name__
            if mtype in ("ai", "AIMessage") and getattr(m, "content", None):
                reply = str(m.content)
                break

    return {
        "execution_result": ExecutionResult(
            result_ids=[],
            assertion_count=0,
            verified_count=0,
            payload={"reply": reply},
        ),
        "presentation": {"type": "deep_agent", "title": None} if reply else None,
    }
