"""CapabilityRouter for the ranking + metric_snapshot slices (PR #6, §P2.1).

Routing is decided by the semantic plan + deterministic policy, never by a
router LLM in v1.  Execution and response modes are orthogonal fields:
``execution_mode`` picks how facts are produced, ``response_mode`` how the
answer is rendered.

The trusted chain is complete after PR #5, so the fast paths may be switched
on behind a feature flag.  With the flag off the router emits the same
decision in *observational* mode — recorded in Trace, traffic still goes
through the existing agent path — so the decision can be validated before any
production switch (slice §5.1).

Permission check runs after routing and before Metric Execute (slice §P2.1),
reusing the same policy source as the agent path.
"""

from __future__ import annotations

from typing import Literal, Union

from app.runtime.contracts import RuntimeModel
from app.runtime.resolver import ClarificationResult, ResolvedSemanticPlan

FAST_PATH_RULE = "route.fast_path.ranking@1"
SNAPSHOT_FAST_PATH_RULE = "route.fast_path.metric_snapshot@1"

# v1 fast-path operation set: the ranking atom plus its fixed dependencies.
FAST_PATH_OPERATIONS = {"ranking", "topn_total", "share_of_total", "metric_snapshot"}

# Metrics licensed for a deterministic fast path in v1.
FAST_PATH_METRICS = {"finance.customer_sales_ranking", "finance.sales_snapshot"}


class RouteDecision(RuntimeModel):
    execution_mode: Literal["DIRECT", "DETERMINISTIC", "AGENTIC", "MULTI_AGENT"]
    response_mode: Literal[
        "TEMPLATE", "DETERMINISTIC_RENDERER", "LIGHTWEIGHT_LLM", "SPECIALIST_LLM"
    ]
    reason_code: str
    rule_id: str | None = None
    estimated_cost: int = 0
    fast_path_active: bool = False


class CapabilityRouter:
    def route(
        self,
        plan_result: Union[ResolvedSemanticPlan, ClarificationResult],
        *,
        fast_path_enabled: bool,
    ) -> RouteDecision:
        if not isinstance(plan_result, ResolvedSemanticPlan):
            return RouteDecision(
                execution_mode="AGENTIC",
                response_mode="LIGHTWEIGHT_LLM",
                reason_code="clarification_required",
                fast_path_active=False,
            )
        if not self._is_fast_path_plan(plan_result):
            return RouteDecision(
                execution_mode="AGENTIC",
                response_mode="LIGHTWEIGHT_LLM",
                reason_code="not_in_fast_path_scope",
                fast_path_active=False,
            )
        if not fast_path_enabled:
            return RouteDecision(
                execution_mode="DIRECT",
                response_mode="DETERMINISTIC_RENDERER",
                reason_code="fast_path_disabled_observational",
                rule_id=self._rule_for(plan_result),
                estimated_cost=self._estimate_cost(plan_result),
                fast_path_active=False,
            )
        return RouteDecision(
            execution_mode="DIRECT",
            response_mode="DETERMINISTIC_RENDERER",
            reason_code=self._reason_for(plan_result),
            rule_id=self._rule_for(plan_result),
            estimated_cost=self._estimate_cost(plan_result),
            fast_path_active=True,
        )

    @staticmethod
    def _is_fast_path_plan(plan: ResolvedSemanticPlan) -> bool:
        if plan.metric.metric_id not in FAST_PATH_METRICS:
            return False
        return all(op.type in FAST_PATH_OPERATIONS for op in plan.operations)

    @staticmethod
    def _reason_for(plan: ResolvedSemanticPlan) -> str:
        if plan.metric.metric_id == "finance.sales_snapshot":
            return "fast_path_metric_snapshot_v1"
        return "fast_path_ranking_v1"

    @staticmethod
    def _rule_for(plan: ResolvedSemanticPlan) -> str:
        if plan.metric.metric_id == "finance.sales_snapshot":
            return SNAPSHOT_FAST_PATH_RULE
        return FAST_PATH_RULE

    @staticmethod
    def _estimate_cost(plan: ResolvedSemanticPlan) -> int:
        """Coarse planner estimate: queries + deterministic render, no LLM."""
        queries = sum(1 for op in plan.operations if op.type in {"ranking", "metric_snapshot"})
        return queries * 200 + 300  # ~tokens of projected context + rendering
