"""前端显示分层契约：detail 语义统一 + LLM 路径不泄漏原始回答。

三个决策（2026-08-17）：
1. ①链式推理（CoT）不进任何展示层，只进 Trace。
2. ②过程轨迹（工具调用）以「查询过程」折叠显示（一句话摘要）。
3. ③「完整业务分析/分析说明」永远是**可追溯的推导**，不是生成式原文：
   - Fast Path：kind="deterministic"（Renderer 生成的范围/来源/计算/判断）
   - LLM 路径：kind="summary"（结论/原因/已核验事实/查询时间），
     绝不包含 raw_reply。
"""

from __future__ import annotations

from app.services.schedule_agent import DecisionSummary, _llm_path_detail


def test_llm_detail_never_contains_raw_reply() -> None:
    """LLM 路径的 detail 只含结构化 summary，原始回答不得泄漏（回归）。"""
    raw = "这是一个未校验的 LLM 原始回答，包含思考过程和工具细节。"
    detail = _llm_path_detail(
        DecisionSummary(decision="本月销售额 3,425 万元", reason="出货额合计", facts=["客户A 1,235 万"]),
        raw,
        [{"name": "query_metric", "content": "{}"}],
    )
    assert detail["available"] is True
    assert detail["kind"] == "summary"
    content = detail["content"]
    assert "结论" in content and "关键原因" in content and "已核验事实" in content
    assert "查询过程" in content and "query_metric" in content
    assert raw not in content, "raw_reply 泄漏进 detail"


def test_llm_detail_hidden_when_nothing_verifiable() -> None:
    """无可追溯成分（空 decision/reason/facts/证据）时 available=false，前端隐藏。"""
    detail = _llm_path_detail(DecisionSummary(decision="", reason="", facts=[]), "某文本", [])
    assert detail["available"] is False
    assert detail["kind"] == "summary"


def test_fast_path_detail_kind_deterministic() -> None:
    """Fast Path detail 标记 kind=deterministic，供前端区分折叠标签。"""
    from app.services import agent_fast_path
    from app.config import get_settings
    from unittest.mock import patch
    from app.services import finance_service

    settings = get_settings()
    settings.agent_fast_path_enabled = True

    def fake_report(db, tenant_id, *, year=None, month=None, customer_id=None, keyword=None,
                    date_from=None, date_to=None, loss_only=False):
        return {"orders": [{"customer_name": "客户 A", "revenue": __import__("decimal").Decimal("12350000")}],
                "summary": {"revenue": __import__("decimal").Decimal("12350000")}, "year": year}

    with patch.object(finance_service, "profit_report", fake_report):
        outcome = agent_fast_path.run_fast_path(
            None, tenant_id=1, question="本月销售额多少", conversation_id="c1",
            permission_codes=["menu.profit"],
        )
    assert outcome.status == "executed"
    detail = outcome.response["detail"]
    assert detail["available"] is True
    assert detail["kind"] == "deterministic"
