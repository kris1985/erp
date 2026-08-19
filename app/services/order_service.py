from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductLabor,
    OwnProductPart,
    OwnProductQuote,
    Partner,
    ProcessDefinition,
    SalesOrder,
    Size,
)
from app.schemas.api import OrderCreate, OrderItemIn, SizeAdjustItemIn


class OrderError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def order_labors_for_route(
    db: Session,
    tenant_id: int,
    own_product_id: int,
    *,
    labors: list[OwnProductLabor] | None = None,
) -> list[OwnProductLabor]:
    """产品工序报价，按部件清单排序（与 create_order 一致）。"""
    if labors is None:
        labors = list(
            db.scalars(
                select(OwnProductLabor)
                .where(
                    OwnProductLabor.tenant_id == tenant_id,
                    OwnProductLabor.own_product_id == own_product_id,
                    OwnProductLabor.process_id.is_not(None),
                )
                .order_by(OwnProductLabor.sort_order, OwnProductLabor.id)
            ).all()
        )
    if not labors:
        raise OrderError("no_route", "该产品未配置工序报价")
    parts = list(
        db.scalars(
            select(OwnProductPart)
            .where(
                OwnProductPart.tenant_id == tenant_id,
                OwnProductPart.own_product_id == own_product_id,
            )
            .order_by(OwnProductPart.sort_order, OwnProductPart.id)
        ).all()
    )
    if not parts:
        return labors
    by_part: dict[int | None, list[OwnProductLabor]] = {}
    for labor in labors:
        by_part.setdefault(labor.part_id, []).append(labor)
    ordered: list[OwnProductLabor] = []
    known = {p.part_id for p in parts}
    for part in parts:
        ordered.extend(by_part.get(part.part_id, []))
    for pid, rows in by_part.items():
        if pid is not None and pid not in known:
            ordered.extend(rows)
    ordered.extend(by_part.get(None, []))
    return ordered


ORDER_SORT_FIELDS = {
    "order_no": Order.order_no,
    "delivery_date": Order.delivery_date,
    "created_at": Order.created_at,
    "total_qty": Order.total_qty,
    "product_code": "product_code",  # join OwnProduct
    "sales_order_no": "sales_order_no",  # join SalesOrder
}

ORDER_STATUS_STAT_KEYS = (
    "draft",
    "confirmed",
    "in_progress",
    "completed",
    "cancelled",
)


def _order_nulls_last(column, *, asc: bool = True):
    """MySQL-compatible NULLS LAST."""
    return column.is_(None).asc(), column.asc() if asc else column.desc()


def _resolve_customer(
    db: Session,
    tenant_id: int,
    *,
    customer_id: int | None,
    customer_name: str | None,
) -> tuple[int | None, str]:
    """返回 (customer_id, customer_name)。可只选档案、可只手填。"""
    if customer_id:
        p = db.get(Partner, customer_id)
        if not p or p.tenant_id != tenant_id or not p.is_active:
            raise OrderError("customer_not_found", "客户不存在或未启用")
        if not (p.is_customer or p.is_brand):
            raise OrderError("not_customer", "所选单位不是客户/品牌方")
        name = (customer_name or "").strip() or p.short_name or p.name
        return p.id, name
    name = (customer_name or "").strip()
    if not name:
        raise OrderError("customer_required", "请选择客户或填写客户名称")
    return None, name


def generate_order_no(db: Session, tenant_id: int) -> str:
    today = date.today().strftime("%y%m%d")
    prefix = today
    existing = db.scalars(
        select(Order).where(Order.tenant_id == tenant_id, Order.order_no.like(f"{prefix}%"))
    ).all()
    seq = len(existing) + 1
    return f"{prefix}{seq:02d}"


