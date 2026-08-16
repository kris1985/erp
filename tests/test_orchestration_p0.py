"""顶层编排图 P0 测试（架构定稿 §9 P0）。

验证：ConversationRuntime 图拓扑（route → 分支 → response/reject）、
ConversationRouter 分层判定、fallback 显式状态机（无宽泛 except）、
分支占位与注入。
"""

from __future__ import annotations

from app.runtime.orchestration import (
    ConversationRouter,
    ConversationRuntime,
    fallback_action,
    resolve_reason_code,
)
from app.runtime.orchestration.state import new_state

RANKING_PLAN = {
    "analysis_type": "ranking",
    "metric": "sales_amount",
    "dimension": "customer",
    "time_range": {"year": 2026},
    "order": "desc",
    "limit": 3,
    "filters": {},
}

SNAPSHOT_PLAN = {
    "analysis_type": "metric_snapshot",
    "metric": "sales_snapshot",
    "time_range": {"year": 2026, "month": 8},
}

INCOMPLETE_RANKING = {**RANKING_PLAN, "limit": None}


# ---------------------------------------------------------------------------
# ConversationRouter：分层判定
# ---------------------------------------------------------------------------


def test_router_routes_registered_complete_plan_to_fast_path() -> None:
    state = new_state(question="客户销售额排行")
    state["semantic_plan"] = RANKING_PLAN
    decision = ConversationRouter().route(state, fast_path_enabled=True)
    assert decision["route"] == "fast_path"
    assert decision["capability"] == "ranking.v1"
    assert decision["confidence"] == 1.0
    assert decision["reason_code"] == "REGISTERED_PLAN_COMPLETE"
    assert decision["fallback_action"] == "respond"


def test_router_routes_snapshot_plan_to_fast_path() -> None:
    state = new_state(question="本月销售额多少")
    state["semantic_plan"] = SNAPSHOT_PLAN
    decision = ConversationRouter().route(state, fast_path_enabled=True)
    assert decision["route"] == "fast_path"
    assert decision["capability"] == "metric_snapshot.v1"


def test_router_no_plan_goes_deep_agent() -> None:
    state = new_state(question="为什么毛利下降")
    decision = ConversationRouter().route(state, fast_path_enabled=True)
    assert decision["route"] == "deep_agent"
    assert decision["reason_code"] == "NO_SEMANTIC_PLAN"
    assert decision["fallback_action"] == "to_deep_agent"


def test_router_unregistered_capability_goes_deep_agent() -> None:
    state = new_state(question="开放问题")
    state["semantic_plan"] = {**RANKING_PLAN, "analysis_type": "attribution_analysis"}
    decision = ConversationRouter().route(state, fast_path_enabled=True)
    assert decision["route"] == "deep_agent"
    assert decision["reason_code"] == "NOT_IN_FAST_PATH_CAPABILITY_SET"


def test_router_missing_slot_goes_clarification() -> None:
    state = new_state(question="客户销售额排行")
    state["semantic_plan"] = INCOMPLETE_RANKING
    decision = ConversationRouter().route(state, fast_path_enabled=True)
    assert decision["route"] == "clarification"
    assert decision["reason_code"] == "MISSING_SLOT"
    assert decision["fallback_action"] == "clarify"


def test_router_observational_when_disabled() -> None:
    state = new_state(question="客户销售额排行")
    state["semantic_plan"] = RANKING_PLAN
    decision = ConversationRouter().route(state, fast_path_enabled=False)
    assert decision["route"] == "deep_agent"
    assert decision["reason_code"] == "FAST_PATH_DISABLED_OBSERVATIONAL"


# ---------------------------------------------------------------------------
# fallback 显式状态机
# ---------------------------------------------------------------------------


def test_fallback_mapping() -> None:
    assert fallback_action("NOT_APPLICABLE") == "to_deep_agent"
    assert fallback_action("LOW_CONFIDENCE") == "to_deep_agent"
    assert fallback_action("MISSING_SLOT") == "clarify"
    assert fallback_action("PERMISSION_DENIED") == "reject"
    assert fallback_action("EVIDENCE_FAILED") == "fail_closed"
    assert fallback_action("CONTRACT_VIOLATION") == "fail_closed"
    assert fallback_action("TRANSIENT_FAILURE") == "retry"
    assert fallback_action("SUCCESS") == "respond"


def test_unknown_reason_code_fails_closed() -> None:
    assert fallback_action("SOME_UNKNOWN_ERROR") == "fail_closed"


