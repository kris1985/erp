"""Tool-first Direct Path 端到端集成测试（Unified DeepAgent）。

用 FakeMessagesListChatModel 驱动真实 create_deep_agent 图：
model → query_metric_direct（return_direct）→ FinalizeMiddleware.after_agent
→ state["response"]。验证单一执行范式：direct 命中短路、统一收尾、response
契约、以及混合调用被 DirectToolCallPolicy 拦截后回到 model 的路径。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Optional

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from deepagents import create_deep_agent

from app.runtime.workshop.context import WorkshopContext
from app.runtime.workshop.direct_tool import build_query_metric_direct, TOOL_NAME
from app.runtime.workshop.direct_tool_policy import DirectToolCallPolicy
from app.runtime.workshop.finalize_middleware import FinalizeMiddleware
from app.runtime.workshop.state import WorkshopAgentState
from app.runtime.workshop.tool_error_normalizer import ToolErrorNormalizer
from app.services import analysis_result_store, finance_service, schedule_agent, workshop_metrics

FAKE_ORDERS = [
    {"customer_name": "客户 A", "revenue": Decimal("12350000")},
    {"customer_name": "客户 B", "revenue": Decimal("9800000")},
]
TOTAL = Decimal("22150000")


def fake_profit_report(db, tenant_id, *, year=None, month=None, customer_id=None, keyword=None, date_from=None, date_to=None, loss_only=False):
    return {"orders": FAKE_ORDERS, "summary": {"revenue": TOTAL}, "year": year}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(finance_service, "profit_report", fake_profit_report)
    monkeypatch.setattr(
        workshop_metrics, "list_metrics",
        lambda permission_codes=None: [
            {"id": "finance.customer_sales_ranking", "name": "客户销售额排行", "description": "客户销售额排行"},
            {"id": "finance.sales_snapshot", "name": "销售额快照", "description": "销售额快照"},
        ],
    )

    def fake_settings():
        return type(
            "Settings", (),
            {"schedule_agent_data_dir": str(tmp_path), "analysis_result_ttl_seconds": 3600,
             "analysis_result_max_per_session": 200},
        )()

    monkeypatch.setattr(analysis_result_store, "get_settings", fake_settings)

    class _FakeSession:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    import app.db

    monkeypatch.setattr(app.db, "SessionLocal", _FakeSession)

    # FinalizeMiddleware 依赖的 schedule_agent 持久化/guardrail 桩
    monkeypatch.setattr(schedule_agent, "_upsert_conversation", lambda *a, **k: {"title": None})
    monkeypatch.setattr(schedule_agent, "_save_ui_messages", lambda *a, **k: None)
    monkeypatch.setattr(schedule_agent, "_record_agent_trace", lambda **k: None)
    monkeypatch.setattr(schedule_agent, "_serialize_ui_messages", lambda *a, **k: [])

    def _guardrail(q, reply, evidence):
        return reply, {"passed": True, "reason": "test", "unmatched": [], "tool_names": [], "has_usable_payload": True}

    monkeypatch.setattr(schedule_agent, "apply_evidence_guardrail", _guardrail)
    monkeypatch.setattr(schedule_agent, "build_evidence_ledger", lambda *a, **k: [])
    monkeypatch.setattr(schedule_agent, "build_response_presentation", lambda *a, **k: None)


class _ScriptedModel(BaseChatModel):
    """按预设序列返回 AIMessage 的 fake model（支持 bind_tools）。"""

    responses: List[AIMessage] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-workshop"

    def bind_tools(self, tools, **kwargs: Any):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        if not self.responses:
            raise RuntimeError("scripted model exhausted")
        response = self.responses[0]
        self.responses = self.responses[1:]
        return ChatResult(generations=[ChatGeneration(message=response)])


def _build_agent(model, *, tenant_id: int = 1):
    tool = build_query_metric_direct(tenant_id=tenant_id, conversation_id="c1", permission_codes=[])
    return create_deep_agent(
        model=model,
        tools=[tool],
        system_prompt="你是产线军师。",
        middleware=[
            DirectToolCallPolicy(),
            ToolErrorNormalizer(),
            FinalizeMiddleware(),
        ],
        state_schema=WorkshopAgentState,
        context_schema=WorkshopContext,
        name="it-workshop",
    )


def _direct_call(**args) -> dict:
    return {"name": TOOL_NAME, "args": args, "id": "call_direct", "type": "tool_call"}


def test_direct_hit_short_circuits_to_response(monkeypatch, tmp_path) -> None:
    """model 一次调用输出 direct tool call → return_direct 短路 → after_agent 统一收尾。"""
    model = _ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[_direct_call(
            metric_id="finance.sales_snapshot", time_range={"year": 2026, "month": 8},
        )]),
    ])
    agent = _build_agent(model)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "本月销售额多少"}]},
        config={"configurable": {"thread_id": "t1"}},
        context=WorkshopContext(tenant_id=1, conversation_id="c1", permission_codes=[]),
    )
    response = result["response"]
    assert response["execution_mode"] == "fast_path"
    assert response["reply"]
    assert response["presentation"]["type"] == "metric"
    assert response["presentation"]["schema_version"] == "1.0"
    assert response["result"]["value"] > 0
    assert response["evidence_guardrail"]["passed"] is True
    # return_direct：图在工具后直接结束，不回到 model（只有一次模型响应被消费）
    assert response["fast_path"]["active"] is True


def test_direct_ranking_short_circuits(monkeypatch, tmp_path) -> None:
    model = _ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[_direct_call(
            metric_id="finance.customer_sales_ranking",
            dimensions=["customer"], time_range={"year": 2026}, limit=2,
        )]),
    ])
    agent = _build_agent(model)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "今年销售额最高的两个客户是谁"}]},
        config={"configurable": {"thread_id": "t2"}},
        context=WorkshopContext(tenant_id=1, conversation_id="c1", permission_codes=[]),
    )
    response = result["response"]
    assert response["execution_mode"] == "fast_path"
    assert response["presentation"]["type"] == "ranking"
    assert len(response["presentation"]["items"]) == 2


def test_mixed_call_policy_redirects_to_model(monkeypatch, tmp_path) -> None:
    """direct + 其他工具混合：DirectToolCallPolicy 拦截，jump_to=model 重试。"""
    mixed = [
        _direct_call(metric_id="finance.sales_snapshot", time_range={"year": 2026}),
        {"name": "other_tool", "args": {}, "id": "call_other", "type": "tool_call"},
    ]
    model = _ScriptedModel(responses=[
        AIMessage(content="", tool_calls=mixed),
        AIMessage(content="本月销售额为 2215 万元。"),
    ])
    tool = build_query_metric_direct(tenant_id=1, conversation_id="c1", permission_codes=[])
    agent = create_deep_agent(
        model=model,
        tools=[tool],
        system_prompt="你是产线军师。",
        middleware=[DirectToolCallPolicy(), ToolErrorNormalizer(), FinalizeMiddleware()],
        state_schema=WorkshopAgentState,
        context_schema=WorkshopContext,
        name="it-mixed",
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "本月销售额多少"}]},
        config={"configurable": {"thread_id": "t3"}},
        context=WorkshopContext(tenant_id=1, conversation_id="c1", permission_codes=[]),
    )
    response = result["response"]
    # 违规后回到 model：模型第二次调用给出纯文本回答 → agent 路径收尾
    assert response["execution_mode"] == "agent"
    assert "2215" in response["reply"]


def test_agent_path_no_direct(monkeypatch, tmp_path) -> None:
    """模型不调 direct（普通文本回答）→ 标准 agent 收尾。"""
    model = _ScriptedModel(responses=[AIMessage(content="这是一般的经营分析回答。")])
    agent = _build_agent(model)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "请分析一下利润情况"}]},
        config={"configurable": {"thread_id": "t4"}},
        context=WorkshopContext(tenant_id=1, conversation_id="c1", permission_codes=[]),
    )
    response = result["response"]
    assert response["execution_mode"] == "agent"
    assert response["reply"] == "这是一般的经营分析回答。"
