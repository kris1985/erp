"""Unified DeepAgent middleware 测试（Tool-first Direct Path）。

覆盖：DirectToolCallPolicy 独占调用拦截、ToolErrorNormalizer 错误归一化、
FinalizeMiddleware 的 direct artifact 解析（success/rejected）与 agent 收尾。
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.runtime.workshop.context import WorkshopContext
from app.runtime.workshop.direct_tool import TOOL_NAME
from app.runtime.workshop.direct_tool_policy import DirectToolCallPolicy
from app.runtime.workshop.finalize_middleware import FinalizeMiddleware
from app.runtime.workshop.tool_error_normalizer import ToolErrorNormalizer


class _Runtime:
    def __init__(self, context=None):
        self.context = context if context is not None else WorkshopContext(
            tenant_id=1, conversation_id="c1", permission_codes=[]
        )


def _state(messages, **extra):
    state = {"messages": messages}
    state.update(extra)
    return state


# ---------------------------------------------------------------- DirectToolCallPolicy

class TestDirectToolCallPolicy:
    def test_no_tool_calls_pass(self):
        policy = DirectToolCallPolicy()
        state = _state([HumanMessage(content="hi"), AIMessage(content="ok")])
        assert policy.after_model(state, _Runtime()) is None

    def test_direct_alone_passes(self):
        policy = DirectToolCallPolicy()
        call = {"name": TOOL_NAME, "args": {"metric_id": "finance.sales_snapshot"}, "id": "call_1"}
        state = _state([HumanMessage(content="本月销售额多少"), AIMessage(content="", tool_calls=[call])])
        assert policy.after_model(state, _Runtime()) is None

    def test_direct_unsupported_metric_first_retry(self):
        policy = DirectToolCallPolicy()
        call = {"name": TOOL_NAME, "args": {"metric_id": "finance.gross_profit_time_series", "time_range": {"year": 2026, "month": 8}}, "id": "call_1"}
        state = _state([HumanMessage(content="今年的销售额趋势怎么样"), AIMessage(content="", tool_calls=[call])])
        result = policy.after_model(state, _Runtime())
        assert result is not None
        assert result["jump_to"] == "model"
        assert result["_direct_policy_attempts"] == 1
        msgs = [m for m in result.get("messages", []) if isinstance(m, SystemMessage)]
        assert msgs and "不在直查白名单内" in msgs[0].content
        assert "query_metric" in msgs[0].content

    def test_direct_unsupported_metric_cap_allows_executor(self):
        policy = DirectToolCallPolicy()
        call = {"name": TOOL_NAME, "args": {"metric_id": "finance.gross_profit_time_series"}, "id": "call_1"}
        state = _state(
            [HumanMessage(content="销售额趋势"), AIMessage(content="", tool_calls=[call])],
            _direct_policy_attempts=1,
        )
        # 超限后放行：由 executor fail-closed 兜底，而非再跳一次 model
        assert policy.after_model(state, _Runtime()) is None

    def test_direct_malformed_args_pass_to_executor(self):
        policy = DirectToolCallPolicy()
        call = {"name": TOOL_NAME, "args": {"unexpected": True}, "id": "call_1"}
        state = _state([HumanMessage(content="销售额"), AIMessage(content="", tool_calls=[call])])
        assert policy.after_model(state, _Runtime()) is None

    def test_mixed_calls_first_retry(self):
        policy = DirectToolCallPolicy()
        calls = [
            {"name": TOOL_NAME, "args": {"metric_id": "finance.sales_snapshot"}, "id": "call_1"},
            {"name": "create_draft_from_proposal_json", "args": {}, "id": "call_2"},
        ]
        state = _state([HumanMessage(content="本月销售额多少"), AIMessage(content="", tool_calls=calls)])
        result = policy.after_model(state, _Runtime())
        assert result is not None
        assert result["jump_to"] == "model"
        assert result["_direct_policy_attempts"] == 1
        assert any(isinstance(m, SystemMessage) for m in result.get("messages", []))

    def test_mixed_calls_second_reject(self):
        policy = DirectToolCallPolicy()
        calls = [
            {"name": TOOL_NAME, "args": {}, "id": "call_1"},
            {"name": "remember_user_fact", "args": {}, "id": "call_2"},
        ]
        state = _state(
            [HumanMessage(content="x"), AIMessage(content="", tool_calls=calls)],
            _direct_policy_attempts=1,
        )
        result = policy.after_model(state, _Runtime())
        assert result is not None
        assert result["jump_to"] == "end"


# ---------------------------------------------------------------- ToolErrorNormalizer

class TestToolErrorNormalizer:
    def test_direct_error_normalized(self):
        normalizer = ToolErrorNormalizer()

        def boom(request):
            raise ValueError("bad metric param")

        class _Req:
            def __init__(self, name):
                self.tool_call = {"name": name, "id": "t1"}

        msg = normalizer.wrap_tool_call(_Req(TOOL_NAME), boom)
        assert isinstance(msg, ToolMessage)
        assert msg.status == "error"
        artifact = json.loads(msg.content)
        assert artifact["status"] == "model_argument_error"
        assert "未能形成有效查询" in artifact["reply"]

    def test_other_tool_passthrough(self):
        normalizer = ToolErrorNormalizer()

        def handler(request):
            return ToolMessage(content="ok", name="other", tool_call_id="t2")

        class _Req:
            def __init__(self, name):
                self.tool_call = {"name": name, "id": "t2"}

        assert normalizer.wrap_tool_call(_Req("other"), handler).content == "ok"


# ---------------------------------------------------------------- FinalizeMiddleware

@pytest.fixture(autouse=True)
def _fake_schedule_agent(monkeypatch):
    """把 FinalizeMiddleware 依赖的 schedule_agent 函数替换为桩。"""
    import app.runtime.workshop.finalize_middleware as fm

    class _Fake:
        @staticmethod
        def _upsert_conversation(tenant_id, conversation_id, *, title=None):
            return {"title": title}

        @staticmethod
        def _save_ui_messages(tenant_id, conversation_id, messages):
            pass

        @staticmethod
        def _record_agent_trace(**kwargs):
            pass

        @staticmethod
        def _serialize_ui_messages(messages, permission_codes=None):
            return [{"role": "assistant", "content": "serialized"}]

        @staticmethod
        def apply_evidence_guardrail(question, reply, tool_evidence):
            return reply, {"passed": True, "reason": "fake", "unmatched": [], "tool_names": [], "has_usable_payload": True}

        @staticmethod
        def build_evidence_ledger(tool_evidence, permission_codes=None, include_internal_refs=False):
            return [{"name": item.get("name"), "source": "fake"} for item in tool_evidence]

        @staticmethod
        def build_response_presentation(question, evidence, tenant_id):
            return {"type": "summary", "title": "fake"}

    monkeypatch.setattr(fm, "_load_cached_ui_messages", lambda *a, **k: [])
    # 函数体内 from app.services import schedule_agent —— 替换模块属性
    import app.services.schedule_agent as sa

    for name in (
        "_upsert_conversation", "_save_ui_messages", "_record_agent_trace",
        "_serialize_ui_messages", "apply_evidence_guardrail",
        "build_evidence_ledger", "build_response_presentation",
    ):
        monkeypatch.setattr(sa, name, getattr(_Fake, name))


def _direct_artifact_msg(status: str, reply: str, **extra) -> ToolMessage:
    artifact = {"status": status, "reply": reply, "presentation": None, "detail": None,
                "trust_metrics": None, "evidence": [], "fast_path": None,
                "reason_code": "SUCCESS" if status == "success" else "REJECTED",
                "clarification": None, "options": [], **extra}
    return ToolMessage(content=json.dumps(artifact, ensure_ascii=False), name=TOOL_NAME, tool_call_id="t1")


class TestFinalizeDirect:
    def test_success_artifact(self):
        finalize = FinalizeMiddleware()
        msg = _direct_artifact_msg(
            "success", "本月销售额为 3425 万元",
            presentation={"type": "table", "title": "销售额", "analysis_type": "metric_snapshot"},
        )
        state = _state([HumanMessage(content="本月销售额多少"), AIMessage(content="", tool_calls=[{"name": TOOL_NAME, "args": {}, "id": "t1", "type": "tool_call"}]), msg])
        result = finalize.after_agent(state, _Runtime())
        response = result["response"]
        assert response["execution_mode"] == "fast_path"
        assert response["reply"] == "本月销售额为 3425 万元"
        assert response["presentation"]["analysis_type"] == "metric_snapshot"
        assert response["evidence_guardrail"]["passed"] is True
        assert result["validation"]["passed"] is True

    def test_rejected_artifact(self):
        finalize = FinalizeMiddleware()
        msg = _direct_artifact_msg("rejected", "当前账号无权限查询销售额。", reason_code="POLICY_DENIED")
        state = _state([HumanMessage(content="销售额"), AIMessage(content="", tool_calls=[{"name": TOOL_NAME, "args": {}, "id": "t1", "type": "tool_call"}]), msg])
        result = finalize.after_agent(state, _Runtime())
        response = result["response"]
        assert response["execution_mode"] == "fast_path_rejected"
        assert response["failure"]["reason_code"] == "POLICY_DENIED"
        assert response["failure"]["action"] == "reject"
        assert response["fast_path_rejection"]["reply"] == "当前账号无权限查询销售额。"

    def test_model_argument_error_artifact(self):
        finalize = FinalizeMiddleware()
        msg = _direct_artifact_msg("model_argument_error", "当前未能形成有效查询：limit 非法。", reason_code="INVALID_LIMIT")
        state = _state([HumanMessage(content="销售额"), AIMessage(content="", tool_calls=[{"name": TOOL_NAME, "args": {}, "id": "t1", "type": "tool_call"}]), msg])
        result = finalize.after_agent(state, _Runtime())
        response = result["response"]
        assert response["execution_mode"] == "fast_path_rejected"
        # 模型参数错误不归咎用户：文案是「未能形成有效查询」
        assert "未能形成有效查询" in response["reply"]


class TestFinalizeAgent:
    def test_ai_message_tail(self):
        finalize = FinalizeMiddleware()
        state = _state([HumanMessage(content="分析一下利润"), AIMessage(content="利润下降主要受毛利影响。")])
        result = finalize.after_agent(state, _Runtime())
        response = result["response"]
        assert response["execution_mode"] == "agent"
        assert response["reply"] == "利润下降主要受毛利影响。"
        assert response["evidence_guardrail"]["passed"] is True

    def test_no_context_passthrough(self):
        finalize = FinalizeMiddleware()
        state = _state([HumanMessage(content="hi")])
        assert finalize.after_agent(state, object()) is None
