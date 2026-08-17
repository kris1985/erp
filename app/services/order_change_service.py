"""B2c：生产单变更版本 — qty/交期/色码明细变更留痕，供 PMC 查历史；不做审批流。

只在「数量或交期发生实际变化」时追加一条版本记录；客户/备注/状态/急单等其它字段
变更不进版本历史（避免噪音）。快照字段：total_qty、delivery_date、items(color/size/qty)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Color, Order, OrderChangeLog, OrderItem, Size, Employee


class OrderChangeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _fetch_items_snapshot(db: Session, tenant_id: int, order_id: int) -> list[dict[str, Any]]:
    """从 DB 取当前色码明细（同一事务内可见 flush 后未提交的改动）。"""
    rows = db.execute(
        select(OrderItem.color_id, OrderItem.size_id, OrderItem.qty).where(
            OrderItem.tenant_id == tenant_id,
            OrderItem.order_id == order_id,
        )
    ).all()
    items = [
        {"color_id": r[0], "size_id": r[1], "qty": int(r[2] or 0)} for r in rows
    ]
    items.sort(key=lambda x: (x["color_id"] or 0, x["size_id"] or 0))
    return items


def capture_order_snapshot(db: Session, tenant_id: int, order: Order) -> dict[str, Any]:
    """在改动前/改动后各调一次，用于 diff。总数取 order.total_qty（内存中已即时更新）。"""
    return {
        "total_qty": int(order.total_qty or 0),
        "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
        "items": _fetch_items_snapshot(db, tenant_id, order.id),
    }


def _next_version_no(db: Session, tenant_id: int, order_id: int) -> int:
    last = db.scalar(
        select(OrderChangeLog.version_no)
        .where(OrderChangeLog.tenant_id == tenant_id, OrderChangeLog.order_id == order_id)
        .order_by(OrderChangeLog.version_no.desc())
        .limit(1)
    )
    return int(last or 0) + 1


def _label(color_id: int | None, size_id: int | None, colors: dict, sizes: dict) -> str:
    c = colors.get(color_id) if color_id else None
    s = sizes.get(size_id) if size_id else None
    color_name = c.name if c else ("无色" if color_id is None else str(color_id))
    size_value = s.size_value if s else (str(size_id) if size_id else "?")
    return f"{color_name}{size_value}"


def _build_summary(
    db: Session,
    tenant_id: int,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    qty_changed: bool,
    delivery_changed: bool,
) -> str:
    parts: list[str] = []
    if qty_changed:
        parts.append(f"总数 {before['total_qty']}→{after['total_qty']}")

        before_map = {(i["color_id"], i["size_id"]): i["qty"] for i in before["items"]}
        after_map = {(i["color_id"], i["size_id"]): i["qty"] for i in after["items"]}
        keys = sorted(
            set(before_map) | set(after_map),
            key=lambda k: (k[0] or 0, k[1] or 0),
        )
        color_ids = {k[0] for k in keys if k[0]}
        size_ids = {k[1] for k in keys if k[1]}
        colors = (
            {c.id: c for c in db.scalars(select(Color).where(Color.id.in_(color_ids))).all()}
            if color_ids
            else {}
        )
        sizes = (
            {s.id: s for s in db.scalars(select(Size).where(Size.id.in_(size_ids))).all()}
            if size_ids
            else {}
        )
        item_diffs: list[str] = []
        for key in keys:
            b = before_map.get(key)
            a = after_map.get(key)
            if b == a:
                continue
            label = _label(key[0], key[1], colors, sizes)
            if b is None:
                item_diffs.append(f"{label}新增{a}")
            elif a is None:
                item_diffs.append(f"{label}删除(原{b})")
            else:
                item_diffs.append(f"{label} {b}→{a}")
        if item_diffs:
            parts.append("色码：" + "、".join(item_diffs))
    if delivery_changed:
        parts.append(f"交期 {before['delivery_date'] or '—'}→{after['delivery_date'] or '—'}")
    return "；".join(parts) or "订单信息变更"


def record_order_change_if_needed(
    db: Session,
    tenant_id: int,
    order: Order,
    before: dict[str, Any],
    *,
    changed_by: int | None = None,
) -> OrderChangeLog | None:
    """比较 before 快照与当前状态；有实质变化则追加一条版本记录（同事务内 flush，不单独 commit）。"""
    after = capture_order_snapshot(db, tenant_id, order)

    qty_changed = before["total_qty"] != after["total_qty"] or before["items"] != after["items"]
    delivery_changed = before["delivery_date"] != after["delivery_date"]
    if not qty_changed and not delivery_changed:
        return None

    change_types = []
    if qty_changed:
        change_types.append("qty")
    if delivery_changed:
        change_types.append("delivery_date")

    summary = _build_summary(
        db, tenant_id, before, after, qty_changed=qty_changed, delivery_changed=delivery_changed
    )

    log = OrderChangeLog(
        tenant_id=tenant_id,
        order_id=order.id,
        version_no=_next_version_no(db, tenant_id, order.id),
        change_type=",".join(change_types),
        summary=summary,
        before_json=before,
        after_json=after,
        created_by=changed_by,
    )
    db.add(log)
    db.flush()
    return log


def serialize_change_log(log: OrderChangeLog, *, created_by_name: str | None = None) -> dict[str, Any]:
    return {
        "id": log.id,
        "order_id": log.order_id,
        "version_no": log.version_no,
        "change_type": log.change_type,
        "summary": log.summary,
        "before": log.before_json,
        "after": log.after_json,
        "created_by": log.created_by,
        "created_by_name": created_by_name,
        "created_at": log.created_at.isoformat(timespec="seconds") if log.created_at else None,
    }


def list_order_change_logs(db: Session, tenant_id: int, order_id: int) -> list[dict[str, Any]]:
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise OrderChangeError("not_found", "订单不存在")
    rows = list(
        db.scalars(
            select(OrderChangeLog)
            .where(OrderChangeLog.tenant_id == tenant_id, OrderChangeLog.order_id == order_id)
            .order_by(OrderChangeLog.version_no.desc())
        ).all()
    )
    user_ids = {r.created_by for r in rows if r.created_by}
    users = (
        {u.id: u.name for u in db.scalars(select(Employee).where(Employee.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )
    return [serialize_change_log(r, created_by_name=users.get(r.created_by)) for r in rows]
