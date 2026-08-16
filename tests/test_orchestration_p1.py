"""Bounded Semantic Workflow 子图 P1 测试（架构定稿 §9 P1，修正版）。

FastPath 不是"0 模型"：semantic_compile 用 LLM（结构化输出 + 本地校验），
inheritance_resolve 两级（规则优先，必要时 LLM）。测试验证：
- 六节点（semantic_compile/inheritance_resolve/plan_validate/
  deterministic_executor/evidence_validate/controlled_render）
- 每节点失败返回显式 reason_code + action（不宽泛 except）
- 继承第一层（确定性）从 previous_plans 结构化状态替换，不调 LLM
- 端到端挂到 ConversationRuntime
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.runtime.orchestration import (
    ConversationRuntime,
    controlled_render,
    deterministic_executor,
    evidence_validate,
    fast_path_branch,
    inheritance_resolve,
    plan_validate,
    semantic_compile,
)
from app.runtime.orchestration.state import new_state

RANKING_PLAN = {
    "analysis_type": "ranking",
    "metric": "sales_amount",
    "dimension": "customer",
    "time_range": {"year": 2026},
    "order": "desc",
    "limit": 2,
    "filters": {},
}

SNAPSHOT_PLAN = {
    "analysis_type": "metric_snapshot",
    "metric": "sales_snapshot",
    "time_range": {"year": 2026, "month": 8},
}

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
    from app.config import get_settings
    from app.services import analysis_result_store, finance_service

    settings = get_settings()
    monkeypatch.setattr(settings, "schedule_agent_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "analysis_result_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "analysis_result_max_per_session", 200)
    monkeypatch.setattr(finance_service, "profit_report", _fake_report)
    monkeypatch.setattr(analysis_result_store, "get_settings", lambda: settings)


def _state(plan=None, **extra):
    state = new_state(question=extra.pop("question", "测试"))
    if plan is not None:
        state["current_plan"] = plan
        state["semantic_plan"] = plan
    state.update({
        "tenant_id": 1,
        "permission_codes": ["menu.profit"],
        "conversation_id": "c_p1",
        "_db": object(),  # executor 调 Domain Tool，测试中 query_metric 被 mock
        **extra,
    })
    return state


@pytest.fixture
def _domain_tool(monkeypatch):
    """mock Domain Tool（query_metric）：返回固定排行数据。"""
    from app.services import workshop_metrics

    def fake_query(db, tenant_id, metric_id, params=None, permission_codes=None):
        if metric_id == "finance.customer_sales_ranking":
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
        if metric_id == "finance.sales_snapshot":
            return {
                "metric_id": metric_id,
                "data": {"year": (params or {}).get("year"),
                         "month": (params or {}).get("month"),
                         "revenue": 34250000.0, "unit": "CNY"},
                "chart": None,
            }
        return {"error": "unknown_metric", "message": f"未知指标：{metric_id}"}

    monkeypatch.setattr(workshop_metrics, "query_metric", fake_query)


# ---------------------------------------------------------------------------
# semantic_compile —— LLM 编译（mock LLM 返回 JSON）
# ---------------------------------------------------------------------------


def test_semantic_compile_uses_llm(monkeypatch) -> None:
    from app.services import schedule_agent

    plan_json = (
        '{"analysis_type": "ranking", "metric": "sales_amount", "dimension": "customer", '
        '"time_range": {"year": 2026}, "order": "desc", "limit": 3, "filters": {}}'
    )

    class _Resp:
        content = plan_json

    monkeypatch.setattr(
        schedule_agent, "_make_model",
        lambda: type("M", (), {"invoke": lambda *a, **k: _Resp()}),
    )
    state = _state(question="今年客户销售额前3名")
    out = semantic_compile(state)
    assert "current_plan" in out
    assert out["current_plan"]["limit"] == 3
    assert out["current_plan"]["analysis_type"] == "ranking"


def test_semantic_compile_failure_is_explicit(monkeypatch) -> None:
    from app.services import schedule_agent

    class _Resp:
        content = "不是 JSON"

    monkeypatch.setattr(
        schedule_agent, "_make_model",
        lambda: type("M", (), {"invoke": lambda *a, **k: _Resp()}),
    )
    state = _state(question="随便")
    out = semantic_compile(state)
    assert out["failure"]["reason_code"] == "SEMANTIC_COMPILE_FAILED"
    assert out["failure"]["action"] == "clarify"


# ---------------------------------------------------------------------------
# inheritance_resolve —— 两级（第一层确定性，第二层 LLM）
# ---------------------------------------------------------------------------


def test_inheritance_deterministic_period_switch() -> None:
    """「上月呢」：第一层确定性继承——从 previous_plans 结构化替换时间，不调 LLM。"""
    state = _state(question="上月呢", current_plan=None)
    state["previous_plans"] = [
        {**SNAPSHOT_PLAN, "time_range": {"year": 2026, "month": 8}},
    ]
    out = inheritance_resolve(state)
    assert out["_inheritance"] == "deterministic"
    assert out["current_plan"]["time_range"] == {"year": 2026, "month": 7}


def test_inheritance_deterministic_limit() -> None:
    """「只看top3」：第一层确定性继承——只换 limit。"""
    state = _state(question="只看top3", current_plan=None)
    state["previous_plans"] = [dict(RANKING_PLAN)]
    out = inheritance_resolve(state)
    assert out["_inheritance"] == "deterministic"
    assert out["current_plan"]["limit"] == 3


def test_inheritance_no_previous_returns_empty() -> None:
    """无 previous_plans → 不继承（由 plan_validate 判定走向）。"""
    state = _state(question="只看top3", current_plan=dict(RANKING_PLAN))
    out = inheritance_resolve(state)
    assert out == {}


def test_inheritance_llm_when_rule_does_not_cover(monkeypatch) -> None:
    """「按金额排序」：规则覆盖不了 → 第二层 LLM（semantic_compiler）。"""
    from app.services import semantic_compiler
    from app.services.semantic_compiler import InheritanceProposal, RefineSpec

    monkeypatch.setattr(
        semantic_compiler, "resolve_inheritance",
        lambda q, **kwargs: semantic_compiler.InheritanceVerdict(
            status="inherited", reason_code="INHERITED_VIA_COMPILER",
            limit=5, min_amount=None, period=None, year=2026, month=None,
        ),
    )
    state = _state(question="按金额排序", current_plan=None)
    state["previous_plans"] = [dict(RANKING_PLAN)]
    out = inheritance_resolve(state)
    assert out["_inheritance"] == "llm"
    assert out["current_plan"]["limit"] == 5


# ---------------------------------------------------------------------------
# plan_validate
# ---------------------------------------------------------------------------


def test_plan_validate_registered_complete() -> None:
    state = _state(plan=RANKING_PLAN)
    out = plan_validate(state)
    assert "_validated_plan" in out


def test_plan_validate_missing_slot() -> None:
    state = _state(plan={**RANKING_PLAN, "limit": None})
    out = plan_validate(state)
    assert out["failure"]["reason_code"] == "MISSING_SLOT"
    assert out["failure"]["action"] == "clarify"


# ---------------------------------------------------------------------------
# deterministic_executor + evidence_validate + controlled_render
# ---------------------------------------------------------------------------


def test_executor_ranking_via_domain_tool(_domain_tool) -> None:
    state = _state(plan=RANKING_PLAN)
    out = deterministic_executor(state)
    assert out["_execution"]["metric_id"] == "finance.customer_sales_ranking"
    assert out["_execution"]["raw"]["data"]["items"][0]["customer_name"] == "客户 A"


def test_executor_permission_denied(monkeypatch) -> None:
    from app.services import workshop_metrics

    monkeypatch.setattr(
        workshop_metrics, "query_metric",
        lambda db, tid, mid, params=None, permission_codes=None: {"error": "forbidden", "message": "无权限"},
    )
    state = _state(plan=RANKING_PLAN)
    out = deterministic_executor(state)
    assert out["failure"]["reason_code"] == "PERMISSION_DENIED"
    assert out["failure"]["action"] == "reject"


def test_evidence_validate_ranking(_domain_tool) -> None:
    state = _state(plan=RANKING_PLAN)
    state.update(deterministic_executor(state))
    out = evidence_validate(state)
    assert "_validated" in out
    assert len(out["_validated"]["verified_assertions"]) >= 2


def test_controlled_render_folds_output(_domain_tool) -> None:
    state = _state(plan=RANKING_PLAN)
    for node in (deterministic_executor, evidence_validate):
        state.update(node(state))
    out = controlled_render(state)
    assert out["presentation"]["type"] == "table"
    assert out["presentation"]["rows"][0] == ["1", "客户 A", "1,235 万元"]
    assert out["trust_metrics"]["claim_precision"] == 1.0


# ---------------------------------------------------------------------------
# 端到端
# ---------------------------------------------------------------------------


def test_fast_path_branch_end_to_end(monkeypatch, _domain_tool) -> None:
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
    state = _state(question="客户销售额排行")
    out = fast_path_branch(state)
    assert "failure" not in out, out.get("failure")
    assert state["presentation"]["rows"][0] == ["1", "客户 A", "1,235 万元"]
    assert state["trust_metrics"]["claim_precision"] == 1.0
    # LLM 调用次数：1（semantic_compile），受控
    assert state["execution_result"]["verified_count"] >= 2


def test_conversation_runtime_with_fast_path(monkeypatch, _domain_tool) -> None:
    from app.services import schedule_agent

    plan_json = (
        '{"analysis_type": "metric_snapshot", "metric": "sales_snapshot", '
        '"time_range": {"year": 2026, "month": 8}}'
    )

    class _Resp:
        content = plan_json

    monkeypatch.setattr(
        schedule_agent, "_make_model",
        lambda: type("M", (), {"invoke": lambda *a, **k: _Resp()}),
    )
    runtime = ConversationRuntime(fast_path_enabled=True, fast_path_node=fast_path_branch)
    out = runtime.invoke(
        question="本月销售额多少",
        tenant_id=1, permission_codes=["menu.profit"], conversation_id="c_runtime",
        _db=object(),
    )
    assert out["route"]["route"] == "fast_path"
    assert out["route"]["reason_code"] == "SUCCESS"
    assert out["presentation"]["columns"] == ["指标", "数值"]
    assert out["presentation"]["rows"][0] == ["销售额", "3,425 万元"]


def test_llm_down_fails_explicit(monkeypatch) -> None:
    """LLM 不可用 → semantic_compile 显式失败（clarify），不静默猜测。"""
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent, "_make_model",
        lambda: (_ for _ in ()).throw(RuntimeError("llm down")),
    )
    state = _state(question="客户销售额排行")
    out = fast_path_branch(state)
    assert out["failure"]["reason_code"] == "SEMANTIC_COMPILE_FAILED"
    assert out["failure"]["action"] == "clarify"
