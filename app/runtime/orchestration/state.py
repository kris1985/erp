"""编排层统一状态 schema（架构定稿 §3，docs/design/agent-orchestration-runtime.md）。

两个执行分支（FastPath / DeepAgent）写入同一个 state；API/SSE 只把最终
state 转换为协议，不关心结果来自哪个分支。

``RouteDecision`` 是可审计对象：route / capability / confidence /
reason_code / plan。``Failure`` 携带稳定 reason_code + action，禁止用宽泛
except 混淆错误类型（架构定稿 §6）。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

Route = Literal["fast_path", "deep_agent", "clarification"]

# fallback 动作（显式状态机，架构定稿 §6）
FallbackAction = Literal[
    "to_deep_agent", "clarify", "retry", "reject", "fail_closed", "respond"
]


class RouteDecision(TypedDict, total=False):
    route: Route
    capability: str
    confidence: float
    reason_code: str
    plan: dict[str, Any] | None
    fallback_action: FallbackAction
    rule_id: str | None


class Failure(TypedDict, total=False):
    reason_code: str
    action: FallbackAction
    message: str
    evidence_refs: list[str]
    stage: str


class ExecutionResult(TypedDict, total=False):
    """FastPath 子图产物：VerifiedAssertion / Facts / Calculations 的摘要。"""

    result_ids: list[str]
    calculation_ids: list[str]
    assertion_count: int
    verified_count: int
    payload: dict[str, Any] | None


class Presentation(TypedDict, total=False):
    type: str
    title: str | None
    columns: list[str] | None
    rows: list[Any] | None
    items: list[Any] | None


class TrustMetrics(TypedDict, total=False):
    unsupported_claim_escape_rate: float
    evidence_sufficiency_rate: float
    claim_precision: float
    total_assertions: int
    verified_assertions: int


class EvidenceItem(TypedDict, total=False):
    id: str
    source: str
    status: str
    facts: list[str]
    queried_at: str | None


class ConversationState(TypedDict, total=False):
    """两个分支共用的结构化 state（架构定稿 §3）。"""

    messages: Annotated[list[BaseMessage], add_messages]
    route: RouteDecision
    semantic_plan: dict[str, Any] | None
    execution_result: ExecutionResult | None
    evidence: list[EvidenceItem]
    presentation: Presentation | None
    trust_metrics: TrustMetrics | None
    failure: Failure | None


def new_state(*, question: str) -> ConversationState:
    """创建一轮对话的初始 state（空路由，等待 Router 填充）。"""
    return {
        "route": RouteDecision(route="deep_agent", reason_code="pending_route"),
        "semantic_plan": None,
        "execution_result": None,
        "evidence": [],
        "presentation": None,
        "trust_metrics": None,
        "failure": None,
    }
