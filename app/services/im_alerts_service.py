"""A2d：IM 预警推送 + 进度日报（v1 stub，只推不改）。

从既有看板口径（`workshop_display_service`）派生「缺料 / 交期风险 / 进度日报」
三类文本消息，统一走租户级 Webhook（企微/钉钉群机器人协议最小子集）。
本模块只读取业务数据组装消息 + 用 `urllib` 发 HTTP POST，绝不写任何业务单据；
推送失败也只记录结果，不向调用方抛异常（不得阻断主业务路径）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from app.models import Tenant
from app.services.workshop_display_service import workshop_display

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

EVENT_TYPES: tuple[str, ...] = ("shortage", "delivery_risk", "digest")
ALERT_EVENT_TYPES: tuple[str, ...] = ("shortage", "delivery_risk")

DEFAULT_IM_ALERTS: dict[str, Any] = {
    "webhook_url": None,
    "enabled": False,
    # 首次开启默认全选；可再关子项
    "events": list(EVENT_TYPES),
}

REQUEST_TIMEOUT_SECONDS = 5


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _clean_url(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def default_im_alerts() -> dict[str, Any]:
    return deepcopy(DEFAULT_IM_ALERTS)


def merge_im_alerts(stored: Optional[dict[str, Any]]) -> dict[str, Any]:
    """合并租户覆盖；events 过滤到合法白名单，避免脏配置。"""
    out = default_im_alerts()
    raw = _as_dict(stored)
    src = _as_dict(raw.get("im_alerts") if "im_alerts" in raw else raw)
    if "webhook_url" in src:
        out["webhook_url"] = _clean_url(src.get("webhook_url"))
    if "enabled" in src:
        out["enabled"] = bool(src["enabled"])
    if "events" in src and isinstance(src["events"], list):
        out["events"] = [str(e) for e in src["events"] if str(e) in EVENT_TYPES]
    return out


def get_tenant_settings(tenant: Optional[Tenant]) -> dict[str, Any]:
    if tenant is None:
        return {}
    return _as_dict(getattr(tenant, "settings_json", None))


def get_im_alerts_for_tenant(tenant: Optional[Tenant]) -> dict[str, Any]:
    settings = get_tenant_settings(tenant)
    return merge_im_alerts(_as_dict(settings.get("im_alerts")) if settings else None)


def get_im_alerts_by_tenant_id(db: "Session", tenant_id: int) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    return get_im_alerts_for_tenant(tenant)


def save_im_alerts_patch(db: "Session", tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    """合并写入 tenant.settings_json.im_alerts（仅允许白名单字段）。"""
    from sqlalchemy.orm.attributes import flag_modified

    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("tenant_not_found")
    settings = dict(_as_dict(getattr(tenant, "settings_json", None)))
    current = dict(_as_dict(settings.get("im_alerts")))
    if "webhook_url" in patch:
        current["webhook_url"] = _clean_url(patch["webhook_url"])
    if "enabled" in patch:
        current["enabled"] = bool(patch["enabled"])
    if "events" in patch and isinstance(patch["events"], list):
        current["events"] = [str(e) for e in patch["events"] if str(e) in EVENT_TYPES]
    settings["im_alerts"] = merge_im_alerts(current)
    tenant.settings_json = settings
    flag_modified(tenant, "settings_json")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return get_im_alerts_for_tenant(tenant)


# ---------------------------------------------------------------------------
# 事件收集 + 消息组装（只读看板数据，不改任何单据）
# ---------------------------------------------------------------------------


def collect_shortage_events(db: "Session", tenant_id: int, *, limit: int = 5) -> list[dict[str, Any]]:
    display = workshop_display(db, tenant_id)
    blocks = display.get("material_blocks") or []
    events: list[dict[str, Any]] = []
    for row in blocks[:limit]:
        rush = " (急单)" if row.get("is_rush") else ""
        events.append(
            {
                "type": "shortage",
                "order_no": row.get("order_no"),
                "text": f"{row.get('order_no')}：{row.get('label')}{rush}",
            }
        )
    return events


def collect_delivery_risk_events(db: "Session", tenant_id: int, *, limit: int = 5) -> list[dict[str, Any]]:
    display = workshop_display(db, tenant_id)
    focus = display.get("focus_orders") or []
    risky = [r for r in focus if r.get("at_risk") or (r.get("is_rush") and r.get("material_blocked"))]
    events: list[dict[str, Any]] = []
    for row in risky[:limit]:
        events.append(
            {
                "type": "delivery_risk",
                "order_no": row.get("order_no"),
                "text": (
                    f"{row.get('order_no')}：{row.get('customer_name') or '—'} "
                    f"交期 {row.get('delivery_label')}，进度 {row.get('overall_percent')}%"
                ),
            }
        )
    return events


def _now_label() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def build_alert_payload(
    db: "Session",
    tenant_id: int,
    *,
    event_types: list[str] | None = None,
) -> dict[str, Any]:
    """组装缺料/交期风险预警文本；不发送，仅返回将要推送的内容。"""
    types = [t for t in (event_types or list(ALERT_EVENT_TYPES)) if t in ALERT_EVENT_TYPES]
    events: list[dict[str, Any]] = []
    if "shortage" in types:
        events.extend(collect_shortage_events(db, tenant_id))
    if "delivery_risk" in types:
        events.extend(collect_delivery_risk_events(db, tenant_id))

    tenant = db.get(Tenant, tenant_id)
    factory = tenant.name if tenant else "工厂"
    now = _now_label()

    if not events:
        content = f"【{factory}】{now} 预警：暂无缺料/交期风险，一切正常。"
    else:
        lines = [f"【{factory}】{now} 预警（{len(events)} 条）："]
        lines.extend(f"- {e['text']}" for e in events)
        content = "\n".join(lines)

    return {
        "kind": "alert",
        "generated_at": now,
        "event_count": len(events),
        "events": events,
        "message": {"msgtype": "text", "text": {"content": content}},
    }


def build_daily_digest(db: "Session", tenant_id: int) -> dict[str, Any]:
    """进度日报：昨日产量 + 今日在制概况 + Top5 重点订单。"""
    display = workshop_display(db, tenant_id)
    summary = display.get("summary") or {}
    top_focus = (display.get("focus_orders") or [])[:5]

    tenant = db.get(Tenant, tenant_id)
    factory = tenant.name if tenant else "工厂"
    now = _now_label()

    lines = [
        f"【{factory}】进度日报 {now}",
        f"昨日合格 {summary.get('yesterday_qualified', 0)}，不良 {summary.get('yesterday_defect', 0)}"
        f"（不良率 {summary.get('yesterday_defect_rate', 0)}%）",
        f"急单 {summary.get('rush_orders', 0)} 单，缺料 {summary.get('material_blocked_orders', 0)} 单",
    ]
    if top_focus:
        lines.append("重点跟进：")
        for row in top_focus:
            lines.append(
                f"- {row.get('order_no')} {row.get('customer_name') or '—'} "
                f"交期{row.get('delivery_label')} 进度{row.get('overall_percent')}%"
            )
    content = "\n".join(lines)

    return {
        "kind": "digest",
        "generated_at": now,
        "summary": summary,
        "focus_orders": top_focus,
        "message": {"msgtype": "text", "text": {"content": content}},
    }


def post_json(url: str, payload: dict[str, Any], *, timeout: int = REQUEST_TIMEOUT_SECONDS) -> dict[str, Any]:
    """向 Webhook POST JSON。任何异常均捕获返回 ok=False，绝不抛出（只推不改）。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", None) or resp.getcode())
            body = resp.read().decode("utf-8", errors="replace")
            return {"ok": 200 <= status < 300, "status": status, "body": body[:2000], "error": None}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return {"ok": False, "status": e.code, "body": body[:2000], "error": str(e)}
    except Exception as e:  # noqa: BLE001 — 推送失败不得抛给业务主路径
        return {"ok": False, "status": None, "body": "", "error": str(e)}


