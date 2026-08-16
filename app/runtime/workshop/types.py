"""Unified DeepAgent 领域类型（全部 JSON 可序列化，供 checkpoint/LangSmith 使用）。

约定：领域 state 与 middleware 边界只交换 JSON 化 dict，不交换 pydantic /
dataclass 实例——LangGraph checkpoint 与 LangSmith 追踪对纯 dict 最稳。
pydantic 对象在边界处用 ``model_dump(mode="json")`` 转换。
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------- 路由

ExecutionMode = Literal["fast_path", "agent", "fast_path_rejected"]

Route = Literal["fast_path", "deep_agent", "clarification"]

FallbackAction = Literal[
    "to_deep_agent", "clarify", "retry", "reject", "fail_closed", "respond"
]


class RouteDecision(TypedDict, total=False):
    """可审计路由对象（与 orchestration/router 输出同构）。"""

    route: Route
    capability: str
    confidence: float
    reason_code: str
    plan: dict[str, Any] | None
    fallback_action: FallbackAction
    rule_id: str | None


class WorkflowFailure(TypedDict, total=False):
    """稳定 reason_code + 显式动作；禁止宽泛 except 混淆错误类型。"""

    reason_code: str
    action: FallbackAction
    message: str
    stage: str
    evidence_refs: list[str]


# ---------------------------------------------------------------- 产物

class ExecutionResult(TypedDict, total=False):
    """FastPath 有界执行产物摘要。

    payload 携带 renderer 输出（reply / presentation / detail /
    trust_metrics / fast_path meta），供 FinalizeMiddleware 统一收尾读取。
    """

    result_ids: list[str]
    calculation_ids: list[str]
    assertion_ids: list[str]
    assertion_count: int
    verified_count: int
    payload: dict[str, Any] | None


class EvidenceItem(TypedDict, total=False):
    id: str
    source: str
    status: str
    facts: list[str]
    queried_at: str | None


class ValidationResult(TypedDict, total=False):
    """统一证据 guardrail 输出。"""

    passed: bool
    reason: str
    unmatched: list[str]
    tool_names: list[str]
    has_usable_payload: bool


class Presentation(TypedDict, total=False):
    type: str
    title: str | None
    columns: list[str] | None
    rows: list[Any] | None
    items: list[Any] | None
    analysis_type: str | None
    year: int | None
    month: int | None
    limit: int | None


# ---------------------------------------------------------------- 输出

class UnifiedResponse(TypedDict, total=False):
    """所有执行路径汇合后的统一输出（调用方只读这个）。"""

    conversation_id: str
    run_id: str
    title: str | None
    reply: str
    execution_mode: ExecutionMode
    semantic_plan: dict[str, Any] | None
    result: dict[str, Any] | None
    presentation: Presentation | None
    detail: dict[str, Any] | None
    trust_metrics: dict[str, Any] | None
    evidence: list[dict[str, Any]]
    evidence_guardrail: ValidationResult | None
    tool_traces: list[dict[str, Any]]
    fast_path: dict[str, Any] | None
    fast_path_rejection: dict[str, Any] | None
    fast_path_observation: dict[str, Any] | None
    failure: WorkflowFailure | None


# ---------------------------------------------------------------- Direct Tool

DirectArtifactStatus = Literal[
    "success",
    "rejected",
    "missing_user_input",
    "ambiguous_user_input",
    "model_argument_error",
]


class DirectArtifact(TypedDict, total=False):
    """query_metric_direct 的归一化输出（ToolMessage.content 的 JSON 契约）。

    - success：确定性执行完成（reply / presentation / detail / trust_metrics）
    - rejected：权限 / 证据不足 / 契约拦截（reason_code 区分）
    - missing_user_input：用户没说清（after_agent 生成澄清问题）
    - ambiguous_user_input：存在多个合理解释（after_agent 提供选项）
    - model_argument_error：用户说清了但模型参数非法（文案不得归咎用户）

    FinalizeMiddleware 兼容 artifact 与框架生成的原始错误 ToolMessage
    （ToolErrorNormalizer 尽量归一化，但不得假设 artifact 永远存在）。
    """

    status: DirectArtifactStatus
    reply: str
    result: dict[str, Any] | None
    presentation: Presentation | None
    detail: dict[str, Any] | None
    trust_metrics: dict[str, Any] | None
    evidence: list[dict[str, Any]]
    fast_path: dict[str, Any] | None
    reason_code: str
    clarification: str | None
    options: list[str]
