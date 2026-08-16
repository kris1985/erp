"""Agent 运行时顶层编排图（P0 骨架）。

把 FastPath 与 DeepAgent 作为平级子图放进统一业务编排图（架构定稿
docs/design/agent-orchestration-runtime.md）。P0 落地：state / fallback
状态机 / 顶层 Router / ConversationRuntime 图拓扑。
"""

from app.runtime.orchestration.state import (
    ConversationState,
    ExecutionResult,
    Failure,
    Presentation,
    RouteDecision,
    TrustMetrics,
    new_state,
)
from app.runtime.orchestration.fallback import (
    FALLBACK_RULES,
    FallbackRule,
    fallback_action,
    resolve_reason_code,
)
from app.runtime.orchestration.router import ConversationRouter
from app.runtime.orchestration.graph import ConversationRuntime, run_conversation

__all__ = [
    "ConversationState",
    "ExecutionResult",
    "Failure",
    "Presentation",
    "RouteDecision",
    "TrustMetrics",
    "new_state",
    "FALLBACK_RULES",
    "FallbackRule",
    "fallback_action",
    "resolve_reason_code",
    "ConversationRouter",
    "ConversationRuntime",
    "run_conversation",
]
