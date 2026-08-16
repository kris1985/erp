"""顶层 Intent / Capability Router（架构定稿 §5）。

Router 不需要证明问题"很复杂"，只需判断 FastPath 是否可以安全执行：

1. 硬规则 capability gating：是否属于已注册、已验证的 FastPath 能力集合
   （复用 ``app.runtime.router.CapabilityRouter`` 的 FAST_PATH_METRICS /
   FAST_PATH_OPERATIONS 判定）。
2. 结构化语义编译：把问题编译成严格 schema（复用 ``semantic_compiler``
   的跨轮继承 + ``analysis_plans.parse_planner_json`` 的约束校验），不直接
   执行自然语言猜测。
3. 置信度与完整性校验：metric/dimension/time range/filters 满足执行要求
   （``validate_semantic_plan``）。
4. 无法证明可确定执行 → DeepAgent。

输出必须是可审计对象（RouteDecision）：route / capability / confidence /
reason_code / plan / fallback_action。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.runtime.orchestration.fallback import fallback_action
from app.runtime.orchestration.state import ConversationState, RouteDecision


class ConversationRouter:
    """三层路由：fast_path / deep_agent / clarification。

    职责边界：本 Router 只做「走哪条执行路径」的判定（Orchestration 控制面），
    不直接实现指标查询；数据能力在 Capability Layer（Domain Tools）。
    """

    def route(self, state: ConversationState, *, fast_path_enabled: bool) -> RouteDecision:
        """根据当前 state 决定执行路径。

        v1 实现：调用方（ConversationRuntime）已把问题编译为
        ``semantic_plan``（可空）；本 Router 基于 plan 完整性做分层判定。
        后续可接入 LLM propose 填充 plan（语义编译步）。
        """
        plan = state.get("semantic_plan")
        if plan is None:
            # 无 plan：可能是跨轮追问（semantic_compiler 处理）或非确定性
            # 问题。v1：交给 DeepAgent（开放推理），reason_code 可审计。
            return RouteDecision(
                route="deep_agent",
                capability="open_reasoning",
                confidence=0.0,
                reason_code="NO_SEMANTIC_PLAN",
                plan=None,
                fallback_action="to_deep_agent",
            )

        analysis_type = plan.get("analysis_type")
        metric_id = _metric_id_from_plan(plan)
        capability = f"{analysis_type}.v1" if analysis_type else "unknown.v1"

        # 1. 硬规则 capability gating：是否注册的 FastPath 能力集合
        if not _is_registered_fast_path_capability(analysis_type, metric_id):
            return RouteDecision(
                route="deep_agent",
                capability=capability,
                confidence=0.0,
                reason_code="NOT_IN_FAST_PATH_CAPABILITY_SET",
                plan=plan,
                fallback_action="to_deep_agent",
            )

        # 2. 完整性校验：plan 缺关键 slot → Clarification（不猜）
        missing = _missing_slots(plan, analysis_type)
        if missing:
            return RouteDecision(
                route="clarification",
                capability=capability,
                confidence=0.0,
                reason_code="MISSING_SLOT",
                plan=plan,
                fallback_action="clarify",
            )

        # 3. 开关未启用 → 观测模式（仍走 DeepAgent，但记录路由意图）
        if not fast_path_enabled:
            return RouteDecision(
                route="deep_agent",
                capability=capability,
                confidence=1.0,
                reason_code="FAST_PATH_DISABLED_OBSERVATIONAL",
                plan=plan,
                fallback_action="to_deep_agent",
            )

        # 4. 可通过确定性执行
        return RouteDecision(
            route="fast_path",
            capability=capability,
            confidence=1.0,
            reason_code="REGISTERED_PLAN_COMPLETE",
            plan=plan,
            fallback_action="respond",
        )


def _metric_id_from_plan(plan: dict[str, Any]) -> str | None:
    """plan.metric 是语义指标名（sales_amount），经 metric-catalog 解析为
    metric_id（finance.customer_sales_ranking）再对照 FAST_PATH_METRICS。"""
    metric_name = plan.get("metric")
    if isinstance(metric_name, dict):
        metric_name = metric_name.get("metric_id")
    if not isinstance(metric_name, str) or not metric_name:
        return None
    try:
        from app.services.agent_policy import get_policy_bundle

        catalog = get_policy_bundle().metric_catalog.metrics
        entry = catalog.get(metric_name)
        return entry.metric_id if entry is not None else None
    except Exception:
        return None


def _is_registered_fast_path_capability(
    analysis_type: str | None, metric_id: str | None
) -> bool:
    """硬规则 gating：分析类型 + 指标是否在注册的 FastPath 能力集合。"""
    from app.runtime.router import FAST_PATH_METRICS

    # ranking / metric_snapshot 是当前注册的 FastPath 分析类型
    if analysis_type not in ("ranking", "metric_snapshot"):
        return False
    if metric_id is None:
        return False
    return metric_id in FAST_PATH_METRICS


def _missing_slots(plan: dict[str, Any], analysis_type: str | None) -> list[str]:
    """plan 完整性：缺关键 slot → 澄清（与 analysis-registry required_slots 对齐）。"""
    required: tuple[str, ...]
    if analysis_type == "ranking":
        required = ("dimension", "time_range", "order", "limit")
    elif analysis_type == "metric_snapshot":
        required = ("time_range",)
    else:
        required = ()
    return [slot for slot in required if plan.get(slot) is None]
