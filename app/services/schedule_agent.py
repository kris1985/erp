"""排产 Agent（L3）：DeepAgents + DeepSeek；只能调规则引擎工具，禁止臆造数据。"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Generator, Optional

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.services import schedule_engine, schedule_service, schedule_settings, workshop_metrics

SYSTEM_PROMPT = """你是鞋厂「车间军师」（排产参谋 + 经营问数 + 诊断分析）。你只出主意、不下指令落库；只能通过工具获取事实与方案，禁止编造订单号、日期、数量、金额、产能或风险。

硬性规则：
1. 任何涉及订单/交期/负荷/插单/方案/产量/缺料/库存/应收/回款/利润/质量/人效的结论，必须先调用对应工具；工具结果是唯一真相源。
2. 不要猜测缺失字段；缺参数就追问用户。
3. 排产方案对用户讲策略名与风险（可带方案编号）；问数时工具调用用 metric_id，对用户只说 list_metrics 里的中文 name（如「今日工序产量」「生产单进度」），禁止在答复里甩英文 id（如 production.today_output、analytics.quality_alerts）。
4. 诊断优先 analytics.*。接单/生产分析必须 query_metric(analytics.order_intake)，params 带 lines；用户改交期/数量/急单/日产能时用同一 lines 加 qty/delivery_date/is_rush/strategy/default_daily_capacity 重查，禁止口头改数。答复极简：裁决一句话 → **解释为何**（引用毛利对比、码段偏离、争料、实耗偏差、缺料与预计齐套日、交期冲击被影响单号、回款余额/平均回款天数）→ 最多 3 条可执行建议。风险只用中文标签（risk_label / intake_risk_label）：余量充足、交期偏紧、预计逾期、缺料卡住、产能不足；每条建议以标签开头。禁止输出利润明细表与物料明细表（界面左侧即时诊断已展示，勿重复）；用户明确要求「出表」时才出表。empty_bom=true 时明确「未建 BOM，不能确认可开裁」。缺料时说「预计到料日/预计齐套日」，禁止写 ETA。capacity_configured=false 时须说明「未校验产能」，并提示可在假设中填日产能后重算；若 capacity_from_hypothesis=true 须说明「按假设日产能校验、未写入排产设置」。确认生产/取消须界面 HITL。
5. 其它诊断：今日行动、齐套可排、本周简报、交期风险、产能负荷、供应链、经营健康、质量热点、质量预警、人效、本月简报（工具侧对应 today_actions / kit_ready / … / quality_alerts 等）。「可排」用 generate_schedule_proposals（提醒人工确认）；产能校准 suggested_memories 用 remember_user_fact。讲「今日行动 / 今日 3 件事」时：只陈述 data.top3（最多 3 条），每条必须引用该条 evidence.facts 与 order_nos；禁止编造未出现在 evidence 中的单号、日期、数量；不要把完整 actions 清单当主答复。讲质量抽检时优先查「质量预警」（analytics.quality_alerts，款×工序突增），可辅以「质量热点」；讲损耗超标时先看今日行动是否含损耗超标项，有则只引用其 evidence，没有则如实说没有——禁止编造领料实耗。方案对比须点明各方案的延期风险与负荷含义，并提醒人工确认后落库。
6. 你不能确认落库、不能改派工/工资/交期/采购/核销；只能建议用户在系统里操作；排产路径仍是「采用方案→进草稿→人工确认」。
7. 若工具报错、无权限或无数据，如实说明（用中文说「无工艺路线」等，不要甩 sim_error=no_route），不要补造。
8. 多轮沿用已确认约束；长期偏好用 remember_user_fact。
9. 用中文。少废话。面向车间师傅/厂长：不出现英文字段名、metric_id、snake_case、JSON key。
10. 问数先 list_metrics 再 query_metric；不要编造 metric_id。建议下一步时说中文动作（如「可再查今日工序产量，或按生产单号查进度」），不要写英文指标名。
11. 工具若返回 chart，前端会画图；你只解释结论，不要编造图表或 ```chart 代码块。
"""


_lock = threading.Lock()


def agent_available() -> dict[str, Any]:
    s = get_settings()
    enabled = bool(s.schedule_agent_enabled) and bool(s.deepseek_api_key)
    return {
        "enabled": enabled,
        "model": s.deepseek_model if enabled else None,
        "reason": None if enabled else "未配置 DEEPSEEK_API_KEY 或已关闭 SCHEDULE_AGENT_ENABLED",
    }


def _data_dir() -> Path:
    s = get_settings()
    p = Path(s.schedule_agent_data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


@lru_cache
def _checkpointer():
    from langgraph.checkpoint.sqlite import SqliteSaver

    path = _data_dir() / "checkpoints.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


@lru_cache
def _store():
    from langgraph.store.sqlite import SqliteStore

    path = _data_dir() / "memory.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    store = SqliteStore(conn)
    store.setup()
    return store


def _memory_ns(tenant_id: int) -> tuple[str, str]:
    return ("schedule_agent", f"tenant_{tenant_id}")


def list_memories(tenant_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    store = _store()
    items = store.search(_memory_ns(tenant_id), limit=limit)
    out: list[dict[str, Any]] = []
    for it in items:
        val = it.value if hasattr(it, "value") else it
        if isinstance(val, dict):
            out.append(
                {
                    "key": getattr(it, "key", None),
                    "text": val.get("text"),
                    "updated_at": val.get("updated_at"),
                }
            )
    return out


def remember_fact(tenant_id: int, key: str, text: str) -> dict[str, Any]:
    store = _store()
    key = (key or "").strip()[:80] or f"fact_{uuid.uuid4().hex[:8]}"
    text = (text or "").strip()[:500]
    if not text:
        raise ValueError("empty_memory")
    payload = {"text": text, "updated_at": date.today().isoformat()}
    store.put(_memory_ns(tenant_id), key, payload)
    return {"key": key, **payload}


def _build_tools(tenant_id: int, *, permission_codes: list[str] | None = None):
    """每个工具独立 Session，避免 LangGraph 并行调工具时共用 FastAPI 请求 Session 打乱 pymysql 包序。"""
    perms = list(permission_codes or [])

    @contextmanager
    def _session() -> Generator[Session, None, None]:
        db = SessionLocal()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @tool
    def get_schedule_pool(
        hide_scheduled: bool = True,
        hide_first_kit_blocked: bool = False,
    ) -> str:
        """查看待排池订单（含齐套、优先级）。"""
        with _session() as db:
            items = schedule_engine.collect_candidate_orders(
                db,
                tenant_id,
                hide_scheduled=hide_scheduled,
                hide_first_kit_blocked=hide_first_kit_blocked,
            )
            return json.dumps({"items": items, "total": len(items)}, ensure_ascii=False)

    @tool
    def get_schedule_settings() -> str:
        """读取租户排产规则：默认工期、粗产能、风险阈值。"""
        with _session() as db:
            cfg = schedule_settings.get_schedule_by_tenant_id(db, tenant_id)
            return json.dumps(cfg, ensure_ascii=False)

    @tool
    def get_daily_load(days: int = 14) -> str:
        """查看从今天起 N 天的工序日负荷与瓶颈。"""
        days = max(1, min(int(days or 14), 60))
        today = date.today()
        with _session() as db:
            data = schedule_engine.daily_load(
                db, tenant_id, date_from=today, date_to=today + timedelta(days=days)
            )
            return json.dumps(data, ensure_ascii=False)

    @tool
    def generate_schedule_proposals(order_ids: Optional[list[int]] = None) -> str:
        """用规则引擎生成 2～3 套排产方案（含风险）。可指定 order_ids，否则用待排池。"""
        with _session() as db:
            props = schedule_engine.generate_proposals(
                db, tenant_id, order_ids=order_ids or None, hide_scheduled=True
            )
            return json.dumps({"proposals": props}, ensure_ascii=False)

    @tool
    def simulate_insert_order(order_id: int) -> str:
        """插单仿真：返回保交期/保现场/折中三套方案及影响清单。"""
        with _session() as db:
            try:
                props = schedule_engine.simulate_insert(db, tenant_id, int(order_id))
            except ValueError as e:
                return json.dumps({"error": str(e)}, ensure_ascii=False)
            return json.dumps({"proposals": props}, ensure_ascii=False)

    @tool
    def create_draft_from_proposal_json(proposal_json: str, note: str = "") -> str:
        """将某套方案写入排产草稿（未确认，不会改现场派工）。传入完整 proposal 对象 JSON。"""
        try:
            proposal = json.loads(proposal_json)
        except json.JSONDecodeError:
            return json.dumps({"error": "invalid_json"}, ensure_ascii=False)
        with _session() as db:
            try:
                draft = schedule_service.create_draft_from_proposal(
                    db, tenant_id, proposal, note=note or None, auto_assign=True
                )
            except schedule_service.ScheduleError as e:
                return json.dumps({"error": e.code, "message": e.message}, ensure_ascii=False)
            return json.dumps(
                {
                    "draft_id": draft.get("id"),
                    "status": draft.get("status"),
                    "note": draft.get("note"),
                },
                ensure_ascii=False,
            )

    @tool
    def list_metrics() -> str:
        """列出当前用户有权查询的只读指标。每项含 id（仅供 query_metric）与 name（对用户说话时用中文 name，禁止把 id 念给用户）。"""
        items = workshop_metrics.list_metrics(permission_codes=perms)
        return json.dumps({"items": items, "total": len(items)}, ensure_ascii=False)

    @tool
    def query_metric(metric_id: str, params_json: str = "{}") -> str:
        """按白名单 metric_id 查询指标。params_json 为 JSON 对象字符串，如 {\"order_no\":\"MO1\"} 或 {\"year\":2026,\"month\":8}。"""
        try:
            params = json.loads(params_json or "{}")
            if not isinstance(params, dict):
                return json.dumps({"error": "invalid_params", "message": "params_json 须为对象"}, ensure_ascii=False)
        except json.JSONDecodeError:
            return json.dumps({"error": "invalid_params", "message": "params_json 不是合法 JSON"}, ensure_ascii=False)
        with _session() as db:
            result = workshop_metrics.query_metric(
                db,
                tenant_id,
                metric_id,
                params=params,
                permission_codes=perms,
            )
            return json.dumps(result, ensure_ascii=False, default=str)

    @tool
    def remember_user_fact(key: str, text: str) -> str:
        """保存长期记忆（厂规偏好、产能约定等）。"""
        try:
            row = remember_fact(tenant_id, key, text)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        return json.dumps(row, ensure_ascii=False)

    @tool
    def list_user_facts() -> str:
        """列出本租户已保存的长期记忆。"""
        return json.dumps({"items": list_memories(tenant_id)}, ensure_ascii=False)

    return [
        get_schedule_pool,
        get_schedule_settings,
        get_daily_load,
        generate_schedule_proposals,
        simulate_insert_order,
        create_draft_from_proposal_json,
        list_metrics,
        query_metric,
        remember_user_fact,
        list_user_facts,
    ]


def _make_model() -> ChatOpenAI:
    s = get_settings()
    if not s.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY missing")
    return ChatOpenAI(
        model=s.deepseek_model or "deepseek-chat",
        api_key=s.deepseek_api_key,
        base_url=s.deepseek_base_url or "https://api.deepseek.com",
        temperature=0,
        max_tokens=4096,
    )


def _build_agent(tenant_id: int, *, permission_codes: list[str] | None = None):
    from deepagents import FilesystemPermission, create_deep_agent

    memories = list_memories(tenant_id, limit=30)
    mem_block = ""
    if memories:
        lines = [f"- [{m.get('key')}] {m.get('text')}" for m in memories if m.get("text")]
        mem_block = "\n\n已知长期记忆：\n" + "\n".join(lines)

    metrics = workshop_metrics.list_metrics(permission_codes=permission_codes)
    if metrics:
        metric_lines = [f"- {m['id']}：{m['name']}（{m['description']}）" for m in metrics]
        mem_block += "\n\n当前可用问数指标：\n" + "\n".join(metric_lines)

    return create_deep_agent(
        model=_make_model(),
        tools=_build_tools(tenant_id, permission_codes=permission_codes),
        system_prompt=SYSTEM_PROMPT + mem_block,
        checkpointer=_checkpointer(),
        store=_store(),
        # 禁用文件系统读写，避免幻觉式翻盘外文件；execute 在非沙箱 backend 下也会失败
        permissions=[
            FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
        ],
        name=f"workshop-agent-t{tenant_id}",
    )


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


@lru_cache
def _catalog_conn() -> sqlite3.Connection:
    path = _data_dir() / "conversations.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_conv_tenant_updated "
        "ON conversations(tenant_id, updated_at DESC)"
    )
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    if "ui_messages" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN ui_messages TEXT")
    conn.commit()
    return conn


def _thread_id(tenant_id: int, conversation_id: str) -> str:
    return f"t{tenant_id}:{conversation_id}"


def _auto_title(message: str) -> str:
    text = " ".join((message or "").strip().split())
    if not text:
        return "新对话"
    return text if len(text) <= 28 else text[:28] + "…"


def _upsert_conversation(tenant_id: int, conversation_id: str, *, title: str | None = None) -> dict[str, Any]:
    conn = _catalog_conn()
    now = _now_iso()
    row = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id=? AND tenant_id=?",
        (conversation_id, tenant_id),
    ).fetchone()
    if row:
        new_title = title if title is not None else row["title"]
        conn.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND tenant_id=?",
            (new_title, now, conversation_id, tenant_id),
        )
        conn.commit()
        return {
            "id": conversation_id,
            "title": new_title,
            "created_at": row["created_at"],
            "updated_at": now,
        }
    use_title = title or "新对话"
    conn.execute(
        "INSERT INTO conversations(id, tenant_id, title, created_at, updated_at) VALUES(?,?,?,?,?)",
        (conversation_id, tenant_id, use_title, now, now),
    )
    conn.commit()
    return {
        "id": conversation_id,
        "title": use_title,
        "created_at": now,
        "updated_at": now,
    }


def list_conversations(tenant_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    conn = _catalog_conn()
    limit = max(1, min(int(limit or 100), 200))
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations "
        "WHERE tenant_id=? ORDER BY updated_at DESC LIMIT ?",
        (tenant_id, limit),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def rename_conversation(tenant_id: int, conversation_id: str, title: str) -> dict[str, Any]:
    title = " ".join((title or "").strip().split())
    if not title:
        raise ValueError("empty_title")
    title = title[:60]
    conn = _catalog_conn()
    row = conn.execute(
        "SELECT id FROM conversations WHERE id=? AND tenant_id=?",
        (conversation_id, tenant_id),
    ).fetchone()
    if not row:
        raise ValueError("not_found")
    return _upsert_conversation(tenant_id, conversation_id, title=title)


def delete_conversation(tenant_id: int, conversation_id: str) -> dict[str, Any]:
    conn = _catalog_conn()
    cur = conn.execute(
        "DELETE FROM conversations WHERE id=? AND tenant_id=?",
        (conversation_id, tenant_id),
    )
    conn.commit()
    if cur.rowcount <= 0:
        raise ValueError("not_found")
    try:
        _checkpointer().delete_thread(_thread_id(tenant_id, conversation_id))
    except Exception:
        # 目录已删即可；checkpoint 缺失不阻断
        pass
    return {"id": conversation_id, "deleted": True}


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _serialize_ui_messages(raw_messages: list[Any]) -> list[dict[str, Any]]:
    """仅输出用户/助手可见消息；工具调用收拢到下一条助手消息的 tools/charts。"""
    out: list[dict[str, Any]] = []
    pending_tools: list[dict[str, Any]] = []
    pending_charts: list[dict[str, Any]] = []
    for m in raw_messages:
        mtype = getattr(m, "type", None) or m.__class__.__name__
        name = getattr(m, "name", None)
        if mtype in ("tool", "ToolMessage"):
            content = _content_to_text(getattr(m, "content", ""))
            pending_tools.append(
                {
                    "name": name,
                    "content": content[:600],
                }
            )
            for c in workshop_metrics.extract_charts(content):
                pending_charts.append(c)
            continue
        if mtype in ("human", "HumanMessage", "user"):
            text = _content_to_text(getattr(m, "content", "")).strip()
            if text:
                out.append({"role": "user", "content": text, "tools": [], "charts": []})
            pending_tools = []
            pending_charts = []
            continue
        if mtype in ("ai", "AIMessage", "assistant"):
            text = _content_to_text(getattr(m, "content", "")).strip()
            # 跳过纯 tool_call 中间步（无文本）
            tool_calls = getattr(m, "tool_calls", None) or []
            if not text and tool_calls:
                continue
            if text or pending_tools or pending_charts:
                out.append(
                    {
                        "role": "assistant",
                        "content": text or "（已调用工具）",
                        "tools": pending_tools[-8:],
                        "charts": pending_charts[-6:],
                    }
                )
            pending_tools = []
            pending_charts = []
    return out


def _load_raw_thread_messages(
    tenant_id: int,
    conversation_id: str,
    *,
    permission_codes: list[str] | None = None,
) -> list[Any]:
    """从 LangGraph 状态还原完整 messages（含 deepagents 增量快照）。

    注意：不可只用 checkpointer.get_tuple().channel_values['messages']，
    增量快照下该字段常为空。
    """
    config = {"configurable": {"thread_id": _thread_id(tenant_id, conversation_id)}}
    try:
        agent = _build_agent(tenant_id, permission_codes=permission_codes)
        st = agent.get_state(config)
        vals = getattr(st, "values", None) or {}
        raw = list(vals.get("messages") or [])
        if raw:
            return raw
    except Exception:
        pass
    # 兜底：旧版完整快照仍可能写在 channel_values
    try:
        tup = _checkpointer().get_tuple(config)
        if tup and tup.checkpoint:
            channel_values = tup.checkpoint.get("channel_values") or {}
            return list(channel_values.get("messages") or [])
    except Exception:
        pass
    return []


def _save_ui_messages(tenant_id: int, conversation_id: str, messages: list[dict[str, Any]]) -> None:
    conn = _catalog_conn()
    conn.execute(
        "UPDATE conversations SET ui_messages=?, updated_at=? WHERE id=? AND tenant_id=?",
        (json.dumps(messages, ensure_ascii=False), _now_iso(), conversation_id, tenant_id),
    )
    conn.commit()


def _read_cached_ui_messages(row: Any) -> list[dict[str, Any]] | None:
    raw = None
    try:
        raw = row["ui_messages"]
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        return None
    return None


def get_conversation_messages(tenant_id: int, conversation_id: str) -> dict[str, Any]:
    conn = _catalog_conn()
    meta = conn.execute(
        "SELECT id, title, created_at, updated_at, ui_messages FROM conversations WHERE id=? AND tenant_id=?",
        (conversation_id, tenant_id),
    ).fetchone()
    if not meta:
        raise ValueError("not_found")

    cached = _read_cached_ui_messages(meta)
    if cached is not None:
        ui_messages = cached
    else:
        raw = _load_raw_thread_messages(tenant_id, conversation_id)
        ui_messages = _serialize_ui_messages(raw)
        if ui_messages:
            try:
                _save_ui_messages(tenant_id, conversation_id, ui_messages)
            except Exception:
                pass

    return {
        "id": meta["id"],
        "title": meta["title"],
        "created_at": meta["created_at"],
        "updated_at": meta["updated_at"],
        "messages": ui_messages,
        "model": get_settings().deepseek_model,
    }


def _refresh_ui_message_cache(
    tenant_id: int,
    conversation_id: str,
    *,
    permission_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    raw = _load_raw_thread_messages(
        tenant_id, conversation_id, permission_codes=permission_codes
    )
    ui_messages = _serialize_ui_messages(raw)
    if ui_messages:
        try:
            _save_ui_messages(tenant_id, conversation_id, ui_messages)
        except Exception:
            pass
    return ui_messages


def chat(
    db: Session,
    tenant_id: int,
    message: str,
    *,
    conversation_id: str | None = None,
    permission_codes: list[str] | None = None,
) -> dict[str, Any]:
    """多轮对话。conversation_id 为空则新建。

    注意：`db` 参数保留以兼容 API 签名；工具查询使用独立 Session，不复用请求 Session。
    """
    _ = db  # 工具侧自建 Session，避免与 LangGraph 并行执行冲突
    status = agent_available()
    if not status["enabled"]:
        raise RuntimeError(status["reason"] or "agent_disabled")

    message = (message or "").strip()
    if not message:
        raise ValueError("empty_message")

    is_new = not (conversation_id or "").strip()
    conv_id = (conversation_id or "").strip() or uuid.uuid4().hex
    thread_id = _thread_id(tenant_id, conv_id)

    with _lock:
        agent = _build_agent(tenant_id, permission_codes=permission_codes)
        result = agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}},
        )

    messages = result.get("messages") if isinstance(result, dict) else None
    reply = ""
    tool_traces: list[dict[str, Any]] = []
    if messages:
        for m in messages:
            mtype = getattr(m, "type", None) or m.__class__.__name__
            if mtype == "tool" or mtype == "ToolMessage":
                tool_traces.append(
                    {
                        "name": getattr(m, "name", None),
                        "content": _content_to_text(getattr(m, "content", ""))[:800],
                    }
                )
        last = messages[-1]
        reply = _content_to_text(getattr(last, "content", "")).strip()

    title = _auto_title(message) if is_new else None
    meta = _upsert_conversation(tenant_id, conv_id, title=title)
    ui_messages = _serialize_ui_messages(list(messages or []))
    if ui_messages:
        try:
            _save_ui_messages(tenant_id, conv_id, ui_messages)
        except Exception:
            pass

    return {
        "conversation_id": conv_id,
        "title": meta["title"],
        "reply": reply or "（无文本回复，请查看工具结果或重试）",
        "tool_traces": tool_traces[-8:],
        "model": get_settings().deepseek_model,
        "messages": ui_messages,
    }


def _sse_pack(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def iter_chat_sse(
    tenant_id: int,
    message: str,
    *,
    conversation_id: str | None = None,
    permission_codes: list[str] | None = None,
):
    """SSE 事件流：meta / token / tool / done / error。"""
    status = agent_available()
    if not status["enabled"]:
        yield _sse_pack({"type": "error", "message": status["reason"] or "agent_disabled"})
        return

    message = (message or "").strip()
    if not message:
        yield _sse_pack({"type": "error", "message": "empty_message"})
        return

    is_new = not (conversation_id or "").strip()
    conv_id = (conversation_id or "").strip() or uuid.uuid4().hex
    thread_id = _thread_id(tenant_id, conv_id)
    title = _auto_title(message) if is_new else None
    # 先落目录，流式过程中前端就能绑定 conversation_id
    meta = _upsert_conversation(tenant_id, conv_id, title=title)
    model_name = get_settings().deepseek_model

    yield _sse_pack(
        {
            "type": "meta",
            "conversation_id": conv_id,
            "title": meta["title"],
            "model": model_name,
        }
    )

    if not _lock.acquire(timeout=180):
        yield _sse_pack({"type": "error", "message": "军师忙碌，请稍后再试"})
        return

    reply_parts: list[str] = []
    tool_traces: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    try:
        agent = _build_agent(tenant_id, permission_codes=permission_codes)
        for item in agent.stream(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="messages",
        ):
            msg = item[0] if isinstance(item, tuple) and len(item) >= 1 else item
            mtype = getattr(msg, "type", None) or msg.__class__.__name__
            name = getattr(msg, "name", None)

            if mtype in ("tool", "ToolMessage"):
                content = _content_to_text(getattr(msg, "content", ""))
                trace = {
                    "name": name,
                    "content": content[:800],
                }
                tool_traces.append(trace)
                yield _sse_pack({"type": "tool", **trace})
                for c in workshop_metrics.extract_charts(content):
                    charts.append(c)
                    yield _sse_pack({"type": "chart", "chart": c})
                continue

            # 流式 token：仅 AIMessageChunk，避免完整 AIMessage 回放重复
            cls_name = msg.__class__.__name__
            if cls_name != "AIMessageChunk" and mtype != "AIMessageChunk":
                continue
            text = _content_to_text(getattr(msg, "content", ""))
            if not text:
                continue
            reply_parts.append(text)
            yield _sse_pack({"type": "token", "text": text})

        reply = "".join(reply_parts).strip()
        if not reply:
            # 回退读 checkpoint 最终消息
            try:
                detail = get_conversation_messages(tenant_id, conv_id)
                msgs = detail.get("messages") or []
                for m in reversed(msgs):
                    if m.get("role") == "assistant" and (m.get("content") or "").strip():
                        reply = str(m["content"]).strip()
                        if not charts and m.get("charts"):
                            charts = list(m.get("charts") or [])
                        break
            except Exception:
                pass
        if not reply:
            reply = "（无文本回复，请查看工具结果或重试）"

        _upsert_conversation(tenant_id, conv_id, title=None)
        try:
            _refresh_ui_message_cache(
                tenant_id, conv_id, permission_codes=permission_codes
            )
        except Exception:
            pass
        yield _sse_pack(
            {
                "type": "done",
                "conversation_id": conv_id,
                "title": meta["title"],
                "reply": reply,
                "tool_traces": tool_traces[-8:],
                "charts": charts[-6:],
                "model": model_name,
            }
        )
    except Exception as e:
        yield _sse_pack({"type": "error", "message": f"agent_error: {e}"})
    finally:
        _lock.release()
