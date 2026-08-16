"""Fast Path 接入层集成测试（DoD #9）。

用 monkeypatch 替换 finance_service.profit_report 与 Result Store 目录，
验证：开关关闭时观测性决策、开启后 ranking 走确定性链路、权限拒绝、
占比/集中度/表格渲染、可信指标门禁。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import get_settings
from app.services import agent_fast_path, analysis_result_store, finance_service

FAKE_ORDERS = [
    {"customer_name": "客户 A", "revenue": Decimal("12350000")},
    {"customer_name": "客户 B", "revenue": Decimal("9800000")},
    {"customer_name": "客户 C", "revenue": Decimal("7600000")},
    {"customer_name": "客户 D", "revenue": Decimal("4500000")},
]
TOTAL = Decimal("34250000")


def fake_profit_report(db, tenant_id, *, year=None, month=None, customer_id=None, keyword=None, date_from=None, date_to=None, loss_only=False):
    return {"orders": FAKE_ORDERS, "summary": {"revenue": TOTAL}, "year": year}


@pytest.fixture(autouse=True)
def _fake_report(monkeypatch):
    monkeypatch.setattr(finance_service, "profit_report", fake_profit_report)


@pytest.fixture(autouse=True)
def _tmp_result_store(monkeypatch, tmp_path):
    def fake_settings():
        return type(
            "Settings",
            (),
            {
                "schedule_agent_data_dir": str(tmp_path),
                "analysis_result_ttl_seconds": 3600,
                "analysis_result_max_per_session": 200,
            },
        )()

    monkeypatch.setattr(analysis_result_store, "get_settings", fake_settings)


def _enable_fast_path(monkeypatch, enabled: bool) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_fast_path_enabled", enabled)


def test_non_ranking_question_not_applicable(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="今天天气怎么样", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "not_applicable"


def test_ranking_observational_when_disabled(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, False)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="客户销售额排行", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "observational"
    assert outcome.observation["decision"]["reason_code"] == "fast_path_disabled_observational"
    assert outcome.observation["decision"]["fast_path_active"] is False


def test_ranking_executes_when_enabled(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="客户销售额排行", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    response = outcome.response
    # 主回复 = 一句结论；表格卡片独立展示
    assert "客户 A居首" in response["reply"]
    assert "1,235 万元" in response["reply"]
    assert response["presentation"]["type"] == "table"
    assert response["presentation"]["rows"][0] == ["1", "客户 A", "1,235 万元"]
    assert response["detail"]["available"] is True
    assert "断言" in response["detail"]["content"] and "Fact" in response["detail"]["content"]
    assert response["fast_path"]["active"] is True
    assert response["fast_path"]["reason_code"] == "fast_path_ranking_v1"
    assert response["trust_metrics"]["unsupported_claim_escape_rate"] == 0.0
    assert response["trust_metrics"]["claim_precision"] == 1.0


def test_share_sentence_without_judgement(monkeypatch) -> None:
    """top2 占比 0.6467 < 0.80 -> 占比句有、集中度判断无。"""
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="前两名客户占多少", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    assert "占" in outcome.response["reply"]
    assert "客户集中度较高" not in outcome.response["reply"]


def test_high_concentration_judgement(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    monkeypatch.setattr(
        finance_service,
        "profit_report",
        lambda *a, **k: {
            "orders": [
                {"customer_name": "客户 A", "revenue": Decimal("60000000")},
                {"customer_name": "客户 B", "revenue": Decimal("30000000")},
                {"customer_name": "客户 C", "revenue": Decimal("5000000")},
                {"customer_name": "客户 D", "revenue": Decimal("5000000")},
            ],
            "summary": {"revenue": Decimal("100000000")},
        },
    )
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="客户集中度怎么样", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    assert "客户集中度较高" in outcome.response["reply"]


def test_table_mode(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="给我客户销售额表格", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    presentation = outcome.response["presentation"]
    assert presentation["type"] == "table"
    assert presentation["columns"] == ["排名", "客户", "销售额"]
    assert presentation["rows"][0] == ["1", "客户 A", "1,235 万元"]


def test_policy_denied_without_permission(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="客户销售额排行", conversation_id="c1",
        permission_codes=[],
    )
    assert outcome.status == "rejected"
    assert outcome.rejection["reason_code"] == "POLICY_DENIED"


def test_year_from_question(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="2025 年客户销售额排行", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    assert outcome.response["semantic_plan"]["scope"]["year"] == 2025