def create_order(
    db: Session,
    tenant_id: int,
    payload: OrderCreate,
    created_by: int | None,
    *,
    sales_order_id: int | None = None,
    sales_order_line_id: int | None = None,
    is_bridge: bool = False,
    commit: bool = True,
) -> Order:
    if not payload.items:
        raise OrderError("empty_items", "订单明细不能为空")

    product = db.get(OwnProduct, payload.own_product_id)
    if not product or product.tenant_id != tenant_id or not product.is_active:
        raise OrderError("product_not_found", "产品不存在或未启用")

    total_qty = sum(i.qty for i in payload.items)
    order_no = payload.order_no or generate_order_no(db, tenant_id)

    exists = db.scalar(select(Order).where(Order.tenant_id == tenant_id, Order.order_no == order_no))
    if exists:
        raise OrderError("duplicate_order_no", f"订单号已存在: {order_no}")

    labors = list(
        db.scalars(
            select(OwnProductLabor)
            .where(
                OwnProductLabor.tenant_id == tenant_id,
                OwnProductLabor.own_product_id == payload.own_product_id,
                OwnProductLabor.process_id.is_not(None),
            )
            .order_by(OwnProductLabor.sort_order, OwnProductLabor.id)
        ).all()
    )
    if not labors:
        raise OrderError("no_route", "该产品未配置工序报价")

    labors = order_labors_for_route(db, tenant_id, payload.own_product_id, labors=labors)
    cust_id, cust_name = _resolve_customer(
        db,
        tenant_id,
        customer_id=getattr(payload, "customer_id", None),
        customer_name=payload.customer_name,
    )

    unit_price = getattr(payload, "unit_price", None)
    if unit_price is None:
        if cust_id:
            q = db.scalar(
                select(OwnProductQuote).where(
                    OwnProductQuote.tenant_id == tenant_id,
                    OwnProductQuote.own_product_id == payload.own_product_id,
                    OwnProductQuote.partner_id == cust_id,
                )
            )
            if q and q.quote_price is not None:
                unit_price = q.quote_price
        if unit_price is None:
            unit_price = product.quote_price
    if unit_price is not None:
        unit_price = Decimal(unit_price).quantize(Decimal("0.01"))

    is_rush = bool(getattr(payload, "is_rush", False))
    rush_reason = (getattr(payload, "rush_reason", None) or None)
    if rush_reason is not None:
        rush_reason = str(rush_reason).strip() or None

    notes = payload.notes
    if is_bridge:
        note = (notes or "").strip()
        if note and not note.startswith("[桥接]"):
            notes = f"[桥接] {note}"
        elif not note:
            notes = "[桥接]"

    order = Order(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_id=cust_id,
        customer_name=cust_name,
        own_product_id=payload.own_product_id,
        style_id=payload.own_product_id,  # 旧库 style_id NOT NULL 兼容
        total_qty=total_qty,
        delivery_date=payload.delivery_date,
        status=OrderStatus.confirmed,
        created_by=created_by,
        notes=notes,
        unit_price=unit_price,
        other_cost_amount=getattr(payload, "other_cost_amount", None),
        is_rush=is_rush,
        rush_reason=rush_reason if is_rush else None,
        rushed_at=datetime.utcnow() if is_rush else None,
        sales_order_id=sales_order_id,
        sales_order_line_id=sales_order_line_id,
        is_bridge=bool(is_bridge),
    )
    db.add(order)
    db.flush()

    for item in payload.items:
        db.add(
            OrderItem(
                tenant_id=tenant_id,
                order_id=order.id,
                color_id=item.color_id,
                size_id=item.size_id,
                qty=item.qty,
                completed_qty=0,
                shipped_qty=0,
            )
        )

    for labor in labors:
        process = db.get(ProcessDefinition, labor.process_id)
        if not process:
            continue
        db.add(
            OrderProcess(
                tenant_id=tenant_id,
                order_id=order.id,
                process_id=process.id,
                process_name=labor.process_name or process.name,
                process_type=process.type,
                part_id=getattr(labor, "part_id", None),
                segment_id=process.segment_id,  # 工序段重构 7.1：从工序继承段快照
                plan_qty=total_qty,
                completed_qty=0,
                defect_qty=0,
                rework_qty=0,
                status=OrderProcessStatus.pending,
                end_date=payload.delivery_date,
            )
        )

    db.flush()

    from app.services.material_service import ensure_material_snapshot

    ensure_material_snapshot(db, tenant_id, order)
    if commit:
        db.commit()
    else:
        db.flush()
    return get_order(db, tenant_id, order.id)


def _item_key(color_id: int | None, size_id: int) -> tuple:
    return (color_id, size_id)


