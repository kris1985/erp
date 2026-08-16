from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Tenant
from app.services import approval_service, agent_orchestration
from app.services.analysis_plans import PlannerOutput, SemanticPlan


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="P3 工厂")
    session.add(tenant)
    session.flush()
    return session, tenant


def test_scenario_gets_only_fixed_roles_and_replayable_child_plans():
    plan = SemanticPlan(analysis_type="scenario")
    children = agent_orchestration.build_child_plans("急单缺料会不会挤占产能", plan)
    assert [child.lifecycle_role for child in children] == ["order_commitment", "procurement_supply", "schedule_capacity"]
    assert all(child.child_plan_id.startswith("cp_") for child in children)
    assert all(child.parent_semantic_plan == plan.model_dump(mode="json") for child in children)


def test_single_domain_role_is_selected_from_plan_metric_not_keyword_guessing():
    plan = SemanticPlan(analysis_type="time_series", metric="gross_profit_trend")
    assert [role.id for role in agent_orchestration.select_roles("看一下趋势", plan)] == ["delivery_finance"]


def test_child_result_rejects_raw_data_and_reasoning():
    with pytest.raises(ValueError, match="internal_data"):
        agent_orchestration.sanitize_child_result({"child_plan_id": "cp_1", "lifecycle_role": "schedule_capacity", "raw_data": []})
    with pytest.raises(ValueError, match="internal_data"):
        agent_orchestration.sanitize_child_result({
            "child_plan_id": "cp_1", "lifecycle_role": "schedule_capacity",
            "typed_result": {"nested": {"result_id": "r_aaaaaaaaaaaaaaaa"}},
        })


def test_chat_child_plans_execute_as_compact_readonly_typed_results(monkeypatch):
    from app.services import schedule_agent

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    plan = SemanticPlan(
        analysis_type="scenario",
        base_facts={"lines": [{"own_product_id": 1, "qty": 20}]},
        assumptions={"is_rush": True}, calculation_method="order_intake_simulation",
        comparison_target="existing_schedule",
    )
    children = agent_orchestration.build_child_plans("急单缺料会不会挤占产能", plan)
    called: list[tuple[str, dict]] = []
    monkeypatch.setattr(schedule_agent, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        schedule_agent.workshop_metrics, "list_metrics",
        lambda **_kwargs: [{"id": metric, "name": metric} for metric in [
            "analytics.order_intake", "analytics.supply_chain", "analytics.capacity_load",
        ]],
    )

    def query_metric(_db, _tenant_id, metric_id, *, params, permission_codes):
        called.append((metric_id, params))
        return {"metric_id": metric_id, "data": {"summary": {"safe_fact": 1}, "result_id": "r_should_not_leave_executor"}}

    monkeypatch.setattr(schedule_agent.workshop_metrics, "query_metric", query_metric)
    results = schedule_agent._execute_child_plans(1, children, permission_codes=["menu.orders"])

    assert [metric_id for metric_id, _params in called] == [
        "analytics.order_intake", "analytics.supply_chain", "analytics.capacity_load",
    ]
    assert all(result.typed_result["status"] == "ok" for result in results)
    serialized = str([result.model_dump() for result in results])
    assert "r_should_not_leave_executor" not in serialized
    assert "raw_data" not in serialized