def send_test(
    db: "Session",
    tenant_id: int,
    *,
    kind: str = "alert",
    webhook_url_override: str | None = None,
) -> dict[str, Any]:
    """试发一条：忽略 `enabled`（未开也可先测连通性），但仍须提供 webhook_url。"""
    settings = get_im_alerts_by_tenant_id(db, tenant_id)
    url = _clean_url(webhook_url_override) or settings.get("webhook_url")
    if not url:
        raise ValueError("未配置 webhook_url，无法试发")

    payload = build_daily_digest(db, tenant_id) if kind == "digest" else build_alert_payload(db, tenant_id)
    result = post_json(url, payload["message"])
    return {"kind": payload["kind"], "webhook_url": url, "payload": payload, "result": result}


def send_alert_if_enabled(db: "Session", tenant_id: int) -> dict[str, Any] | None:
    """供未来定时任务调用：仅当 `enabled` 且 events 命中缺料/交期风险才真正推送。

    v1 无内置调度器，本迭代 UI 只做「预览」+「试发」；此函数留好签名给后续接
    cron / Agent 定时任务时直接复用，避免届时重开一套口径。
    """
    settings = get_im_alerts_by_tenant_id(db, tenant_id)
    if not settings.get("enabled") or not settings.get("webhook_url"):
        return None
    types = [t for t in (settings.get("events") or []) if t in ALERT_EVENT_TYPES]
    if not types:
        return None
    payload = build_alert_payload(db, tenant_id, event_types=types)
    if not payload.get("event_count"):
        return None
    result = post_json(settings["webhook_url"], payload["message"])
    return {"payload": payload, "result": result}


def send_digest_if_enabled(db: "Session", tenant_id: int) -> dict[str, Any] | None:
    """供未来定时任务调用：仅当 `enabled` 且勾选 `digest` 才真正推送日报。"""
    settings = get_im_alerts_by_tenant_id(db, tenant_id)
    if not settings.get("enabled") or not settings.get("webhook_url"):
        return None
    if "digest" not in (settings.get("events") or []):
        return None
    payload = build_daily_digest(db, tenant_id)
    result = post_json(settings["webhook_url"], payload["message"])
    return {"payload": payload, "result": result}