def update_order(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    status: str | None = None,
    customer_id: int | None = None,
    customer_name: str | None = None,
    delivery_date: date | None = None,
    notes: str | None = None,
    items: list[OrderItemIn] | None = None,
    set_customer_id: bool = False,
    set_customer_name: bool | None = None,
    unit_price: Decimal | None = None,
    other_cost_amount: Decimal | None = None,
    set_unit_price: bool = False,
    set_other_cost_amount: bool = False,
    is_rush: bool | None = None,
    rush_reason: str | None = None,
    set_rush_reason: bool = False,
    changed_by: int | None = None,
) -> Order:
    order = get_order(db, tenant_id, order_id)
    if order.status == OrderStatus.cancelled:
        raise OrderError("cancelled", "已取消订单不可修改")

    from app.services.order_change_service import capture_order_snapshot, record_order_change_if_needed

    change_snapshot_before = capture_order_snapshot(db, tenant_id, order)

    if status is not None:
        if status not in OrderStatus.__members__:
            raise OrderError("invalid_status", f"无效状态：{status}")
        if status == OrderStatus.completed.value or status == "completed":
            from app.services.finance_service import order_has_open_receivable

            if order_has_open_receivable(db, tenant_id, order_id):
                raise OrderError("open_receivable", "尚有未收应收，不能标为已完成")
        prev_status = order.status
        order.status = OrderStatus(status)
        if (
            order.status == OrderStatus.cancelled
            and prev_status != OrderStatus.cancelled
        ):
            from app.services.material_service import release_unused_arrived_to_pool

            release_unused_arrived_to_pool(
                db,
                tenant_id,
                order,
                user_id=None,
                note=f"订单取消释放未发占用",
            )

    # 兼容直接传 customer_name=... 的旧调用；API 可显式传 set_customer_name
    do_set_name = customer_name is not None if set_customer_name is None else set_customer_name
    if set_customer_id or do_set_name:
        if set_customer_id:
            new_id, new_name = _resolve_customer(
                db,
                tenant_id,
                customer_id=customer_id,
                customer_name=customer_name if do_set_name else None,
            )
            order.customer_id = new_id
            order.customer_name = new_name
        elif do_set_name:
            name = (customer_name or "").strip()
            if not name:
                raise OrderError("customer_required", "请填写客户名称")
            order.customer_name = name
    if delivery_date is not None:
        order.delivery_date = delivery_date
        for p in order.processes:
            p.end_date = delivery_date
    if notes is not None:
        order.notes = notes
    if set_unit_price:
        order.unit_price = (
            None if unit_price is None else Decimal(unit_price).quantize(Decimal("0.01"))
        )
    if set_other_cost_amount:
        order.other_cost_amount = other_cost_amount

    if is_rush is not None:
        was_rush = bool(getattr(order, "is_rush", False))
        order.is_rush = bool(is_rush)
        if order.is_rush and not was_rush:
            order.rushed_at = datetime.utcnow()
        if not order.is_rush:
            order.rush_reason = None
            order.rushed_at = None
    if set_rush_reason:
        reason = (rush_reason or "").strip() or None
        if getattr(order, "is_rush", False):
            order.rush_reason = reason
        else:
            order.rush_reason = None

    if items is not None:
        if not items:
            raise OrderError("empty_items", "订单明细不能为空")
        if order.status == OrderStatus.completed:
            raise OrderError("completed", "已完成订单不可改明细，请先改回生产中")

        merged: dict[tuple, int] = {}
        for it in items:
            key = _item_key(it.color_id, it.size_id)
            merged[key] = merged.get(key, 0) + int(it.qty)

        existing = {(i.color_id, i.size_id): i for i in order.items}
        for key, row in existing.items():
            done = int(row.completed_qty or 0)
            if key not in merged:
                if done > 0:
                    raise OrderError(
                        "item_has_progress",
                        f"色码已有完成量 {done}，不能删除该明细",
                    )
            elif merged[key] < done:
                raise OrderError(
                    "qty_below_completed",
                    f"计划数量不能低于已完成 {done}",
                )

        for key, qty in merged.items():
            if key in existing:
                existing[key].qty = qty
            else:
                color_id, size_id = key
                db.add(
                    OrderItem(
                        tenant_id=tenant_id,
                        order_id=order.id,
                        color_id=color_id,
                        size_id=size_id,
                        qty=qty,
                        completed_qty=0,
                    )
                )

        for key, row in list(existing.items()):
            if key not in merged and int(row.completed_qty or 0) == 0:
                db.delete(row)

        db.flush()
        total_qty = sum(merged.values())
        order.total_qty = total_qty
        for p in order.processes:
            p.plan_qty = total_qty
            if total_qty > 0 and p.completed_qty >= total_qty:
                p.status = OrderProcessStatus.completed
            elif p.completed_qty > 0:
                p.status = OrderProcessStatus.in_progress
                p.actual_end = None
            else:
                p.status = OrderProcessStatus.pending
                p.actual_end = None
        from app.services.material_service import sync_requirements_after_qty_change

        sync_requirements_after_qty_change(db, tenant_id, order)

    record_order_change_if_needed(
        db, tenant_id, order, change_snapshot_before, changed_by=changed_by
    )

    db.commit()
    return get_order(db, tenant_id, order.id)