def test_chat_main_controller_receives_only_child_result_summaries(monkeypatch):
    from app.services import schedule_agent

    plan = SemanticPlan(analysis_type="scenario")
    planner = PlannerOutput(semantic_plan_id="sp_test", plan=plan)
    child = agent_orchestration.ChildPlan(
        child_plan_id="cp_test", lifecycle_role="schedule_capacity", analysis_type="scenario",
        allowed_metric_ids=["analytics.capacity_load"], parent_semantic_plan=plan.model_dump(mode="json"),
    )
    child_result = agent_orchestration.ChildResult(
        child_plan_id="cp_test", lifecycle_role="schedule_capacity",
        typed_result={"metric_id": "analytics.capacity_load", "status": "ok", "fact_count": 1},
        evidence_summary=["日期：2026-08-15"],
    )
    captured: dict = {}

    class Message:
        content = "暂不能确认。"

    class FakeAgent:
        def invoke(self, payload, *, config, context=None):
            captured["messages"] = payload["messages"]
            return {
                "messages": [Message()],
                "response": {
                    "conversation_id": "p3-chat", "run_id": "r", "title": None,
                    "reply": "暂不能确认。", "execution_mode": "agent",
                    "semantic_plan": None, "presentation": None, "detail": None,
                    "trust_metrics": None, "evidence": [], "evidence_guardrail": None,
                    "tool_traces": [], "fast_path": None, "fast_path_rejection": None,
                    "fast_path_observation": None, "failure": None, "messages": [],
                },
            }

    monkeypatch.setattr(schedule_agent, "agent_available", lambda: {"enabled": True})
    monkeypatch.setattr(schedule_agent, "_agent_run_config", lambda **_kwargs: ("run", {"metadata": {}}))
    monkeypatch.setattr(schedule_agent, "_run_auto_diagnostic_bundle", lambda *_args, **_kwargs: ([], [], [], "", planner, None))
    monkeypatch.setattr(schedule_agent.agent_orchestration, "select_roles", lambda *_args: [])
    monkeypatch.setattr(schedule_agent.agent_orchestration, "build_child_plans", lambda *_args: [child])
    monkeypatch.setattr(schedule_agent, "_execute_child_plans", lambda *_args, **_kwargs: [child_result])
    monkeypatch.setattr(schedule_agent, "_build_agent", lambda *_args, **_kwargs: FakeAgent())
    monkeypatch.setattr(schedule_agent, "_upsert_conversation", lambda *_args, **_kwargs: {"title": "测试"})
    monkeypatch.setattr(schedule_agent, "_record_agent_trace", lambda **_kwargs: None)
    monkeypatch.setattr(schedule_agent, "build_evidence_ledger", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(schedule_agent, "build_response_presentation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(schedule_agent, "_serialize_ui_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(schedule_agent, "get_settings", lambda: type("Settings", (), {"deepseek_model": "test"})())

    result = schedule_agent.chat(None, 1, "模拟插单", conversation_id="p3-chat")

    assert result["child_results"] == [child_result.model_dump()]
    assert "固定角色子诊断摘要" in captured["messages"][0]["content"]
    assert "r_" not in captured["messages"][0]["content"]


def test_governed_action_requires_approval_before_execution():
    db, tenant = _db()
    try:
        approval = approval_service.create_draft(
            db, tenant_id=tenant.id, action="confirm_schedule", requested_by=None,
            evidence=[{"fact": "产能已核验"}], impact_objects=[{"type": "schedule_draft", "id": 7}],
            execution_payload={"draft_id": 7},
        )
        approval_service.submit(db, approval)
        with pytest.raises(approval_service.ApprovalError, match="pending_approval:executed"):
            approval_service.mark_executed(db, approval, executor_id=1)
        approval_service.approve(db, approval, approver_id=2)
        approval_service.mark_executed(db, approval, executor_id=3)
        assert (approval.status, approval.approved_by, approval.executed_by) == ("executed", 2, 3)
    finally:
        db.close()


def test_expired_approval_cannot_resume_execution():
    db, tenant = _db()
    try:
        approval = approval_service.create_draft(
            db, tenant_id=tenant.id, action="create_purchase_order", requested_by=None,
            evidence=[{"fact": "缺料已确认"}], impact_objects=[{"type": "material", "id": 9}],
            execution_payload={"material_id": 9},
        )
        approval_service.submit(db, approval)
        approval.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        with pytest.raises(approval_service.ApprovalError, match="approval_expired"):
            approval_service.approve(db, approval, approver_id=1)
        assert approval.status == "expired"
    finally:
        db.close()
