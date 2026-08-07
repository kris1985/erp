"""排产建议草稿：倒排时间窗 → 人工确认 → 写 OrderProcess 日期。

确认前不改派工/报工/材料占用。不上甘特拖拽。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Order,
    OrderProcess,
    OrderStatus,
    OwnProduct,
    ScheduleDraft,
    ScheduleDraftLine,
    ScheduleDraftStatus,
    ScheduleStatus,
)
from app.services import material_service

# 粗工期：每道工序默认占用天数（中小厂可先固定，后期接节拍）
DEFAULT_PROCESS_DAYS = 1


class ScheduleError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _open_statuses() -> list[OrderStatus]:
    return [OrderStatus.confirmed, OrderStatus.in_progress]


def list_schedule_pool(
    db: Session,
    tenant_id: int,
    *,
    keyword: str | None = None,
    rush_only: bool = False,
    hide_first_kit_blocked: bool = False,
) -> list[dict]:
    """待排池：已确认/生产中的 MO。"""
    q = select(Order).where(
        Order.tenant_id == tenant_id,
        Order.status.in_(_open_statuses()),
    )
    if rush_only:
        q = q.where(Order.is_rush.is_(True))
    if keyword and keyword.strip():
        kw = keyword.strip()
        product_ids = list(
            db.scalars(
                select(OwnProduct.id).where(
                    OwnProduct.tenant_id == tenant_id,
                    OwnProduct.product_code.contains(kw),
                )
            ).all()
        )
        if product_ids:
            q = q.where(
                Order.order_no.contains(kw)
                | Order.customer_name.contains(kw)
                | Order.own_product_id.in_(product_ids)
            )
        else:
            q = q.where(Order.order_no.contains(kw) | Order.customer_name.contains(kw))
    orders = list(db.scalars(q.order_by(Order.is_rush.desc(), Order.delivery_date, Order.id)).all())
    if not orders:
        return []

    product_ids = {o.own_product_id for o in orders if o.own_product_id}
    product_map: dict[int, OwnProduct] = {}
    if product_ids:
        product_map = {
            p.id: p
            for p in db.scalars(
                select(OwnProduct).where(
                    OwnProduct.tenant_id == tenant_id,
                    OwnProduct.id.in_(product_ids),
                )
            ).all()
        }

    for o in orders:
        material_service.ensure_material_snapshot(db, tenant_id, o)
    db.flush()
    ctx = material_service.build_kit_context(db, tenant_id)
    out: list[dict] = []
    for o in orders:
        summary = ctx.summary_for_order(o.id)
        first_ok = bool(summary.get("first_kit_ok", summary.get("kit_ok")))
        if hide_first_kit_blocked and not first_ok and not summary.get("empty_bom"):
            continue
        procs = list(
            db.scalars(
                select(OrderProcess)
                .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == o.id)
                .order_by(OrderProcess.id)
            ).all()
        )
        scheduled_n = sum(1 for p in procs if p.start_date and p.end_date)
        product = product_map.get(o.own_product_id)
        out.append(
            {
                "order_id": o.id,
                "order_no": o.order_no,
                "customer_name": o.customer_name,
                "own_product_id": o.own_product_id,
                "product_code": product.product_code if product else None,
                "product_image_url": product.image_url if product else None,
                "total_qty": o.total_qty,
                "delivery_date": o.delivery_date,
                "is_rush": bool(o.is_rush),
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "schedule_status": (
                    o.schedule_status.value
                    if getattr(o, "schedule_status", None) and hasattr(o.schedule_status, "value")
                    else str(getattr(o, "schedule_status", None) or "none")
                ),
                "kit_ok": bool(summary.get("kit_ok")),
                "first_kit_ok": first_ok,
                "first_process_name": summary.get("first_process_name"),
                "empty_bom": bool(summary.get("empty_bom")),
                "process_count": len(procs),
                "scheduled_process_count": scheduled_n,
            }
        )
    return out


def _backward_windows(
    processes: list[OrderProcess],
    delivery: date | None,
    *,
    days_per_process: int = DEFAULT_PROCESS_DAYS,
) -> list[tuple[date, date]]:
    """按路线倒序倒排：末道完工落在交期（或今天+工序数）。"""
    n = len(processes)
    if n == 0:
        return []
    days = max(1, int(days_per_process))
    end = delivery or (date.today() + timedelta(days=n * days))
    windows: list[tuple[date, date]] = [None] * n  # type: ignore
    cursor_end = end
    for i in range(n - 1, -1, -1):
        start = cursor_end - timedelta(days=days - 1)
        windows[i] = (start, cursor_end)
        cursor_end = start - timedelta(days=1)
    return windows


def create_draft(
    db: Session,
    tenant_id: int,
    order_ids: list[int],
    *,
    user_id: int | None = None,
    note: str | None = None,
    process_ids: list[int] | None = None,
    days_per_process: int = DEFAULT_PROCESS_DAYS,
) -> dict:
    if not order_ids:
        raise ScheduleError("empty", "请选择生产订单")
    orders = list(
        db.scalars(
            select(Order).where(
                Order.tenant_id == tenant_id,
                Order.id.in_(order_ids),
                Order.status.in_(_open_statuses()),
            )
        ).all()
    )
    if len(orders) != len(set(order_ids)):
        raise ScheduleError("order_not_found", "部分订单不存在或不在可排状态")

    # 优先级：急单 → 交期近 → id
    orders.sort(key=lambda o: (0 if o.is_rush else 1, o.delivery_date or date.max, o.id))

    draft = ScheduleDraft(
        tenant_id=tenant_id,
        status=ScheduleDraftStatus.draft,
        note=note,
        created_by=user_id,
    )
    db.add(draft)
    db.flush()

    allow_procs = set(process_ids) if process_ids else None
    priority = 0
    for order in orders:
        procs = list(
            db.scalars(
                select(OrderProcess)
                .where(OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == order.id)
                .order_by(OrderProcess.id)
            ).all()
        )
        windows = _backward_windows(procs, order.delivery_date, days_per_process=days_per_process)
        for p, (start, end) in zip(procs, windows):
            included = True if allow_procs is None else (p.process_id in allow_procs)
            db.add(
                ScheduleDraftLine(
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    order_id=order.id,
                    order_process_id=p.id,
                    process_id=p.process_id,
                    process_name=p.process_name,
                    plan_qty=p.plan_qty,
                    start_date=start,
                    end_date=end,
                    sort_priority=priority,
                    included=included,
                )
            )
        order.schedule_status = ScheduleStatus.drafted
        priority += 1

    db.commit()
    return get_draft(db, tenant_id, draft.id)


def get_draft(db: Session, tenant_id: int, draft_id: int) -> dict:
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft_id, ScheduleDraft.tenant_id == tenant_id)
        .options(selectinload(ScheduleDraft.lines))
    )
    if not draft:
        raise ScheduleError("not_found", "排产草稿不存在")
    lines = sorted(draft.lines, key=lambda x: (x.sort_priority, x.id))
    order_ids = sorted({ln.order_id for ln in lines})
    order_map = {
        o.id: o
        for o in db.scalars(
            select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(order_ids or [0]))
        ).all()
    }
    product_ids = {o.own_product_id for o in order_map.values() if o.own_product_id}
    product_map: dict[int, OwnProduct] = {}
    if product_ids:
        product_map = {
            p.id: p
            for p in db.scalars(
                select(OwnProduct).where(
                    OwnProduct.tenant_id == tenant_id,
                    OwnProduct.id.in_(product_ids),
                )
            ).all()
        }
    kit_cache: dict[int, dict] = {}
    for oid in order_ids:
        try:
            kit_cache[oid] = material_service.get_order_kit(db, tenant_id, oid)
        except material_service.MaterialError:
            kit_cache[oid] = {}

    line_out = []
    for ln in lines:
        order = order_map.get(ln.order_id)
        product = product_map.get(order.own_product_id) if order else None
        kit = kit_cache.get(ln.order_id) or {}
        by_proc = {x["process_id"]: x for x in kit.get("by_process") or []}
        proc_kit = by_proc.get(ln.process_id) or {}
        first_id = kit.get("first_process_id")
        is_first = first_id is not None and ln.process_id == first_id
        line_out.append(
            {
                "id": ln.id,
                "order_id": ln.order_id,
                "order_no": order.order_no if order else None,
                "customer_name": order.customer_name if order else None,
                "product_code": product.product_code if product else None,
                "product_image_url": product.image_url if product else None,
                "delivery_date": order.delivery_date if order else None,
                "is_rush": bool(order.is_rush) if order else False,
                "order_process_id": ln.order_process_id,
                "process_id": ln.process_id,
                "process_name": ln.process_name,
                "plan_qty": ln.plan_qty,
                "start_date": ln.start_date,
                "end_date": ln.end_date,
                "sort_priority": ln.sort_priority,
                "included": bool(ln.included),
                "is_first": is_first,
                "process_kit_ok": bool(proc_kit.get("kit_ok", True)) if proc_kit else True,
                "first_kit_ok": bool(kit.get("first_kit_ok", True)),
            }
        )
    return {
        "id": draft.id,
        "status": draft.status.value if hasattr(draft.status, "value") else str(draft.status),
        "note": draft.note,
        "created_by": draft.created_by,
        "confirmed_by": draft.confirmed_by,
        "confirmed_at": draft.confirmed_at,
        "created_at": draft.created_at,
        "lines": line_out,
    }


def patch_draft_line(
    db: Session,
    tenant_id: int,
    draft_id: int,
    line_id: int,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    included: bool | None = None,
    plan_qty: int | None = None,
) -> dict:
    draft = db.get(ScheduleDraft, draft_id)
    if not draft or draft.tenant_id != tenant_id:
        raise ScheduleError("not_found", "排产草稿不存在")
    if draft.status != ScheduleDraftStatus.draft:
        raise ScheduleError("not_editable", "仅草稿可修改")
    line = db.get(ScheduleDraftLine, line_id)
    if not line or line.tenant_id != tenant_id or line.draft_id != draft_id:
        raise ScheduleError("line_not_found", "草稿行不存在")
    if start_date is not None:
        line.start_date = start_date
    if end_date is not None:
        line.end_date = end_date
    if included is not None:
        line.included = included
    if plan_qty is not None:
        if plan_qty <= 0:
            raise ScheduleError("invalid_qty", "计划数量须大于 0")
        line.plan_qty = plan_qty
    if line.start_date and line.end_date and line.start_date > line.end_date:
        raise ScheduleError("invalid_dates", "开始日期不能晚于结束日期")
    db.commit()
    return get_draft(db, tenant_id, draft_id)


def confirm_draft(
    db: Session,
    tenant_id: int,
    draft_id: int,
    *,
    user_id: int | None = None,
    require_first_kit: bool = True,
) -> dict:
    """确认：写回 OrderProcess 时间窗；不自动派工（需指定工人）。"""
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft_id, ScheduleDraft.tenant_id == tenant_id)
        .options(selectinload(ScheduleDraft.lines))
    )
    if not draft:
        raise ScheduleError("not_found", "排产草稿不存在")
    if draft.status != ScheduleDraftStatus.draft:
        raise ScheduleError("not_confirmable", "草稿已确认或已作废")

    included = [ln for ln in draft.lines if ln.included]
    if not included:
        raise ScheduleError("empty_lines", "没有勾选要确认的工序行")

    # 首道齐套闸门：任一订单若包含首道且 first_kit 不齐 → 阻断
    order_ids = {ln.order_id for ln in included}
    for oid in order_ids:
        kit = material_service.get_order_kit(db, tenant_id, oid)
        first_id = kit.get("first_process_id")
        if not require_first_kit or not first_id:
            continue
        touches_first = any(ln.process_id == first_id for ln in included if ln.order_id == oid)
        if touches_first and not kit.get("empty_bom") and not kit.get("first_kit_ok"):
            order = db.get(Order, oid)
            raise ScheduleError(
                "first_kit_blocked",
                f"订单 {order.order_no if order else oid} 首道缺料，不能确认开裁段排产",
            )
        # 分段：非首道也校验对应 process_kit
        for ln in included:
            if ln.order_id != oid:
                continue
            by_proc = {x["process_id"]: x for x in kit.get("by_process") or []}
            info = by_proc.get(ln.process_id)
            if info and not info.get("kit_ok"):
                raise ScheduleError(
                    "process_kit_blocked",
                    f"订单 {kit.get('order_no') or oid} 工序「{ln.process_name}」缺料，无法确认该段",
                )

    touched_orders: set[int] = set()
    for ln in included:
        proc = db.get(OrderProcess, ln.order_process_id)
        if not proc or proc.tenant_id != tenant_id:
            raise ScheduleError("process_missing", f"工序计划不存在: {ln.order_process_id}")
        proc.start_date = ln.start_date
        proc.end_date = ln.end_date
        touched_orders.add(ln.order_id)

    for oid in touched_orders:
        procs = list(
            db.scalars(
                select(OrderProcess).where(
                    OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == oid
                )
            ).all()
        )
        dated = sum(1 for p in procs if p.start_date and p.end_date)
        order = db.get(Order, oid)
        if not order:
            continue
        if dated == 0:
            order.schedule_status = ScheduleStatus.none
        elif dated < len(procs):
            order.schedule_status = ScheduleStatus.partial
        else:
            order.schedule_status = ScheduleStatus.scheduled

    draft.status = ScheduleDraftStatus.confirmed
    draft.confirmed_by = user_id
    draft.confirmed_at = datetime.now()
    db.commit()
    return get_draft(db, tenant_id, draft_id)


def discard_draft(db: Session, tenant_id: int, draft_id: int) -> dict:
    draft = db.scalar(
        select(ScheduleDraft)
        .where(ScheduleDraft.id == draft_id, ScheduleDraft.tenant_id == tenant_id)
        .options(selectinload(ScheduleDraft.lines))
    )
    if not draft:
        raise ScheduleError("not_found", "排产草稿不存在")
    if draft.status != ScheduleDraftStatus.draft:
        raise ScheduleError("not_discardable", "仅草稿可作废")
    order_ids = {ln.order_id for ln in draft.lines}
    draft.status = ScheduleDraftStatus.discarded
    for oid in order_ids:
        order = db.get(Order, oid)
        if not order or order.tenant_id != tenant_id:
            continue
        # 若该单没有其它 draft 中草稿，且工序尚无日期 → 回 none
        other = db.scalar(
            select(ScheduleDraftLine.id)
            .join(ScheduleDraft, ScheduleDraft.id == ScheduleDraftLine.draft_id)
            .where(
                ScheduleDraftLine.order_id == oid,
                ScheduleDraft.tenant_id == tenant_id,
                ScheduleDraft.status == ScheduleDraftStatus.draft,
                ScheduleDraft.id != draft_id,
            )
            .limit(1)
        )
        if other:
            continue
        procs = list(
            db.scalars(
                select(OrderProcess).where(
                    OrderProcess.tenant_id == tenant_id, OrderProcess.order_id == oid
                )
            ).all()
        )
        dated = sum(1 for p in procs if p.start_date and p.end_date)
        if dated == 0:
            order.schedule_status = ScheduleStatus.none
        elif dated < len(procs):
            order.schedule_status = ScheduleStatus.partial
        else:
            order.schedule_status = ScheduleStatus.scheduled
    db.commit()
    return {"id": draft_id, "status": "discarded"}


def list_drafts(db: Session, tenant_id: int, *, status: str | None = "draft", limit: int = 50) -> list[dict]:
    q = (
        select(ScheduleDraft)
        .where(ScheduleDraft.tenant_id == tenant_id)
        .options(selectinload(ScheduleDraft.lines))
    )
    if status:
        q = q.where(ScheduleDraft.status == ScheduleDraftStatus(status))
    rows = db.scalars(q.order_by(ScheduleDraft.id.desc()).limit(limit)).all()
    return [
        {
            "id": d.id,
            "status": d.status.value if hasattr(d.status, "value") else str(d.status),
            "note": d.note,
            "created_at": d.created_at,
            "confirmed_at": d.confirmed_at,
            "line_count": len(d.lines or []),
        }
        for d in rows
    ]


def list_calendar(
    db: Session,
    tenant_id: int,
    *,
    date_from: date,
    date_to: date,
) -> dict:
    """全局已确认工序计划（只读）：OrderProcess 已写 start/end 且与区间相交。"""
    from app.utils.cn_holidays import day_meta_range

    if date_to < date_from:
        raise ScheduleError("invalid_range", "结束日期不能早于开始日期")
    if (date_to - date_from).days > 62:
        raise ScheduleError("range_too_long", "查询跨度请不超过 62 天")

    day_meta = day_meta_range(date_from, date_to)

    procs = list(
        db.scalars(
            select(OrderProcess)
            .where(
                OrderProcess.tenant_id == tenant_id,
                OrderProcess.start_date.is_not(None),
                OrderProcess.end_date.is_not(None),
                OrderProcess.start_date <= date_to,
                OrderProcess.end_date >= date_from,
            )
            .order_by(OrderProcess.start_date, OrderProcess.id)
        ).all()
    )
    if not procs:
        return {
            "from": date_from,
            "to": date_to,
            "items": [],
            "by_date": {k: [] for k in day_meta},
            "day_meta": day_meta,
        }

    order_ids = {p.order_id for p in procs}
    orders = {
        o.id: o
        for o in db.scalars(
            select(Order).where(Order.tenant_id == tenant_id, Order.id.in_(order_ids))
        ).all()
    }
    # 仅开放状态的单；取消/完成仍可看计划痕迹则不过滤——生管看全局更希望含在制。已取消可滤掉。
    product_ids = {o.own_product_id for o in orders.values() if o.own_product_id}
    products = {
        p.id: p
        for p in db.scalars(
            select(OwnProduct).where(
                OwnProduct.tenant_id == tenant_id,
                OwnProduct.id.in_(product_ids or [0]),
            )
        ).all()
    }

    items: list[dict] = []
    for p in procs:
        order = orders.get(p.order_id)
        if not order or order.status == OrderStatus.cancelled:
            continue
        product = products.get(order.own_product_id)
        items.append(
            {
                "order_process_id": p.id,
                "order_id": order.id,
                "order_no": order.order_no,
                "customer_name": order.customer_name,
                "own_product_id": order.own_product_id,
                "product_code": product.product_code if product else None,
                "product_image_url": product.image_url if product else None,
                "is_rush": bool(order.is_rush),
                "process_id": p.process_id,
                "process_name": p.process_name,
                "plan_qty": p.plan_qty,
                "completed_qty": p.completed_qty,
                "status": p.status.value if hasattr(p.status, "value") else str(p.status),
                "start_date": p.start_date,
                "end_date": p.end_date,
                "delivery_date": order.delivery_date,
            }
        )

    by_date: dict[str, list[dict]] = {}
    cur = date_from
    while cur <= date_to:
        key = cur.isoformat()
        day_items = []
        for it in items:
            if it["start_date"] <= cur <= it["end_date"]:
                day_items.append(it)
        by_date[key] = day_items
        cur += timedelta(days=1)

    return {
        "from": date_from,
        "to": date_to,
        "items": items,
        "by_date": by_date,
        "day_meta": day_meta,
    }