def _size_adjust_names(db: Session, tenant_id: int, keys: list[tuple]) -> tuple[dict, dict]:
    color_ids = {k[0] for k in keys if k[0]}
    size_ids = {k[1] for k in keys if k[1]}
    colors: dict[int, str] = {}
    sizes: dict[int, str] = {}
    if color_ids:
        for c in db.scalars(select(Color).where(Color.id.in_(color_ids))).all():
            colors[c.id] = c.name
    if size_ids:
        for s in db.scalars(select(Size).where(Size.id.in_(size_ids))).all():
            sizes[s.id] = s.size_value
    return colors, sizes


def _format_size_adjust_summary(diff_rows: list[dict], note: str | None, mode: str) -> str:
    changed = [r for r in diff_rows if r["delta_qty"] != 0]
    mode_label = "改码" if mode == "replace" else "补码/改码"
    if changed:
        detail = "；".join(
            f"{r['color_name'] or ''}{r['size_value'] or r['size_id']} "
            f"{r['before_qty']}→{r['after_qty']}({r['delta_qty']:+d})"
            for r in changed
        )
    else:
        detail = "数量未变化"
    text = f"[{mode_label}] {detail}"
    if note:
        text = f"{text}｜备注：{note}"
    return text


def adjust_order_sizes(
    db: Session,
    tenant_id: int,
    order_id: int,
    *,
    items: list[SizeAdjustItemIn],
    mode: str = "delta",
    note: str | None = None,
    user_id: int | None = None,
    dry_run: bool = False,
) -> dict:
    """B2e 补码/改码/尾数向导：调整指定色码计划数量，重算材料需求，标注对发货单的影响。

    - mode="replace"：qty 为该色码目标计划数（绝对值）
    - mode="delta"：qty 为变化量（补码为正，减码为负）
    - dry_run=True：只计算差异与拦截项，不落库、不触发材料重算
    """
    if mode not in ("replace", "delta"):
        raise OrderError("invalid_mode", f"无效模式：{mode}")
    if not items:
        raise OrderError("empty_items", "调整明细不能为空")

    order = get_order(db, tenant_id, order_id)
    if order.status == OrderStatus.cancelled:
        raise OrderError("cancelled", "已取消订单不可调整尺码")
    if order.status == OrderStatus.completed:
        raise OrderError("completed", "已完成订单不可调整尺码，请先改回生产中")

    # B2c 变更留痕：若已落地则记录版本（本函数不改交期，仅 qty 维度），否则回退为订单备注追加
    try:
        from app.services.order_change_service import (
            capture_order_snapshot,
            record_order_change_if_needed,
        )
    except ImportError:
        capture_order_snapshot = None
        record_order_change_if_needed = None
    change_snapshot_before = (
        capture_order_snapshot(db, tenant_id, order) if capture_order_snapshot and not dry_run else None
    )

    merged: dict[tuple, int] = {}
    for it in items:
        key = _item_key(it.color_id, it.size_id)
        if mode == "replace":
            if key in merged and merged[key] != int(it.qty):
                raise OrderError("duplicate_item", "同一色码在本次调整中出现多次且数量不一致")
            merged[key] = int(it.qty)
        else:
            merged[key] = merged.get(key, 0) + int(it.qty)

    existing = {(i.color_id, i.size_id): i for i in order.items}
    colors, sizes = _size_adjust_names(db, tenant_id, list(merged.keys()))

    diff_rows: list[dict] = []
    for key, qty in merged.items():
        color_id, size_id = key
        row = existing.get(key)
        before_qty = int(row.qty) if row else 0
        before_completed = int(row.completed_qty or 0) if row else 0
        before_shipped = int(getattr(row, "shipped_qty", 0) or 0) if row else 0
        after_qty = qty if mode == "replace" else before_qty + qty
        if after_qty < 0:
            raise OrderError(
                "negative_qty",
                f"{colors.get(color_id) or ''}{sizes.get(size_id) or size_id} 调整后数量不能为负",
            )
        delta_qty = after_qty - before_qty
        diff_rows.append(
            {
                "color_id": color_id,
                "color_name": colors.get(color_id),
                "size_id": size_id,
                "size_value": sizes.get(size_id),
                "before_qty": before_qty,
                "after_qty": after_qty,
                "delta_qty": delta_qty,
                "completed_qty": before_completed,
                "shipped_qty": before_shipped,
                "is_new": row is None,
                "below_completed": after_qty < before_completed,
                "over_shipped": after_qty < before_shipped,
                "delivery_impact": before_shipped > 0 and delta_qty != 0,
            }
        )

    blocking = [r for r in diff_rows if r["below_completed"]]
    total_before = order.total_qty
    total_after = total_before + sum(r["delta_qty"] for r in diff_rows)
    has_delivery_impact = any(r["delivery_impact"] for r in diff_rows)

    if dry_run:
        return {
            "dry_run": True,
            "order_id": order.id,
            "order_no": order.order_no,
            "mode": mode,
            "total_qty_before": total_before,
            "total_qty_after": total_after,
            "items": diff_rows,
            "has_blocking": bool(blocking),
            "has_delivery_impact": has_delivery_impact,
        }

    if blocking:
        names = "；".join(
            f"{r['color_name'] or ''}{r['size_value'] or r['size_id']}" for r in blocking
        )
        raise OrderError("qty_below_completed", f"以下色码计划数量不能低于已完成：{names}")

    for r in diff_rows:
        key = (r["color_id"], r["size_id"])
        row = existing.get(key)
        if row:
            if (
                r["after_qty"] == 0
                and int(row.completed_qty or 0) == 0
                and int(getattr(row, "shipped_qty", 0) or 0) == 0
            ):
                db.delete(row)
            else:
                row.qty = r["after_qty"]
        elif r["after_qty"] > 0:
            db.add(
                OrderItem(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    color_id=r["color_id"],
                    size_id=r["size_id"],
                    qty=r["after_qty"],
                    completed_qty=0,
                )
            )

    db.flush()
    order.total_qty = total_after
    for p in order.processes:
        p.plan_qty = total_after
        if total_after > 0 and p.completed_qty >= total_after:
            p.status = OrderProcessStatus.completed
        elif p.completed_qty > 0:
            p.status = OrderProcessStatus.in_progress
            p.actual_end = None
        else:
            p.status = OrderProcessStatus.pending
            p.actual_end = None

    from app.services.material_service import sync_requirements_after_qty_change

    sync_result = sync_requirements_after_qty_change(db, tenant_id, order, user_id=user_id)

    change_log = None
    if record_order_change_if_needed is not None and change_snapshot_before is not None:
        change_log = record_order_change_if_needed(
            db, tenant_id, order, change_snapshot_before, changed_by=user_id
        )
        if change_log is not None and note:
            change_log.summary = f"{change_log.summary}｜备注：{note}"
        change_log_id = change_log.id if change_log else None
        change_logged = change_log is not None
        summary = change_log.summary if change_log else _format_size_adjust_summary(diff_rows, note, mode)
    else:
        # B2c OrderChangeLog 尚未落地：回退为订单备注追加
        summary = _format_size_adjust_summary(diff_rows, note, mode)
        stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        line = f"[{stamp}] {summary}"
        order.notes = f"{order.notes}\n{line}" if order.notes else line
        change_log_id = None
        change_logged = False

    db.commit()
    return {
        "dry_run": False,
        "order_id": order.id,
        "order_no": order.order_no,
        "mode": mode,
        "total_qty_before": total_before,
        "total_qty_after": total_after,
        "items": diff_rows,
        "has_blocking": False,
        "has_delivery_impact": has_delivery_impact,
        "released": sync_result.get("released", []),
        "requirement_count": sync_result.get("requirement_count", 0),
        "change_log_id": change_log_id,
        "change_logged": change_logged,
        "summary": summary,
    }


