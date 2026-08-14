"""P4: replay trace IDs, version stamps, and session-scoped locking."""

from types import SimpleNamespace

from app.services import agent_trace_service
from app.services.analysis_plans import parse_planner_json, resolve_execution_plan
from app.services.schedule_agent import _attach_plan_trace_metadata, _conversation_lock, _record_agent_trace


def test_trace_ledger_records_only_replay_identifiers(monkeypatch, tmp_path):
    monkeypatch.setattr(
        agent_trace_service,
        "get_settings",
        lambda: SimpleNamespace(schedule_agent_data_dir=str(tmp_path)),
    )
    recorded = agent_trace_service.record_run(
        run_id="run-1", tenant_id=7, conversation_id="conversation-1",
        semantic_plan_id="sp_123", execution_plan_id="ep_123", match_passed=True,
        result_ids=["r_aaaaaaaaaaaaaaaa", "r_aaaaaaaaaaaaaaaa"],
        calculation_ids=["c_bbbbbbbbbbbbbbbb"], approval_ids=["approval-9"],
        approval_statuses=["approved"],
        versions={"prompt": "1.0.0", "calculation_engine": "1.0.0"}, outcome="completed:supported",
    )

    assert recorded["result_ids"] == ["r_aaaaaaaaaaaaaaaa"]
    assert agent_trace_service.get_run(7, "run-1") == recorded


def test_conversation_lock_does_not_block_other_tenant_or_conversation():
    with _conversation_lock(1, "same", timeout=0) as first:
        assert first is True
        with _conversation_lock(1, "same", timeout=0) as same_conversation:
            assert same_conversation is False
        with _conversation_lock(2, "same", timeout=0) as other_tenant:
            assert other_tenant is True
        with _conversation_lock(1, "other", timeout=0) as other_conversation:
            assert other_conversation is True


def test_agent_trace_extracts_lineage_and_approval_references(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent_trace_service, "record_run", lambda **kwargs: captured.update(kwargs))
    planner = parse_planner_json({
        "analysis_type": "metric_snapshot", "metric": "profit_overview",
        "time_range": {"year": 2026, "month": 8},
    })
    assert planner.plan is not None
    execution = resolve_execution_plan(planner.plan)

    _record_agent_trace(
        tenant_id=1, conversation_id="c1", run_id="run-2", planner=planner,
        execution_plan=execution,
        tool_evidence=[{"content": '{"result_id":"r_aaaaaaaaaaaaaaaa","calculation_id":"c_bbbbbbbbbbbbbbbb","approval_id":"a1","status":"approved"}'}],
        guardrail={"reason": "supported"}, outcome="completed",
    )

    assert captured["execution_plan_id"] == execution.execution_plan_id
    assert captured["match_passed"] is True
    assert captured["result_ids"] == ["r_aaaaaaaaaaaaaaaa"]
    assert captured["calculation_ids"] == ["c_bbbbbbbbbbbbbbbb"]
    assert captured["approval_ids"] == ["a1"]
    assert captured["approval_statuses"] == ["approved"]


def test_run_config_gets_plan_identifiers_before_model_execution():
    planner = parse_planner_json({
        "analysis_type": "metric_snapshot", "metric": "profit_overview",
        "time_range": {"year": 2026, "month": 8},
    })
    assert planner.plan is not None
    execution = resolve_execution_plan(planner.plan)
    config = {"metadata": {}}

    _attach_plan_trace_metadata(config, planner, execution)

    assert config["metadata"] == {
        "semantic_plan_id": planner.semantic_plan_id,
        "execution_plan_id": execution.execution_plan_id,
        "semantic_match": True,
    }
