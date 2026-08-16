"""SSE 端 Fast Path 集成测试（DoD #9 前端通路）。

验证 iter_chat_sse：开关开启时 ranking 请求产出 fast_path 事件与确定性
回复；开关关闭时观测决策随 done 事件返回且不改变现有流程。
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.config import get_settings
from app.services import schedule_agent
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


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(schedule_agent, "agent_available", lambda: {"enabled": True, "reason": ""})
    monkeypatch.setattr(finance_service, "profit_report", _fake_report)
    settings = get_settings()
    monkeypatch.setattr(settings, "schedule_agent_data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "agent_fast_path_enabled", True)


def _events(*, question: str, enabled: bool, permission_codes: list[str] | None = None) -> list[dict]:
    get_settings().agent_fast_path_enabled = enabled
    stream = schedule_agent.iter_chat_sse(1, question, permission_codes=permission_codes)
    return [
        json.loads(packet[6:])
        for packet in stream
        if packet.startswith("data:") and packet[6:].strip()
    ]


def test_sse_fast_path_executed() -> None:
    events = _events(question="客户销售额排行", enabled=True, permission_codes=["menu.profit"])
    types = [ev["type"] for ev in events]
    assert "fast_path" in types
    done = next(ev for ev in events if ev["type"] == "done")
    assert done["fast_path"]["active"] is True
    assert done["fast_path"]["reason_code"] == "fast_path_ranking_v1"
    assert "客户 A 销售额 1,235 万元，排名第 1" in done["reply"]
    assert done["trust_metrics"]["unsupported_claim_escape_rate"] == 0.0


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