def import_orders_csv(db: Session, tenant_id: int, csv_text: str, created_by: int | None) -> dict:
    """CSV 批量建单。同订单号多行合并为一条订单的多色码明细。

    表头：订单号,客户,产品编号,交期,颜色,尺码,数量,备注
    （兼容旧表头「款号」）
    """
    import csv
    import io
    from datetime import datetime as dt

    text = (csv_text or "").lstrip("\ufeff").strip()
    if not text:
        raise OrderError("empty_csv", "CSV 内容为空")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise OrderError("bad_csv", "CSV 缺少表头")

    def _col(*names: str) -> str | None:
        for n in names:
            for h in reader.fieldnames or []:
                if h and h.strip() == n:
                    return h
        return None

    c_order = _col("订单号", "order_no")
    c_customer = _col("客户", "customer_name", "客户名")
    c_product = _col("产品编号", "product_code", "款号", "style_code", "款式编码")
    c_delivery = _col("交期", "delivery_date")
    c_color = _col("颜色", "color", "color_name")
    c_size = _col("尺码", "size", "size_value")
    c_qty = _col("数量", "qty")
    c_notes = _col("备注", "notes")

    required = {
        "客户": c_customer,
        "产品编号": c_product,
        "尺码": c_size,
        "数量": c_qty,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise OrderError("bad_csv", f"CSV 缺少列：{', '.join(missing)}")

    products = {
        p.product_code: p
        for p in db.scalars(
            select(OwnProduct).where(OwnProduct.tenant_id == tenant_id, OwnProduct.is_active.is_(True))
        ).all()
    }
    colors = {c.name: c for c in db.scalars(select(Color).where(Color.tenant_id == tenant_id)).all()}
    sizes = {s.size_value: s for s in db.scalars(select(Size).where(Size.tenant_id == tenant_id)).all()}

    groups: dict[str, dict] = {}
    errors: list[str] = []
    conflict_keys: set[str] = set()
    row_no = 1
    for raw in reader:
        row_no += 1
        order_no = (raw.get(c_order) or "").strip() if c_order else ""
        customer = (raw.get(c_customer) or "").strip()
        product_code = (raw.get(c_product) or "").strip()
        size_value = (raw.get(c_size) or "").strip()
        color_name = (raw.get(c_color) or "").strip() if c_color else ""
        qty_raw = (raw.get(c_qty) or "").strip()
        delivery_raw = (raw.get(c_delivery) or "").strip() if c_delivery else ""
        notes = (raw.get(c_notes) or "").strip() if c_notes else ""

        if not any([order_no, customer, product_code, size_value, qty_raw]):
            continue
        if not customer or not product_code or not size_value or not qty_raw:
            errors.append(f"第{row_no}行：客户/产品编号/尺码/数量不能为空")
            continue
        product = products.get(product_code)
        if not product:
            errors.append(f"第{row_no}行：找不到产品编号 {product_code}")
            continue
        size = sizes.get(size_value)
        if not size:
            errors.append(f"第{row_no}行：找不到尺码 {size_value}")
            continue
        color_id = None
        if color_name:
            color = colors.get(color_name)
            if not color:
                errors.append(f"第{row_no}行：找不到颜色 {color_name}")
                continue
            color_id = color.id
        try:
            qty = int(float(qty_raw))
        except ValueError:
            errors.append(f"第{row_no}行：数量无效 {qty_raw}")
            continue
        if qty <= 0:
            errors.append(f"第{row_no}行：数量须大于 0")
            continue

        delivery = None
        if delivery_raw:
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
                try:
                    delivery = dt.strptime(delivery_raw, fmt).date()
                    break
                except ValueError:
                    continue
            if delivery is None:
                errors.append(f"第{row_no}行：交期格式无效 {delivery_raw}")
                continue

        key = order_no or f"__auto__{row_no}"
        g = groups.get(key)
        if not g:
            groups[key] = {
                "order_no": order_no or None,
                "customer_name": customer,
                "own_product_id": product.id,
                "delivery_date": delivery,
                "notes": notes or None,
                "items": [],
            }
            g = groups[key]
        else:
            if g["customer_name"] != customer or g["own_product_id"] != product.id:
                errors.append(f"第{row_no}行：同订单号 {order_no} 的客户/产品不一致")
                conflict_keys.add(key)
                continue
            if notes and not g["notes"]:
                g["notes"] = notes
            if delivery and not g["delivery_date"]:
                g["delivery_date"] = delivery
        g["items"].append(OrderItemIn(color_id=color_id, size_id=size.id, qty=qty))

    created: list[str] = []
    skipped: list[str] = []
    for key, g in groups.items():
        if key in conflict_keys:
            continue
        order_no = g["order_no"]
        if order_no and db.scalar(select(Order).where(Order.tenant_id == tenant_id, Order.order_no == order_no)):
            skipped.append(order_no)
            continue
        try:
            order = create_order(
                db,
                tenant_id,
                OrderCreate(
                    order_no=order_no,
                    customer_name=g["customer_name"],
                    own_product_id=g["own_product_id"],
                    delivery_date=g["delivery_date"],
                    notes=g["notes"],
                    items=g["items"],
                ),
                created_by=created_by,
            )
            created.append(order.order_no)
        except OrderError as e:
            errors.append(f"订单 {order_no or '(自动)'}：{e.message}")

    return {
        "created": created,
        "created_count": len(created),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "errors": errors,
        "message": (
            f"导入完成：新建 {len(created)} 单"
            + (f"，跳过已存在 {len(skipped)} 单" if skipped else "")
            + (f"，错误 {len(errors)} 条" if errors else "")
        ),
    }


def import_template_csv() -> str:
    return (
        "\ufeff订单号,客户,产品编号,交期,颜色,尺码,数量,备注\n"
        "230801,陈姐,A款,2026-08-10,红,37,200,示例可删\n"
        "230801,陈姐,A款,2026-08-10,红,38,200,\n"
        "230802,李姐,A款,2026-08-12,黑,39,100,\n"
    )


def get_order(db: Session, tenant_id: int, order_id: int) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items), selectinload(Order.processes))
    )
    if not order:
        raise OrderError("not_found", "订单不存在")
    return order


