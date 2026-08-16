"""DeepAgent 子图 P2 测试（架构定稿 §9 P2）。

验证 deep_agent_branch：
- 作为 ConversationRuntime 的 deep_agent 节点（不再做根）
- 调 create_deep_agent（mock _build_agent）后折叠输出
- 异常 → 显式 TRANSIENT_FAILURE → retry
- 开放问题（无 plan）走 deep_agent 分支
"""

from __future__ import annotations

from unittest.mock import patch

from app.runtime.orchestration import (
    ConversationRuntime,
    deep_agent_branch,
)
from app.runtime.orchestration.state import new_state


def _fake_agent_result(reply: str = "这是开放分析的结论。") -> dict:
    class _Msg:
        type = "ai"
        content = reply

    return {"messages": [_Msg()]}


def _fake_build_agent(reply: str = "这是开放分析的结论。"):
    def _build(tenant_id, **kwargs):
        class _Agent:
            def invoke(self, payload, config=None):
                return _fake_agent_result(reply)

        return _Agent()

    return _build


def test_deep_agent_branch_returns_reply(monkeypatch) -> None:
    from app.services import schedule_agent

    monkeypatch.setattr(schedule_agent, "_build_agent", _fake_build_agent())
    state = new_state(question="为什么毛利下降")
    state["tenant_id"] = 1
    state["permission_codes"] = ["menu.profit"]
    state["conversation_id"] = "c_deep"
    out = deep_agent_branch(state)
    assert out["execution_result"]["payload"]["reply"] == "这是开放分析的结论。"
    assert out["presentation"]["type"] == "deep_agent"


def test_deep_agent_branch_exception_is_explicit(monkeypatch) -> None:
    from app.services import schedule_agent

    def _boom(tenant_id, **kwargs):
        raise RuntimeError("agent crash")

    monkeypatch.setattr(schedule_agent, "_build_agent", _boom)
    state = new_state(question="开放问题")
    state["tenant_id"] = 1
    out = deep_agent_branch(state)
    assert out["failure"]["reason_code"] == "TRANSIENT_FAILURE"
    assert out["failure"]["action"] == "retry"


def test_runtime_no_plan_goes_deep_agent(monkeypatch) -> None:
    """开放问题（无 plan）→ route=deep_agent → 跑 DeepAgent 子图。"""
    from app.services import schedule_agent

    monkeypatch.setattr(schedule_agent, "_build_agent", _fake_build_agent("综合判断如下。"))
    runtime = ConversationRuntime(fast_path_enabled=True)
    out = runtime.invoke(
        question="为什么毛利下降",
        tenant_id=1, permission_codes=["menu.profit"], conversation_id="c_runtime_deep",
    )
    assert out["route"]["route"] == "deep_agent"
    assert out["execution_result"]["payload"]["reply"] == "综合判断如下。"


def test_runtime_deep_agent_failure_fails_closed(monkeypatch) -> None:
    from app.services import schedule_agent

    def _boom(tenant_id, **kwargs):
        raise RuntimeError("deep agent down")

    monkeypatch.setattr(schedule_agent, "_build_agent", _boom)
    runtime = ConversationRuntime(fast_path_enabled=True)
    out = runtime.invoke(
        question="为什么毛利下降",
        tenant_id=1, permission_codes=["menu.profit"], conversation_id="c_fail",
    )
    assert out["route"]["route"] == "deep_agent"
    assert out["failure"]["reason_code"] == "TRANSIENT_FAILURE"
    # 不是 SUCCESS（失败未静默成成功）
    assert out["route"]["reason_code"] != "SUCCESS"
