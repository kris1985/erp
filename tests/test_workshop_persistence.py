"""agent 路径展示产物持久化回归（修复：刷新后 evidence/presentation 丢失）。

覆盖：
1. _carry_over_display_fields：重序列化时按内容携带旧缓存的展示字段（多轮不丢卡片）
2. _enrich_last_assistant_message：跑完后把本轮 presentation/detail/evidence 写回最后一条助手消息
3. FinalizeMiddleware._finalize_agent：state.injected_evidence 驱动 evidence/presentation
   （消除「SSE 重建 vs middleware 空证据」两套真相源）
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.runtime.workshop.finalize_middleware import FinalizeMiddleware
from app.services import schedule_agent as sa


def _ranking_payload() -> dict:
    return {
        "metric_id": "finance.customer_sales_ranking",
        "data": {"year": 2026, "order": "desc", "limit": 10, "items": [
            {"customer_name": "厦门海丝进出口", "sales_amount": 3920.0},
            {"customer_name": "合单·2来源", "sales_amount": 3750.0},
            {"customer_name": "走查直发客户", "sales_amount": 900.0},
            {"customer_name": "欧恋", "sales_amount": 828.0},
        ], "total": 4},
        "_result": {"result_id": "r_test", "metric_id": "finance.customer_sales_ranking"},
        "_evidence": {"metric_id": "finance.customer_sales_ranking",
                      "filters": {"year": 2026, "order": "desc", "limit": 10},
                      "queried_at": "2026-08-17T04:29:39", "automatic": True},
    }


@pytest.fixture
def fake_conv_db(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations ("
        "id TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL, title TEXT NOT NULL,"
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, ui_messages TEXT)"
    )
    monkeypatch.setattr(sa, "_catalog_conn", lambda: conn)
    return conn


def _seed(db, conversation_id: str = "c1", messages: list[dict] | None = None) -> None:
    db.execute(
        "INSERT INTO conversations (id, tenant_id, title, created_at, updated_at, ui_messages)"
        " VALUES (?,?,?,?,?,?)",
        (conversation_id, 1, "t", "2026-01-01T00:00:00", "2026-01-01T00:00:00",
         json.dumps(messages or [], ensure_ascii=False)),
    )
    db.commit()


def _stored(db, conversation_id: str = "c1") -> list[dict]:
    row = db.execute(
        "SELECT ui_messages FROM conversations WHERE id=? AND tenant_id=1", (conversation_id,)
    ).fetchone()
    return json.loads(row["ui_messages"])


# ---------------------------------------------------------------- 1. carry-over

def test_carry_over_display_fields_preserves_enriched_fields(fake_conv_db):
    old_cache = [
        {"role": "user", "content": "客户销售额排行"},
        {"role": "assistant", "content": "2026年客户销售额排行回复",
         "presentation": {"type": "ranking", "items": []},
         "detail": {"available": True, "kind": "summary", "content": "x"},
         "evidence": [{"id": "E1", "source": "客户销售额排行"}],
         "todos": [{"type": "ai_followup", "title": "y"}],
         "charts": [{"metric_id": "finance.customer_sales_ranking", "type": "bar"}]},
    ]
    _seed(fake_conv_db, messages=old_cache)

    new_messages = [
        {"role": "user", "content": "客户销售额排行"},
        {"role": "assistant", "content": "2026年客户销售额排行回复"},
        {"role": "assistant", "content": "另一条回复"},
    ]
    sa._carry_over_display_fields(1, "c1", new_messages)

    # 同内容 → 展示字段被携带
    assert new_messages[1]["presentation"] == {"type": "ranking", "items": []}
    assert new_messages[1]["detail"]["available"] is True
    assert new_messages[1]["evidence"][0]["id"] == "E1"
    assert new_messages[1]["todos"][0]["type"] == "ai_followup"
    assert new_messages[1]["charts"][0]["metric_id"] == "finance.customer_sales_ranking"
    # 不同内容 → 不携带
    assert "presentation" not in new_messages[2]


def test_carry_over_with_empty_old_cache_is_noop(fake_conv_db):
    _seed(fake_conv_db, messages=[])
    new_messages = [{"role": "assistant", "content": "回复"}]
    sa._carry_over_display_fields(1, "c1", new_messages)
    assert "presentation" not in new_messages[0]


# ---------------------------------------------------------------- 2. enrich

def test_enrich_last_assistant_message_patches_last_reply(fake_conv_db):
    _seed(fake_conv_db, messages=[
        {"role": "user", "content": "客户销售额排行"},
        {"role": "assistant", "content": "2026年客户销售额排行回复"},
    ])

    sa._enrich_last_assistant_message(
        1, "c1",
        presentation={"type": "ranking", "items": []},
        detail={"available": True, "kind": "summary", "content": "x"},
        evidence=[{"id": "E1", "source": "客户销售额排行"}],
        todos=[],
        charts=[{"metric_id": "finance.customer_sales_ranking", "type": "bar"}],
    )

    stored = _stored(fake_conv_db)
    assert stored[1]["presentation"] == {"type": "ranking", "items": []}
    assert stored[1]["detail"]["available"] is True
    assert stored[1]["evidence"][0]["id"] == "E1"
    assert stored[1]["charts"][0]["metric_id"] == "finance.customer_sales_ranking"
    assert "presentation" not in stored[0]  # 用户消息不受影响


def test_enrich_then_refresh_keeps_fields_via_carry_over(fake_conv_db):
    """完整闭环：enrich 落库 → 下一轮重序列化（carry-over）→ 字段仍在。"""
    _seed(fake_conv_db, messages=[{"role": "assistant", "content": "回复A"}])
    sa._enrich_last_assistant_message(
        1, "c1", presentation={"type": "ranking", "items": []}, detail=None,
        evidence=[{"id": "E1"}], todos=None,
    )
    # 模拟下一轮：缓存被重序列化为同内容的新消息
    serialized = [{"role": "assistant", "content": "回复A"}]
    sa._carry_over_display_fields(1, "c1", serialized)
    assert serialized[0]["presentation"] == {"type": "ranking", "items": []}
    assert serialized[0]["evidence"] == [{"id": "E1"}]


# ---------------------------------------------------------------- 3. injected evidence

def test_finalize_agent_builds_evidence_and_presentation_from_injected(monkeypatch):
    """B1：state.injected_evidence 直接驱动 middleware 的 evidence/presentation，
    不再依赖 SSE 侧重建（修复两套真相源）。"""
    import app.runtime.workshop.finalize_middleware as fm

    monkeypatch.setattr(fm, "_load_cached_ui_messages", lambda *a, **k: [])
    for name in ("_upsert_conversation", "_save_ui_messages",
                 "_record_agent_trace", "_serialize_ui_messages"):
        monkeypatch.setattr(sa, name, lambda *a, **k: None)
    monkeypatch.setattr(
        sa.workshop_metrics, "list_metrics",
        lambda permission_codes=None: [
            {"id": "finance.customer_sales_ranking", "name": "客户销售额排行", "description": "x"},
        ],
    )

    def _no_ref(*a, **k):
        raise ValueError("not_found")

    monkeypatch.setattr(sa.analysis_result_store, "read_ref", _no_ref)

    injected = [{"name": "query_metric", "content": json.dumps(_ranking_payload(), ensure_ascii=False)}]
    messages = [
        HumanMessage(content="客户销售额排行"),
        AIMessage(content="2026年客户销售额排行：厦门海丝进出口3920元居首，合单·2来源3750元次之。"),
    ]
    state = {"messages": messages, "injected_evidence": injected}

    response = FinalizeMiddleware()._finalize_agent(
        schedule_agent=sa,
        tenant_id=1,
        conversation_id="c1",
        permission_codes=["menu.profit"],
        question="客户销售额排行",
        messages=messages,
        run_id="run_x",
        title="客户销售额排行",
        state=state,
    )

    assert response["execution_mode"] == "agent"
    assert response["evidence"], "injected evidence 应产出证据卡片"
    assert response["evidence"][0]["source"] == "客户销售额排行"
    assert response["presentation"] is not None
    assert response["presentation"]["type"] == "ranking"
    assert response["presentation"]["items"][0]["label"] == "厦门海丝进出口"
