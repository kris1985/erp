"""CapabilityRouter tests (PR #6, slice §P2.1).

Acceptance: six simple analysis types must not spawn SubAgents; routing is
deterministic (no router LLM); execution/response modes are orthogonal; the
fast path is observational until the feature flag turns it on.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.runtime.contracts import MetricRef, OperationSpec, ResolvedSemanticPlan, TimeScope
from app.runtime.resolver import ClarificationResult, RankingRequest, RankingResolver
from app.runtime.router import (
    FAST_PATH_RULE,
    CapabilityRouter,
)

AS_OF = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)
ROUTER = CapabilityRouter()
RESOLVER = RankingResolver()


def ranking_request(**overrides) -> RankingRequest:
    base = {
        "metric_id": "finance.customer_sales_ranking",
        "year": 2026,
        "as_of": AS_OF,
    }
    base.update(overrides)
    return RankingRequest(**base)


def test_ranking_plan_routes_to_fast_path_when_enabled() -> None:
    plan = RESOLVER.resolve(ranking_request())
    decision = ROUTER.route(plan, fast_path_enabled=True)
    assert decision.execution_mode == "DIRECT"
    assert decision.response_mode == "DETERMINISTIC_RENDERER"
    assert decision.reason_code == "fast_path_ranking_v1"
    assert decision.rule_id == FAST_PATH_RULE
    assert decision.fast_path_active is True
    assert decision.estimated_cost > 0


def test_fast_path_observational_when_disabled() -> None:
    plan = RESOLVER.resolve(ranking_request())
    decision = ROUTER.route(plan, fast_path_enabled=False)
    # Same path decision, but traffic must not switch yet (slice §5.1).
    assert decision.execution_mode == "DIRECT"
    assert decision.reason_code == "fast_path_disabled_observational"
    assert decision.fast_path_active is False
    assert decision.rule_id == FAST_PATH_RULE


def test_clarification_never_takes_fast_path() -> None:
    clarification = RESOLVER.resolve(ranking_request(year=None))
    assert isinstance(clarification, ClarificationResult)
    decision = ROUTER.route(clarification, fast_path_enabled=True)
    assert decision.execution_mode == "AGENTIC"
    assert decision.fast_path_active is False
    assert decision.reason_code == "clarification_required"


def test_out_of_scope_plan_stays_agentic() -> None:
    other = ResolvedSemanticPlan(
        semantic_plan_id="sp_other",
        metric=MetricRef(metric_id="finance.net_profit", definition_version="1.0.0"),
        dimension="customer",
        scope=TimeScope(year=2026),
        as_of=AS_OF,
        operations=[OperationSpec(operation_id="op_ranking", type="ranking", top_n=10, sort="desc")],
    )
    decision = ROUTER.route(other, fast_path_enabled=True)
    assert decision.execution_mode == "AGENTIC"
    assert decision.reason_code == "not_in_fast_path_scope"
    assert decision.fast_path_active is False


def test_share_plan_is_still_fast_path() -> None:
    plan = RESOLVER.resolve(ranking_request(needs_share=True))
    decision = ROUTER.route(plan, fast_path_enabled=True)
    assert decision.fast_path_active is True
    assert decision.execution_mode == "DIRECT"
