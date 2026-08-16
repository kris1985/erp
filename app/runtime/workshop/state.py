"""WorkshopAgentState —— create_deep_agent 的领域 state schema。

继承 ``DeepAgentState``（messages / jump_to / structured_response 由
deepagents 定义），追加领域工作产物通道。调用方只读 ``response``；
其余通道是 middleware 之间的内部契约：

- ``semantic_plan``：入口语义编译产物（FastPath 与 Agent 共用）
- ``previous_plans``：跨轮继承的结构化源（FinalizeMiddleware 每轮追加）
- ``route_decision``：可审计路由对象
- ``execution_mode``：executed / rejected / agent 三态
- ``execution_result``：FastPath 有界执行产物摘要
- ``evidence`` / ``validation`` / ``presentation`` / ``response`` /
  ``failure``：统一收尾链路的读写通道
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from deepagents import DeepAgentState

ExecutionMode = Literal["fast_path", "agent", "fast_path_rejected"]


class WorkshopAgentState(DeepAgentState):  # type: ignore[misc]
    """领域 state：继承 DeepAgentState（messages/jump_to）并扩展工作产物。"""

    semantic_plan: NotRequired[dict[str, Any] | None]
    previous_plans: NotRequired[list[dict[str, Any]]]
    route_decision: NotRequired[dict[str, Any] | None]
    execution_mode: NotRequired[ExecutionMode | None]
    execution_result: NotRequired[dict[str, Any] | None]
    evidence: NotRequired[list[dict[str, Any]]]
    validation: NotRequired[dict[str, Any] | None]
    presentation: NotRequired[dict[str, Any] | None]
    response: NotRequired[dict[str, Any] | None]
    failure: NotRequired[dict[str, Any] | None]
    fast_path_observation: NotRequired[dict[str, Any] | None]
    # 调用方注入的前置证据（preflight/child 查询），进入统一 guardrail
    injected_evidence: NotRequired[list[dict[str, Any]]]


def initial_workshop_state(*, question: str) -> dict[str, Any]:
    """调用方 invoke/stream 的输入 state：问题 + 空工作产物。"""
    return {
        "messages": [{"role": "user", "content": question}],
        "semantic_plan": None,
        "previous_plans": [],
        "route_decision": None,
        "execution_mode": None,
        "execution_result": None,
        "evidence": [],
        "validation": None,
        "presentation": None,
        "response": None,
        "failure": None,
        "fast_path_observation": None,
        "injected_evidence": [],
    }
