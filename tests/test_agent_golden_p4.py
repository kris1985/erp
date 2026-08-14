"""P4 golden contract suite for every registered workshop analysis type.

These cases are intentionally deterministic.  They are the release gate for
planner/registry/match/calculation governance; the offline LLM judge is only a
separate quality signal for decision prose.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services import analysis_result_store
from app.services.analysis_plans import (
    ExecutionPlan,
    QueryStep,
    SemanticPlan,
    TimeRange,
    match_execution_plan,
    resolve_execution_plan,
    validate_semantic_plan,
)


def _plans() -> dict[str, SemanticPlan]:
    current = TimeRange(year=2026, month=8)
    return {
        "metric_snapshot": SemanticPlan(analysis_type="metric_snapshot", metric="profit_overview", time_range=current),
        "period_comparison": SemanticPlan(analysis_type="period_comparison", metric="gross_profit", time_range=current, baseline=TimeRange(year=2026, month=7)),
        "ranking": SemanticPlan(analysis_type="ranking", metric="sales_amount", dimension="customer", time_range=current, order="desc", limit=10),
        "time_series": SemanticPlan(analysis_type="time_series", metric="gross_profit_trend", time_range=current, time_granularity="month"),
        "composition": SemanticPlan(analysis_type="composition", metric="cost_breakdown", dimension="cost_type", time_range=current),
        "data_table": SemanticPlan(analysis_type="data_table", metric="profit_order_details", entity="order", columns=["order_no"], time_range=current, order="desc", limit=20),
        "exception_list": SemanticPlan(analysis_type="exception_list", metric="delivery_risk_orders", entity="order", risk_condition="delivery_risk", time_range=current, order="asc", limit=10),
        "scenario": SemanticPlan(analysis_type="scenario", metric="order_intake_scenario", base_facts={"lines": [{"own_product_id": 1, "qty": 20}]}, assumptions={"is_rush": True}, calculation_method="order_intake_simulation", comparison_target="existing_schedule"),
        "attribution_analysis": SemanticPlan(analysis_type="attribution_analysis", metric="gross_profit_by_order", dimension="order", time_range=current),
    }


@pytest.mark.parametrize("analysis_type", list(_plans()))
def test_golden_normal_query_resolves_and_matches(analysis_type: str):
    plan = _plans()[analysis_type]
    execution = resolve_execution_plan(plan)

    assert execution.execution_plan_id.startswith("ep_")
    assert match_execution_plan(plan, execution) is True


@pytest.mark.parametrize(
    ("analysis_type", "expected_missing"),
    [
        ("metric_snapshot", ["metric", "time_range"]),
        ("period_comparison", ["metric", "time_range", "baseline"]),
        ("ranking", ["metric", "dimension", "time_range", "order", "limit"]),
        ("time_series", ["metric", "time_range", "time_granularity"]),
        ("composition", ["metric", "dimension", "time_range"]),
        ("data_table", ["entity", "columns", "time_range", "order", "limit"]),
        ("exception_list", ["entity", "risk_condition", "time_range", "order", "limit"]),
        ("scenario", ["base_facts", "assumptions", "calculation_method", "comparison_target"]),
        ("attribution_analysis", ["metric", "dimension", "time_range"]),
    ],
)
def test_golden_missing_slots_are_explicit(analysis_type: str, expected_missing: list[str]):
    assert validate_semantic_plan(SemanticPlan(analysis_type=analysis_type)) == expected_missing


def test_golden_decision_never_becomes_an_unbounded_metric_query():
    plan = SemanticPlan(analysis_type="decision")
    assert validate_semantic_plan(plan) == []
    with pytest.raises(ValueError, match="unsupported_execution_plan:decision"):
        resolve_execution_plan(plan)


@pytest.mark.parametrize("analysis_type", list(_plans()))
def test_golden_match_gate_rejects_changed_metric_time_dimension_order_or_limit(analysis_type: str):
    plan = _plans()[analysis_type]
    execution = resolve_execution_plan(plan)
    altered = execution.model_copy(deep=True)
    step = altered.steps[0]
    if analysis_type in {"metric_snapshot", "period_comparison", "composition", "data_table", "attribution_analysis"}:
        step.params["year"] = 1999
    elif analysis_type == "ranking":
        step.params["limit"] = 9
    elif analysis_type == "time_series":
        step.params["granularity"] = "week"
    elif analysis_type == "exception_list":
        step.params["limit"] = 9
    elif analysis_type == "scenario":
        step.params["is_rush"] = False

    assert match_execution_plan(plan, altered) is False


def test_golden_rejects_unregistered_metric_and_unregistered_filter():
    metric_plan = SemanticPlan(analysis_type="metric_snapshot", metric="invented_metric", time_range=TimeRange(year=2026))
    filter_plan = SemanticPlan(analysis_type="metric_snapshot", metric="profit_overview", time_range=TimeRange(year=2026), filters={"customer_id": 9})

    assert "metric_not_allowed" in validate_semantic_plan(metric_plan)
    assert "filters_not_allowed" in validate_semantic_plan(filter_plan)
    with pytest.raises(ValueError, match="filters_not_allowed"):
        resolve_execution_plan(filter_plan)


def test_golden_permission_denial_does_not_produce_metric_payload():
    from app.services import workshop_metrics

    result = workshop_metrics.query_metric(None, 1, "finance.profit_report", permission_codes=[])
    assert result == {
        "error": "forbidden",
        "message": "无权限查询 finance.profit_report，需要：menu.profit",
    }


def test_golden_calculation_lineage_must_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_result_store, "get_settings",
        lambda: type("Settings", (), {"schedule_agent_data_dir": str(tmp_path)})(),
    )
    with pytest.raises(ValueError, match="invalid_calculation_input_ref"):
        analysis_result_store.calculate(1, "sum", ["1000"])
    with pytest.raises(ValueError, match="unknown_result_ref"):
        analysis_result_store.calculate(1, "sum", ["r_aaaaaaaaaaaaaaaa.data.total"])


def test_golden_write_action_stops_until_human_approval():
    from app.db import Base
    from app.models import Tenant
    from app.services import approval_service

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        tenant = Tenant(name="P4 黄金测试工厂")
        db.add(tenant)
        db.flush()
        approval = approval_service.create_draft(
            db, tenant_id=tenant.id, action="confirm_schedule", requested_by=1,
            evidence=[{"fact": "产能已核验"}], impact_objects=[{"type": "schedule_draft", "id": 9}],
            execution_payload={"draft_id": 9},
        )
        approval_service.submit(db, approval)
        with pytest.raises(approval_service.ApprovalError, match="pending_approval:executed"):
            approval_service.mark_executed(db, approval, executor_id=2)
        approval_service.approve(db, approval, approver_id=3)
        approval_service.mark_executed(db, approval, executor_id=2)
        assert approval.status == "executed"
    finally:
        db.close()