def list_orders(
    db: Session,
    tenant_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
    order_no: str | None = None,
    customer_id: int | None = None,
    customer_keyword: str | None = None,
    own_product_id: int | None = None,
    status: str | None = None,
    delivery_date_from: date | None = None,
    delivery_date_to: date | None = None,
    kit_ok: bool | None = None,
    is_rush: bool | None = None,
    sales_order_id: int | None = None,
    sales_order_no: str | None = None,
    q: str | None = None,
    order_ids: set[int] | list[int] | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> tuple[list[Order], int]:
    from app.schemas.common import normalize_page

    page, page_size, offset = normalize_page(page, page_size)
    base = select(Order).where(Order.tenant_id == tenant_id)

    if order_ids is not None:
        ids = list(order_ids) if not isinstance(order_ids, list) else order_ids
        if not ids:
            return [], 0
        base = base.where(Order.id.in_(ids))

    if order_no:
        base = base.where(Order.order_no.ilike(f"%{order_no.strip()}%"))
    if customer_id:
        base = base.where(Order.customer_id == customer_id)
    if customer_keyword:
        kw = customer_keyword.strip()
        if kw:
            base = base.where(Order.customer_name.ilike(f"%{kw}%"))
    if own_product_id:
        base = base.where(Order.own_product_id == own_product_id)
    if status:
        if status not in OrderStatus.__members__:
            raise OrderError("invalid_status", f"无效状态：{status}")
        base = base.where(Order.status == OrderStatus(status))
    if delivery_date_from:
        base = base.where(Order.delivery_date >= delivery_date_from)
    if delivery_date_to:
        base = base.where(Order.delivery_date <= delivery_date_to)
    if is_rush is not None:
        base = base.where(Order.is_rush.is_(bool(is_rush)))
    if sales_order_id:
        base = base.where(Order.sales_order_id == sales_order_id)
    if sales_order_no and sales_order_no.strip():
        so = db.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == tenant_id,
                SalesOrder.order_no == sales_order_no.strip(),
            )
        )
        if so:
            base = base.where(Order.sales_order_id == so.id)
        else:
            base = base.where(Order.id == -1)
    if q:
        keyword = q.strip()
        if keyword:
            base = base.where(
                (Order.order_no.ilike(f"%{keyword}%")) | (Order.customer_name.ilike(f"%{keyword}%"))
            )

    # 齐套筛选：与列表徽章 / 缺料 / 看板同一套池承诺算法
    if kit_ok is not None:
        from app.services.material_service import order_ids_matching_kit

        matched = order_ids_matching_kit(db, tenant_id, kit_ok=bool(kit_ok))
        if matched:
            base = base.where(Order.id.in_(list(matched)))
        else:
            base = base.where(Order.id == -1)

    sb = (sort_by or "").strip()
    asc = (sort_order or "desc").strip().lower() == "asc"
    if sb and sb not in ORDER_SORT_FIELDS:
        raise OrderError("invalid_sort", f"不支持的排序字段：{sb}")

    # 排序可能需要关联产品/销售单
    if sb == "product_code":
        base = base.outerjoin(OwnProduct, Order.own_product_id == OwnProduct.id)
    elif sb == "sales_order_no":
        base = base.outerjoin(SalesOrder, Order.sales_order_id == SalesOrder.id)

    total = db.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0

    order_clauses = [Order.is_rush.desc()]
    if sb == "product_code":
        order_clauses.extend(_order_nulls_last(OwnProduct.product_code, asc=asc))
    elif sb == "sales_order_no":
        order_clauses.extend(_order_nulls_last(SalesOrder.order_no, asc=asc))
    elif sb in ("delivery_date", "created_at"):
        order_clauses.extend(_order_nulls_last(ORDER_SORT_FIELDS[sb], asc=asc))
    elif sb:
        col = ORDER_SORT_FIELDS[sb]
        order_clauses.append(col.asc() if asc else col.desc())
    order_clauses.append(Order.id.desc())

    rows = list(
        db.scalars(
            base.options(selectinload(Order.items), selectinload(Order.processes))
            .order_by(*order_clauses)
            .offset(offset)
            .limit(page_size)
        ).all()
    )
    return rows, int(total)


