from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.agent_policy import get_policy_bundle, load_policy_bundle
from app.services.schedule_agent import _agent_run_config


def test_checked_in_agent_policy_has_versions_and_cross_file_contracts():
    bundle = get_policy_bundle()

    assert bundle.versions == {
        "global_policy": "1.0.0",
        "analysis_registry": "1.0.0",
        "metric_catalog": "1.0.0",
        "action_policy": "1.0.0",
        "ui_contract": "1.0.0",
    }
    assert bundle.analysis_registry.analysis_types["ranking"].required_slots == [
        "metric", "dimension", "time_range", "order", "limit",
    ]


def test_invalid_policy_schema_is_rejected_at_load_time(tmp_path: Path):
    source = Path(__file__).parents[1] / "app" / "agent_policy"
    for policy in source.glob("*.yaml"):
        (tmp_path / policy.name).write_text(policy.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "metric-catalog.yaml").write_text("version: '1.0.0'\nmetrics: []\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="agent_policy_schema_invalid"):
        load_policy_bundle(tmp_path)


def test_agent_trace_metadata_records_policy_versions(monkeypatch):
    monkeypatch.setattr(
        "app.services.schedule_agent.get_settings",
        lambda: SimpleNamespace(langsmith_tracing=False, langsmith_api_key=""),
    )
    _, config = _agent_run_config(
        tenant_id=1, conversation_id="conversation", thread_id="thread", transport="sync"
    )

    assert config["metadata"]["policy_versions"] == get_policy_bundle().versions
    assert config["metadata"]["runtime_versions"] == {
        "prompt": "1.0.0",
        "calculation_engine": "1.0.0",
        "evidence_guardrail": "1.0.0",
    }
