"""统一 Response/Guardrail/Evidence P3 测试（架构定稿 §9 P3）。

验证：
- fold_evidence 从 FastPath execution_result（result_ids + facts）折叠
- apply_response_guardrail 是唯一 guardrail 入口（一套语义）
- guardrail 失败 → 显式 EVIDENCE_FAILED → fail_closed（不静默放行）
- 端到端：FastPath 分支产出 → response 节点 fold + guardrail → SUCCESS
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.runtime.orchestration import (
    ConversationRuntime,
    apply_response_guardrail,
    fast_path_branch,
    fold_evidence,
)
from app.runtime.orchestration.state import ExecutionResult, new_state


# ---------------------------------------------------------------------------
# fold_evidence
# ---------------------------------------------------------------------------


def test_fold_evidence_from_fastpath_result() -> None:
    state = new_state(question="客户销售额排行")
    state["route"] = {"route": "fast_path", "capability": "ranking.v1"}
    state["execution_result"] = ExecutionResult(
        result_ids=["r_1"],
        assertion_count=2,
        verified_count=2,
        payload={"reply": "客户 A 居首", "facts": ["客户销售额 12350000 CNY（2026年）"]},
    )
    out = fold_evidence(state)
    assert out["evidence"][0]["id"] == "r_1"
    assert out["evidence"][0]["status"] == "已核验"
    assert out["evidence"][0]["facts"] == ["客户销售额 12350000 CNY（2026年）"]


def test_fold_evidence_dedupes() -> None:
    state = new_state(question="x")
    state["route"] = {"route": "fast_path", "capability": "ranking.v1"}
    state["execution_result"] = ExecutionResult(result_ids=["r_1"], payload={})
    state["evidence"] = [{"id": "r_1", "source": "ranking.v1", "status": "已核验", "facts": []}]
    out = fold_evidence(state)
    assert len(out["evidence"]) == 1  # 不重复


# ---------------------------------------------------------------------------
# apply_response_guardrail —— 唯一 guardrail 入口
# ---------------------------------------------------------------------------


def test_guardrail_passes_with_traceable_numbers(monkeypatch) -> None:
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent, "apply_evidence_guardrail",
        lambda q, reply, evidence: (reply, {"passed": True, "reason": "ok"}),
    )
    state = new_state(question="客户销售额排行")
    state["execution_result"] = ExecutionResult(
        result_ids=["r_1"], payload={"reply": "客户 A 居首，销售额 1,235 万元。"},
    )
    state["evidence"] = [{
        "id": "r_1", "source": "ranking.v1", "status": "已核验",
        "facts": ["客户销售额 12350000 CNY（2026年）"],
    }]
    out = apply_response_guardrail(state)
    assert "_guardrail" in out
    assert out["execution_result"]["payload"]["reply"] == "客户 A 居首，销售额 1,235 万元。"


def test_guardrail_failure_fails_closed(monkeypatch) -> None:
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent, "apply_evidence_guardrail",
        lambda q, reply, evidence: (reply, {"passed": False, "reason": "unsupported_measurable_claim"}),
    )
    state = new_state(question="客户销售额排行")
    state["execution_result"] = ExecutionResult(
        result_ids=["r_1"], payload={"reply": "客户 A 居首，销售额 999,999 万元。"},
    )
    state["evidence"] = [{
        "id": "r_1", "source": "ranking.v1", "status": "已核验",
        "facts": ["客户销售额 12350000 CNY（2026年）"],
    }]
    out = apply_response_guardrail(state)
    assert out["failure"]["reason_code"] == "EVIDENCE_FAILED"
    assert out["failure"]["action"] == "fail_closed"


def test_guardrail_empty_reply_fails_closed(monkeypatch) -> None:
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent, "apply_evidence_guardrail",
        lambda q, reply, evidence: (reply, {"passed": True}),
    )
    state = new_state(question="x")
    state["execution_result"] = ExecutionResult(result_ids=[], payload={"reply": ""})
    out = apply_response_guardrail(state)
    assert out["failure"]["reason_code"] == "EVIDENCE_FAILED"


# ---------------------------------------------------------------------------
# 端到端：FastPath 分支 → response 节点（fold + guardrail）
# ---------------------------------------------------------------------------


@pytest.fixture
def _domain_tool(monkeypatch):
    from app.services import workshop_metrics

    def fake_query(db, tenant_id, metric_id, params=None, permission_codes=None):
        return {
            "metric_id": metric_id,
            "data": {
                "year": (params or {}).get("year"),
                "order": (params or {}).get("order"),
                "limit": (params or {}).get("limit"),
                "items": [
                    {"customer_name": "客户 A", "sales_amount": 12350000.0},
                    {"customer_name": "客户 B", "sales_amount": 9800000.0},
                    {"customer_name": "客户 C", "sales_amount": 7600000.0},
                    {"customer_name": "客户 D", "sales_amount": 4500000.0},
                ],
                "total": 4,
            },
            "chart": None,
        }

    monkeypatch.setattr(workshop_metrics, "query_metric", fake_query)


@pytest.fixture
def _guardrail_pass(monkeypatch):
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent, "apply_evidence_guardrail",
        lambda q, reply, evidence: (reply, {"passed": True, "reason": "ok"}),
    )


def test_runtime_fastpath_through_guardrail(monkeypatch, _domain_tool, _guardrail_pass) -> None:
    from app.services import schedule_agent

    plan_json = (
        '{"analysis_type": "ranking", "metric": "sales_amount", "dimension": "customer", '
        '"time_range": {"year": 2026}, "order": "desc", "limit": 2, "filters": {}}'
    )

    class _Resp:
        content = plan_json

    monkeypatch.setattr(
        schedule_agent, "_make_model",
        lambda: type("M", (), {"invoke": lambda *a, **k: _Resp()}),
    )
    runtime = ConversationRuntime(fast_path_enabled=True, fast_path_node=fast_path_branch)
    out = runtime.invoke(
        question="客户销售额排行",
        tenant_id=1, permission_codes=["menu.profit"], conversation_id="c_gr",
        _db=object(),
    )
    assert out["route"]["route"] == "fast_path"
    assert out["route"]["reason_code"] == "SUCCESS"
    assert out["presentation"]["rows"][0] == ["1", "客户 A", "1,235 万元"]
    # 统一 evidence（带 facts，供 guardrail）
    assert out["evidence"][0]["id"] == out["execution_result"]["result_ids"][0]
    assert out["evidence"][0]["facts"], "evidence 应携带数字 facts 供 guardrail 校验"
    assert out["_guardrail"]["passed"] is True


def test_runtime_fastpath_guardrail_fail(monkeypatch, _domain_tool) -> None:
    """guardrail 拒绝 → fail_closed（FastPath 不再硬编码 passed）。"""
    from app.services import schedule_agent

    plan_json = (
        '{"analysis_type": "ranking", "metric": "sales_amount", "dimension": "customer", '
        '"time_range": {"year": 2026}, "order": "desc", "limit": 2, "filters": {}}'
    )

    class _Resp:
        content = plan_json

    monkeypatch.setattr(
        schedule_agent, "_make_model",
        lambda: type("M", (), {"invoke": lambda *a, **k: _Resp()}),
    )
    monkeypatch.setattr(
        schedule_agent, "apply_evidence_guardrail",
        lambda q, reply, evidence: (reply, {"passed": False, "reason": "unsupported_measurable_claim"}),
    )
    runtime = ConversationRuntime(fast_path_enabled=True, fast_path_node=fast_path_branch)
    out = runtime.invoke(
        question="客户销售额排行",
        tenant_id=1, permission_codes=["menu.profit"], conversation_id="c_gr_fail",
        _db=object(),
    )
    assert out["failure"]["reason_code"] == "EVIDENCE_FAILED"
    assert out["failure"]["action"] == "fail_closed"
    assert out["route"]["reason_code"] != "SUCCESS"