def count_orders_by_status(
    db: Session,
    tenant_id: int,
    *,
    order_ids: set[int] | list[int] | None = None,
) -> dict:
    """按生产单状态统计数量（与列表状态标签一致）。"""
    base = select(Order.status, func.count()).where(Order.tenant_id == tenant_id)
    if order_ids is not None:
        ids = list(order_ids) if not isinstance(order_ids, list) else order_ids
        if not ids:
            return {"total": 0, "by_status": {k: 0 for k in ORDER_STATUS_STAT_KEYS}}
        base = base.where(Order.id.in_(ids))
    base = base.group_by(Order.status)
    counts = {k: 0 for k in ORDER_STATUS_STAT_KEYS}
    total = 0
    for status, n in db.execute(base).all():
        key = status.value if hasattr(status, "value") else str(status)
        n_int = int(n or 0)
        total += n_int
        counts[key] = n_int
    return {"total": total, "by_status": counts}


def get_order_by_no(db: Session, tenant_id: int, order_no: str) -> Order | None:
    return db.scalar(
        select(Order)
        .where(Order.tenant_id == tenant_id, Order.order_no == order_no)
        .options(selectinload(Order.items), selectinload(Order.processes))
    )


def get_labor_unit_price(
    db: Session, tenant_id: int, own_product_id: int, process_id: int
) -> Decimal | None:
    labor = db.scalar(
        select(OwnProductLabor).where(
            OwnProductLabor.tenant_id == tenant_id,
            OwnProductLabor.own_product_id == own_product_id,
            OwnProductLabor.process_id == process_id,
        )
    )
    if not labor:
        return None
    return Decimal(labor.unit_price)
