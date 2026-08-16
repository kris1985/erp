"""Fast Path 接入层集成测试（DoD #9）。

用 monkeypatch 替换 finance_service.profit_report 与 Result Store 目录，
验证：开关关闭时观测性决策、开启后 ranking 走确定性链路、权限拒绝、
占比/集中度/表格渲染、可信指标门禁。
"""

from __future__ import annotations

from datetime import date
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
    assert "数据来源" in response["detail"]["content"] and "客户销售额排行" in response["detail"]["content"]
    assert response["fast_path"]["active"] is True
    assert response["fast_path"]["reason_code"] == "fast_path_ranking_v1"
    assert response["trust_metrics"]["unsupported_claim_escape_rate"] == 0.0
    assert response["trust_metrics"]["claim_precision"] == 1.0


def test_highest_customer_returns_single_row(monkeypatch) -> None:
    """「哪个客户销售额最高」limit=1：只返回居首客户，不得把全部客户当排行。"""
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="今年哪个客户销售额最高？", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    response = outcome.response
    assert response["semantic_plan"]["operations"][0]["top_n"] == 1
    assert response["presentation"]["rows"] == [["1", "客户 A", "1,235 万元"]]
    assert len(response["presentation"]["rows"]) == 1
    assert "客户 A居首" in response["reply"]


def test_superlative_variants_limit_and_order(monkeypatch) -> None:
    """最高级矩阵 E2E：最大/最多 → desc 居首；最低/最少 → asc 垫底；
    都只返回 1 行，且排序方向正确。"""
    _enable_fast_path(monkeypatch, True)
    cases = [
        ("哪个客户销售额最大", "客户 A居首", [["1", "客户 A", "1,235 万元"]]),
        ("哪个客户销售额最多", "客户 A居首", [["1", "客户 A", "1,235 万元"]]),
        ("哪个客户销售额最低", "客户 D垫底", [["1", "客户 D", "450 万元"]]),
        ("哪个客户销售额最少", "客户 D垫底", [["1", "客户 D", "450 万元"]]),
    ]
    for question, expected_word, expected_rows in cases:
        outcome = agent_fast_path.run_fast_path(
            None, tenant_id=1, question=question, conversation_id="c1",
            permission_codes=["menu.profit"],
        )
        assert outcome.status == "executed", question
        response = outcome.response
        assert response["semantic_plan"]["operations"][0]["top_n"] == 1, question
        assert response["presentation"]["rows"] == expected_rows, question
        assert len(response["presentation"]["rows"]) == 1, question
        assert expected_word in response["reply"], question


def test_superlative_with_n_returns_n_rows(monkeypatch) -> None:
    """「销售额最大的2笔」：limit=2 返回 2 行（desc）；「最小的2笔」返回
    2 行且 asc（垫底在前）。"""
    _enable_fast_path(monkeypatch, True)
    cases = [
        ("销售额最大的2笔", "客户 A居首", [["1", "客户 A", "1,235 万元"], ["2", "客户 B", "980 万元"]]),
        ("销售额最小的2笔", "客户 D垫底", [["1", "客户 D", "450 万元"], ["2", "客户 C", "760 万元"]]),
    ]
    for question, expected_word, expected_rows in cases:
        outcome = agent_fast_path.run_fast_path(
            None, tenant_id=1, question=question, conversation_id="c1",
            permission_codes=["menu.profit"],
        )
        assert outcome.status == "executed", question
        response = outcome.response
        assert response["semantic_plan"]["operations"][0]["top_n"] == 2, question
        assert response["presentation"]["rows"] == expected_rows, question
        assert len(response["presentation"]["rows"]) == 2, question
        assert expected_word in response["reply"], question


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


# ---------------------------------------------------------------------------
# metric_snapshot 切片（Direct Metric 快照路径）
# ---------------------------------------------------------------------------


def test_snapshot_observational_when_disabled(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, False)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="本月销售额多少", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "observational"
    assert outcome.observation["decision"]["reason_code"] == "fast_path_disabled_observational"
    assert outcome.observation["decision"]["fast_path_active"] is False


def test_snapshot_executes_when_enabled(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="本月销售额多少", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    response = outcome.response
    # 主回复 = 一句结论；表格卡片独立展示（fake summary.revenue = TOTAL 3,425 万元）
    assert "销售额 3,425 万元" in response["reply"]
    assert response["presentation"]["type"] == "table"
    assert response["presentation"]["columns"] == ["指标", "数值"]
    assert response["presentation"]["rows"][0] == ["销售额", "3,425 万元"]
    assert response["detail"]["available"] is True
    assert "数据来源" in response["detail"]["content"] and "销售额快照" in response["detail"]["content"]
    assert response["fast_path"]["active"] is True
    assert response["fast_path"]["reason_code"] == "fast_path_metric_snapshot_v1"
    assert response["trust_metrics"]["unsupported_claim_escape_rate"] == 0.0
    assert response["trust_metrics"]["claim_precision"] == 1.0


def test_snapshot_year_scope(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="今年销售额多少", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    scope = outcome.response["semantic_plan"]["scope"]
    assert scope["year"] == date.today().year
    assert scope.get("month") is None
    assert "销售额 3,425 万元" in outcome.response["reply"]


def test_snapshot_month_scope(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="2026 年 5 月销售额多少", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    scope = outcome.response["semantic_plan"]["scope"]
    assert scope["year"] == 2026
    assert scope["month"] == 5


def test_snapshot_policy_denied_without_permission(monkeypatch) -> None:
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="本月销售额多少", conversation_id="c1",
        permission_codes=[],
    )
    assert outcome.status == "rejected"
    assert outcome.rejection["reason_code"] == "POLICY_DENIED"


def test_snapshot_ranking_not_confused(monkeypatch) -> None:
    """排行问题不被快照路径拦截：ranking 仍由排行路径处理。"""
    _enable_fast_path(monkeypatch, True)
    outcome = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="客户销售额排行", conversation_id="c1",
        permission_codes=["menu.profit"],
    )
    assert outcome.status == "executed"
    assert outcome.response["fast_path"]["reason_code"] == "fast_path_ranking_v1"


def test_snapshot_period_switch_followup(monkeypatch, tmp_path) -> None:
    """turn1 本月销售额（Fast Path 写历史）→ turn2「上月呢」继承并切到上月：
    确定性链路返回 2026 年 7 月销售额。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "schedule_agent_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "agent_fast_path_enabled", True)
    from app.services import schedule_agent

    conv_id = "snap_conv_1"
    schedule_agent._upsert_conversation(1, conv_id, title="test")
    schedule_agent._save_ui_messages(1, conv_id, [
        {"role": "user", "content": "本月销售额多少", "path": "fast_path"},
        {"role": "assistant", "content": "2026 年 8 月销售额 1,235 万元。",
         "presentation": None, "path": "fast_path"},
    ])
    try:
        outcome = agent_fast_path.run_fast_path(
            None, tenant_id=1, question="上月呢", conversation_id=conv_id,
            permission_codes=["menu.profit"],
        )
    finally:
        # _catalog_conn 是模块级 lru_cache 共享连接：本测试把数据目录指向
        # tmp_path 会污染后续测试（如 test_sse_fast_path 的模块级 data_dir），
        # 用完必须清缓存，让后续调用按各自目录重建。
        schedule_agent._catalog_conn.cache_clear()
    assert outcome.status == "executed", f"turn2 应走快照 Fast Path，实际 {outcome.status}"
    scope = outcome.response["semantic_plan"]["scope"]
    assert scope["year"] == 2026
    assert scope["month"] == 7
    assert "2026 年 7 月销售额" in outcome.response["reply"]
