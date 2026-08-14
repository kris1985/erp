import pytest

from app.services import analysis_result_store
from app.services.schedule_agent import build_response_presentation


def test_result_store_calculates_only_from_persisted_field_refs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_result_store, "get_settings",
        lambda: type("Settings", (), {"schedule_agent_data_dir": str(tmp_path)})(),
    )
    result_id = analysis_result_store.put_result(
        1, "finance.profit_report",
        {"data": {"summary": {"material_cost": 407.8, "labor_cost": 354.7}}},
        {"year": 2026, "month": 8},
    )
    calculated = analysis_result_store.calculate(
        1, "sum", [
            f"{result_id}.data.summary.material_cost",
            f"{result_id}.data.summary.labor_cost",
        ], precision=1,
    )
    assert calculated["value"] == 762.5
    assert calculated["calculation_id"].startswith("c_")
    value, lineage = analysis_result_store.read_ref(1, f"{calculated['calculation_id']}.value")
    assert value == 762.5
    assert lineage["operation"] == "sum"
    assert [item["ref"] for item in calculated["inputs"]] == [
        f"{result_id}.data.summary.material_cost",
        f"{result_id}.data.summary.labor_cost",
    ]


def test_result_store_rejects_unverified_or_non_numeric_inputs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_result_store, "get_settings",
        lambda: type("Settings", (), {"schedule_agent_data_dir": str(tmp_path)})(),
    )
    with pytest.raises(ValueError, match="invalid_calculation_input_ref"):
        analysis_result_store.calculate(1, "sum", ["1000"])


@pytest.mark.parametrize("raw_input", ["1000", "2026-08-15", "12.5%", "r_0123456789abcdef", "c_0123456789abcdef.total"])
def test_calculation_rejects_literals_and_non_value_refs(monkeypatch, tmp_path, raw_input):
    monkeypatch.setattr(
        analysis_result_store, "get_settings",
        lambda: type("Settings", (), {"schedule_agent_data_dir": str(tmp_path)})(),
    )
    with pytest.raises(ValueError, match="invalid_calculation_input_ref"):
        analysis_result_store.calculate(1, "sum", [raw_input])


def test_calculation_accepts_a_prior_calculation_value_ref(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_result_store, "get_settings",
        lambda: type("Settings", (), {"schedule_agent_data_dir": str(tmp_path)})(),
    )
    result_id = analysis_result_store.put_result(1, "metric", {"data": {"a": 8, "b": 2}}, {})
    quotient = analysis_result_store.calculate(1, "divide", [f"{result_id}.data.a", f"{result_id}.data.b"])
    doubled = analysis_result_store.calculate(1, "sum", [f"{quotient['calculation_id']}.value", f"{quotient['calculation_id']}.value"])
    assert doubled["value"] == 8


def test_metric_snapshot_reads_values_from_result_refs_not_evidence_text(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_result_store, "get_settings",
        lambda: type("Settings", (), {"schedule_agent_data_dir": str(tmp_path)})(),
    )
    result_id = analysis_result_store.put_result(
        1, "finance.profit_report",
        {"data": {"summary": {"revenue": 1000, "total_cost": 250, "gross_profit": 750}}}, {},
    )
    presentation = build_response_presentation(
        "本月收入、成本、毛利各多少？",
        [{"source": "利润报表", "result_id": result_id, "facts": []}], tenant_id=1,
    )
    assert presentation["items"][0]["value"] == 1000
    assert presentation["items"][0]["ref"] == f"{result_id}.data.summary.revenue"


def test_cost_composition_is_calculated_from_result_refs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_result_store, "get_settings",
        lambda: type("Settings", (), {"schedule_agent_data_dir": str(tmp_path)})(),
    )
    result_id = analysis_result_store.put_result(
        1, "finance.profit_report",
        {"data": {"summary": {"material_cost": 50, "labor_cost": 30, "other_cost": 20, "total_cost": 100}}}, {},
    )
    presentation = build_response_presentation(
        "本月成本构成和占比", [{"source": "利润报表", "result_id": result_id, "facts": []}], tenant_id=1,
    )
    assert presentation == {
        "type": "composition", "title": "成本构成",
        "items": [
            {"label": "材料", "value": 50, "unit": "元", "share": 50.0, "share_ref": presentation["items"][0]["share_ref"]},
            {"label": "人工", "value": 30, "unit": "元", "share": 30.0, "share_ref": presentation["items"][1]["share_ref"]},
            {"label": "其它", "value": 20, "unit": "元", "share": 20.0, "share_ref": presentation["items"][2]["share_ref"]},
        ],
    }


def test_result_is_session_scoped_and_inspection_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_result_store, "get_settings",
        lambda: type("Settings", (), {"schedule_agent_data_dir": str(tmp_path)})(),
    )
    result_id = analysis_result_store.put_result(
        1, "finance.profit_report", {"data": {"values": [1, 2, 3], "total": 6}}, {}, session_id="chat-a",
    )
    inspected = analysis_result_store.inspect_result(1, result_id, ["data.values"], 2, session_id="chat-a")
    assert inspected["fields"] == {"data.values": [1, 2]}
    assert any(field["field"] == "data.total" for field in inspected["schema"])
    with pytest.raises(ValueError, match="unknown_result_ref"):
        analysis_result_store.inspect_result(1, result_id, session_id="chat-b")


def test_calculation_operations_are_replayable_and_reference_only(monkeypatch, tmp_path):
    monkeypatch.setattr(
        analysis_result_store, "get_settings",
        lambda: type("Settings", (), {"schedule_agent_data_dir": str(tmp_path)})(),
    )
    result_id = analysis_result_store.put_result(
        1, "finance.profit_report", {"data": {"current": 120, "previous": 100, "peer": 140}}, {}, session_id="chat-a",
    )
    yoy = analysis_result_store.calculate(1, "yoy", [f"{result_id}.data.current", f"{result_id}.data.previous"], session_id="chat-a")
    rank = analysis_result_store.calculate(1, "rank", [f"{result_id}.data.current", f"{result_id}.data.previous", f"{result_id}.data.peer"], session_id="chat-a")
    replay = analysis_result_store.replay_calculation(1, yoy["calculation_id"], session_id="chat-a")
    assert yoy["value"] == 20.0
    assert rank["value"] == 2.0
    assert replay["matches"] is True
    assert replay["inputs"][0]["ref"] == f"{result_id}.data.current"
