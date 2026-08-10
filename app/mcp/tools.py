"""MCP 工具实现：指标白名单 + 排产只读仿真。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.mcp.scopes import (
    SCHEDULE_EXTRA_TOOLS,
    SERVER_METRICS,
    SERVER_META,
    SERVER_PERMISSIONS,
    ServerId,
)
from app.services import schedule_engine, schedule_settings, workshop_metrics


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def list_tool_defs(server: ServerId) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "name": "list_metrics",
            "description": (
                f"列出本 MCP（{SERVER_META[server]['title']}）可查询的只读指标。"
                "返回 id / name / description / params；对用户说话用中文 name。"
            ),
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "query_metric",
            "description": (
                "按白名单 metric_id 查询指标。params 为对象（非字符串）。"
                "结论以工具返回为准，禁止编造订单号/数量/金额。"
            ),
            "inputSchema": {
                "type": "object",
                "required": ["metric_id"],
                "properties": {
                    "metric_id": {"type": "string"},
                    "params": {"type": "object", "additionalProperties": True},
                },
            },
        },
    ]
    if server == "schedule":
        tools.extend(SCHEDULE_EXTRA_TOOLS)
    return tools


def call_tool(
    db: Session,
    *,
    tenant_id: int,
    server: ServerId,
    name: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    """返回 MCP tools/call 的 result 结构：{content, isError?}。"""
    args = dict(arguments or {})
    try:
        if name == "list_metrics":
            data = _list_metrics(server)
            return _ok(data)
        if name == "query_metric":
            data = _query_metric(db, tenant_id, server, args)
            return _ok(data)
        if server == "schedule":
            if name == "get_schedule_pool":
                return _ok(_schedule_pool(db, tenant_id, args))
            if name == "get_schedule_settings":
                return _ok(schedule_settings.get_schedule_by_tenant_id(db, tenant_id))
            if name == "get_daily_load":
                return _ok(_daily_load(db, tenant_id, args))
            if name == "generate_schedule_proposals":
                return _ok(_generate_proposals(db, tenant_id, args))
            if name == "simulate_insert_order":
                return _ok(_simulate_insert(db, tenant_id, args))
        return _err(f"未知工具：{name}")
    except Exception as e:
        return _err(str(e))


def _list_metrics(server: ServerId) -> dict[str, Any]:
    allow = SERVER_METRICS[server]
    perms = SERVER_PERMISSIONS[server]
    items = [
        m
        for m in workshop_metrics.list_metrics(permission_codes=perms)
        if m["id"] in allow
    ]
    return {"server": server, "items": items, "total": len(items)}


def _query_metric(
    db: Session,
    tenant_id: int,
    server: ServerId,
    args: dict[str, Any],
) -> dict[str, Any]:
    mid = str(args.get("metric_id") or "").strip()
    if mid not in SERVER_METRICS[server]:
        return {
            "error": "forbidden_metric",
            "message": f"本 MCP（{server}）不可查 {mid}",
            "allowed": sorted(SERVER_METRICS[server]),
        }
    params = args.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return {"error": "invalid_params", "message": "params 须为对象"}
    return workshop_metrics.query_metric(
        db,
        tenant_id,
        mid,
        params=params,
        permission_codes=SERVER_PERMISSIONS[server],
    )


def _schedule_pool(db: Session, tenant_id: int, args: dict[str, Any]) -> dict[str, Any]:
    items = schedule_engine.collect_candidate_orders(
        db,
        tenant_id,
        hide_scheduled=bool(args.get("hide_scheduled", True)),
        hide_first_kit_blocked=bool(args.get("hide_first_kit_blocked", False)),
    )
    return {"items": items, "total": len(items)}


def _daily_load(db: Session, tenant_id: int, args: dict[str, Any]) -> dict[str, Any]:
    days = max(1, min(int(args.get("days") or 14), 60))
    today = date.today()
    return schedule_engine.daily_load(
        db, tenant_id, date_from=today, date_to=today + timedelta(days=days)
    )


def _generate_proposals(db: Session, tenant_id: int, args: dict[str, Any]) -> Any:
    order_ids = args.get("order_ids")
    if order_ids is not None and not isinstance(order_ids, list):
        return {"error": "invalid_params", "message": "order_ids 须为整数数组"}
    ids = [int(x) for x in order_ids] if order_ids else None
    return schedule_engine.generate_proposals(
        db, tenant_id, order_ids=ids, hide_scheduled=True
    )


def _simulate_insert(db: Session, tenant_id: int, args: dict[str, Any]) -> dict[str, Any]:
    if args.get("order_id") is None:
        return {"error": "invalid_params", "message": "缺少 order_id"}
    try:
        props = schedule_engine.simulate_insert(db, tenant_id, int(args["order_id"]))
    except ValueError as e:
        return {"error": str(e)}
    return {"proposals": props}


def _ok(data: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _json_text(data)}],
        "structuredContent": data if isinstance(data, dict) else {"data": data},
    }


def _err(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }
