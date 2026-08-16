"""SSE 端 Fast Path 集成测试（DoD #9 前端通路）。

验证 iter_chat_sse：开关开启时 ranking 请求产出 fast_path 事件与确定性
回复；开关关闭时观测决策随 done 事件返回且不改变现有流程。
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.config import get_settings
from app.services import agent_fast_path, schedule_agent
from app.services import finance_service

FAKE_ORDERS = [
    {"customer_name": "客户 A", "revenue": Decimal("12350000")},
    {"customer_name": "客户 B", "revenue": Decimal("9800000")},
    {"customer_name": "客户 C", "revenue": Decimal("7600000")},
    {"customer_name": "客户 D", "revenue": Decimal("4500000")},
]


def _fake_report(db, tenant_id, *, year=None, month=None, customer_id=None, keyword=None,
                 date_from=None, date_to=None, loss_only=False):
    return {"orders": FAKE_ORDERS, "summary": {"revenue": Decimal("34250000")}, "year": year}


@pytest.fixture(scope="module")
def _data_dir(tmp_path_factory):
    """模块级共享数据目录：_catalog_conn 是 @lru_cache 共享连接（指向第一次
    调用的目录），各测试必须写同一目录，否则独立连接（如 _inherited_year）
    读到的是另一个目录。生产环境目录固定，无此问题。"""
    return tmp_path_factory.mktemp("sse_data")


@pytest.fixture(autouse=True)
def _env(monkeypatch, _data_dir):
    monkeypatch.setattr(schedule_agent, "agent_available", lambda: {"enabled": True, "reason": ""})
    monkeypatch.setattr(finance_service, "profit_report", _fake_report)
    settings = get_settings()
    monkeypatch.setattr(settings, "schedule_agent_data_dir", str(_data_dir))
    monkeypatch.setattr(settings, "agent_fast_path_enabled", True)


def _events(*, question: str, enabled: bool, permission_codes: list[str] | None = None) -> list[dict]:
    settings = get_settings()
    previous = settings.agent_fast_path_enabled
    settings.agent_fast_path_enabled = enabled
    try:
        stream = schedule_agent.iter_chat_sse(1, question, permission_codes=permission_codes)
        return [
            json.loads(packet[6:])
            for packet in stream
            if packet.startswith("data:") and packet[6:].strip()
        ]
    finally:
        settings.agent_fast_path_enabled = previous


def test_sse_fast_path_executed() -> None:
    events = _events(question="客户销售额排行", enabled=True, permission_codes=["menu.profit"])
    types = [ev["type"] for ev in events]
    assert "fast_path" in types
    done = next(ev for ev in events if ev["type"] == "done")
    assert done["fast_path"]["active"] is True
    assert done["fast_path"]["reason_code"] == "fast_path_ranking_v1"
    assert "客户 A居首" in done["reply"]
    assert done["trust_metrics"]["unsupported_claim_escape_rate"] == 0.0
    assert done["detail"]["available"] is True
    assert "数据来源" in done["detail"]["content"]


def test_sse_fast_path_table_presentation() -> None:
    events = _events(question="给我客户销售额表格", enabled=True, permission_codes=["menu.profit"])
    presentation = next(ev["presentation"] for ev in events if ev.get("type") == "presentation")
    assert presentation["type"] == "table"
    assert presentation["rows"][0] == ["1", "客户 A", "1,235 万元"]


def test_sse_fast_path_observational_when_disabled() -> None:
    events = _events(question="客户销售额排行", enabled=False, permission_codes=["menu.profit"])
    done = next(ev for ev in events if ev["type"] == "done")
    assert done.get("fast_path_observation", {}).get("decision", {}).get("reason_code") == "fast_path_disabled_observational"
    assert "fast_path" not in done  # 未启用时不携带执行标记


def test_sse_fast_path_policy_denied() -> None:
    events = _events(question="客户销售额排行", enabled=True, permission_codes=[])
    done = next(ev for ev in events if ev["type"] == "done")
    assert done.get("fast_path_rejection", {}).get("reason_code") == "POLICY_DENIED"
    assert "无权限" in done["reply"]


def test_filter_followup_uses_fast_path() -> None:
    """turn1 排行（Fast Path 写历史）→ turn2「只要大于500万的」走确定性链路：
    表格只显示过滤后的 3 行（而非 LLM 重查全量 4 行），结论句带过滤条件。"""
    events = _events(question="客户销售额排行", enabled=True, permission_codes=["menu.profit"])
    meta = next(ev for ev in events if ev["type"] == "meta")
    conv_id = meta["conversation_id"]

    out = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="只要大于500万的", conversation_id=conv_id,
        permission_codes=["menu.profit"],
    )
    assert out.status == "executed", f"turn2 应走 Fast Path，实际 {out.status}"
    response = out.response
    rows = response["presentation"]["rows"]
    assert rows == [
        ["1", "客户 A", "1,235 万元"],
        ["2", "客户 B", "980 万元"],
        ["3", "客户 C", "760 万元"],
    ], f"表格应只含 >500万 的 3 行：{rows}"
    assert "大于 500 万元" in response["reply"]
    assert "共 3 家" in response["reply"]
    assert "客户 D" not in response["reply"]  # 450 万被过滤
    assert "销售额 > 500 万元" in response["detail"]["content"]


def test_filter_followup_without_history_is_not_applicable() -> None:
    """无排行上下文时「大于1000的」不猜测为排行过滤（交给 LLM 路径）。"""
    settings = get_settings()
    settings.agent_fast_path_enabled = True
    try:
        stream = schedule_agent.iter_chat_sse(1, "只要大于1000的", permission_codes=["menu.profit"])
        events = [json.loads(p[6:]) for p in stream if p.startswith("data:")]
    finally:
        settings.agent_fast_path_enabled = False
    done = next((ev for ev in events if ev["type"] == "done"), None)
    assert done is not None
    assert "fast_path" not in done  # 未走 Fast Path（无排行历史）


def test_cross_path_history_injection() -> None:
    """混合路径跨轮修复回归：turn1 走 Fast Path（不写 LangGraph checkpoint），
    turn2 走 LLM 路径时必须从 ui_messages 注入历史，否则 LLM 看不到 turn1
    （「只要查询大于1000元的」无法继承「客户销售额排行」语义）。"""
    events = _events(question="客户销售额排行", enabled=True, permission_codes=["menu.profit"])
    meta = next(ev for ev in events if ev["type"] == "meta")
    conv_id = meta["conversation_id"]

    from app.services import schedule_agent

    agent_messages = [{"role": "user", "content": "只要查询大于1000元的"}]
    schedule_agent._inject_cross_path_history(1, conv_id, agent_messages)
    injected = [m for m in agent_messages if m["role"] == "system" and "历史对话" in m["content"]]
    assert injected, "未注入跨路径历史"
    assert "客户销售额排行" in injected[0]["content"]
    assert "居首" in injected[0]["content"]


def test_cross_path_history_not_injected_without_fast_path_turn() -> None:
    """全 LLM 会话（ui_messages 无 fast_path 标记）→ 不注入：历史已在
    LangGraph checkpoint，注入会造成重复上下文。"""
    from app.services import schedule_agent

    conv_id = "llm_only_conv"
    schedule_agent._upsert_conversation(1, conv_id, title="test")
    schedule_agent._save_ui_messages(1, conv_id, [
        {"role": "user", "content": "turn1 问题"},
        {"role": "assistant", "content": "turn1 回复"},
    ])
    agent_messages = [{"role": "user", "content": "追问题"}]
    schedule_agent._inject_cross_path_history(1, conv_id, agent_messages)
    assert not any("历史对话" in m["content"] for m in agent_messages), "全 LLM 会话不应注入历史"