def test_resolve_reason_code_normalization() -> None:
    assert resolve_reason_code("not_applicable") == "NOT_APPLICABLE"
    assert resolve_reason_code("requires_clarification") == "MISSING_SLOT"
    assert resolve_reason_code("unsupported") == "UNSUPPORTED_ANALYSIS_TYPE"
    assert resolve_reason_code("rejected") == "PERMISSION_DENIED"
    assert resolve_reason_code("executed") == "SUCCESS"
    assert resolve_reason_code("boom") == "EVIDENCE_FAILED"


# ---------------------------------------------------------------------------
# ConversationRuntime 图拓扑
# ---------------------------------------------------------------------------


def test_graph_routes_fast_path_and_responds(monkeypatch) -> None:
    state = new_state(question="客户销售额排行")
    state["semantic_plan"] = RANKING_PLAN

    def fake_fast_path(s):
        return {"execution_result": {
            "result_ids": ["r_1"], "verified_count": 3,
            "payload": {"reply": "客户 A 居首，销售额 1,235 万元。"},
        }}

    # P3：guardrail 通过才置 SUCCESS（统一 Response Layer）
    from app.services import schedule_agent

    monkeypatch.setattr(
        schedule_agent, "apply_evidence_guardrail",
        lambda q, reply, evidence: (reply, {"passed": True, "reason": "ok"}),
    )
    runtime = ConversationRuntime(
        fast_path_enabled=True, fast_path_node=fake_fast_path
    )
    out = runtime.invoke(question="客户销售额排行", semantic_plan=RANKING_PLAN)
    assert out["route"]["route"] == "fast_path"
    assert out["route"]["reason_code"] == "SUCCESS"
    assert out["execution_result"]["verified_count"] == 3
    assert "failure" not in out or out.get("failure") is None


def test_graph_missing_slot_goes_clarification() -> None:
    runtime = ConversationRuntime(fast_path_enabled=True)
    out = runtime.invoke(question="客户销售额排行", semantic_plan=INCOMPLETE_RANKING)
    assert out["route"]["route"] == "clarification"
    assert out["failure"]["action"] == "clarify"
    assert out["failure"]["reason_code"] == "MISSING_SLOT"


def test_graph_no_plan_goes_deep_agent() -> None:
    """无 plan → route=deep_agent（P2 起为真实 DeepAgent 子图）。
    此处不 mock _build_agent，验证路由本身：deep_agent 分支跑真实 agent
    会因缺 tenant 而显式失败（EVIDENCE_FAILED），而非占位。"""
    runtime = ConversationRuntime(fast_path_enabled=True)
    out = runtime.invoke(question="为什么毛利下降")
    assert out["route"]["route"] == "deep_agent"
    # 无 tenant_id → deep_agent_branch 显式失败（不是占位 reason_code）
    assert out["failure"]["reason_code"] == "EVIDENCE_FAILED"


def test_graph_fast_path_failure_fails_closed() -> None:
    """FastPath 分支失败 → fail_closed，不是宽泛 except→agent。"""

    def broken_fast_path(s):
        raise RuntimeError("query boom")

    # P0：分支抛异常由调用方显式捕获（P1 起分支内部转为 Failure 状态）
    # 这里验证：即使分支抛异常，外层不吞（显式失败语义留给分支实现）。
    runtime = ConversationRuntime(fast_path_enabled=True, fast_path_node=broken_fast_path)
    try:
        runtime.invoke(question="客户销售额排行", semantic_plan=RANKING_PLAN)
        raised = False
    except RuntimeError:
        raised = True
    assert raised, "分支异常应显式冒出，不得被图吞成深潜失败"


def test_graph_reject_node_terminates() -> None:
    """PERMISSION_DENIED → reject 节点终止，不进入 response。"""

    def rejecting_fast_path(s):
        return {"failure": {"reason_code": "PERMISSION_DENIED", "action": "reject", "stage": "authorize"}}

    runtime = ConversationRuntime(fast_path_enabled=True, fast_path_node=rejecting_fast_path)
    out = runtime.invoke(question="客户销售额排行", semantic_plan=RANKING_PLAN)
    assert out["failure"]["action"] == "reject"
    # reject 不置 SUCCESS：route 保持原始 reason_code
    assert out["route"]["reason_code"] != "SUCCESS"


def test_branch_node_injection() -> None:
    """分支节点可注入（P1/P2 替换占位的机制）。"""
    called = {"fast": False, "deep": False}

    def fast(s):
        called["fast"] = True
        return {"execution_result": {"result_ids": ["r"]}}

    def deep(s):
        called["deep"] = True
        return {}

    runtime = ConversationRuntime(
        fast_path_enabled=True,
        fast_path_node=fast,
        deep_agent_node=deep,
        clarification_node=lambda s: {},
    )
    runtime.invoke(question="客户销售额排行", semantic_plan=RANKING_PLAN)
    assert called["fast"] is True
    assert called["deep"] is False
