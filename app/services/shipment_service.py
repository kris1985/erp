"""出货单与欠交。

B0a 齐码可发口径（禁止用 order_items.completed_qty）：
  可发 = 末道工序该色码有效合格累计 − 已出货；
  确认出货硬拦超可发；草稿仅卡计划欠交。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Color,
    Order,
    OrderItem,
    OwnProduct,
    Partner,
    PartnerContact,
    Receivable,
    ReceivableStatus,
    ReportType,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    SpecExecutionOrder,
    ExecutionAllocation,
    Shipment,
    ShipmentLine,
    ShipmentStatus,
    Size,
    Tenant,
    WorkLog,
    WorkLogStatus,
)
from app.services.material_service import last_order_process


class ShipmentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def sales_order_snapshot(db: Session, order: Order) -> tuple[int | None, str | None]:
    """从生产单取销售单 id + 单号快照（无销售行则空）。"""
    so_id = order.sales_order_id
    if not so_id:
        return None, None
    so = db.get(SalesOrder, so_id)
    return so_id, (so.order_no if so else None)


_SHIP_QUALIFIED_TYPES = (
    ReportType.normal,
    ReportType.group,
    ReportType.supplement,
    ReportType.tail,
)


def generate_shipment_no(db: Session, tenant_id: int) -> str:
    today = date.today().strftime("%y%m%d")
    prefix = f"SH{today}"
    n = db.scalar(
        select(func.count()).select_from(Shipment).where(
            Shipment.tenant_id == tenant_id,
            Shipment.shipment_no.like(f"{prefix}%"),
        )
    )
    return f"{prefix}{(n or 0) + 1:03d}"


def _color_size_names(
    db: Session, rows: list[tuple[int | None, int | None]]
) -> tuple[dict[int, str], dict[int, str]]:
    color_ids = {cid for cid, _ in rows if cid}
    size_ids = {sid for _, sid in rows if sid}
    colors = {
        c.id: c.name
        for c in db.scalars(select(Color).where(Color.id.in_(color_ids))).all()
    } if color_ids else {}
    sizes = {
        s.id: s.size_value
        for s in db.scalars(select(Size).where(Size.id.in_(size_ids))).all()
    } if size_ids else {}
    return colors, sizes


def _primary_partner_contact(
    db: Session, tenant_id: int, partner_id: int
) -> PartnerContact | None:
    return db.scalar(
        select(PartnerContact)
        .where(
            PartnerContact.tenant_id == tenant_id,
            PartnerContact.partner_id == partner_id,
            PartnerContact.is_active.is_(True),
        )
        .order_by(PartnerContact.is_primary.desc(), PartnerContact.sort_order, PartnerContact.id)
        .limit(1)
    )


def _last_process_qualified_by_sku(
    db: Session, tenant_id: int, order_id: int
) -> tuple[object | None, dict[tuple[int | None, int | None], int]]:
    """末道工序按色码汇总有效合格数。返回 (last_process|None, {(color_id,size_id): qty})。"""
    last = last_order_process(db, tenant_id, order_id)
    if not last:
        return None, {}
    rows = db.execute(
        select(WorkLog.color_id, WorkLog.size_id, func.coalesce(func.sum(WorkLog.qualified_qty), 0))
        .where(
            WorkLog.tenant_id == tenant_id,
            WorkLog.order_id == order_id,
            WorkLog.order_process_id == last.id,
            WorkLog.status == WorkLogStatus.valid,
            WorkLog.report_type.in_(_SHIP_QUALIFIED_TYPES),
        )
        .group_by(WorkLog.color_id, WorkLog.size_id)
    ).all()
    out: dict[tuple[int | None, int | None], int] = {}
    for color_id, size_id, qty in rows:
        out[(color_id, size_id)] = int(qty or 0)
    return last, out


def _shippable_for_item(
    it: OrderItem,
    *,
    gate_enabled: bool,
    qualified_map: dict[tuple[int | None, int | None], int],
) -> tuple[int, int, int]:
    """返回 (last_qualified, shippable, short_vs_plan)。"""
    shipped = int(it.shipped_qty or 0)
    plan = int(it.qty or 0)
    backlog = max(0, plan - shipped)
    if not gate_enabled:
        return 0, backlog, 0
    last_q = int(qualified_map.get((it.color_id, it.size_id), 0))
    shippable = max(0, last_q - shipped)
    shippable = min(shippable, backlog)
    short = max(0, plan - last_q)
    return last_q, shippable, short


def _assert_lines_shippable(
    db: Session,
    tenant_id: int,
    order: Order,
    item_qty_pairs: list[tuple[OrderItem, int]],
) -> None:
    """确认出货时齐码闸：禁止超末道可发。无工序时不启用（仅欠交闸）。"""
    last, qmap = _last_process_qualified_by_sku(db, tenant_id, order.id)
    if not last:
        return
    for it, qty in item_qty_pairs:
        if qty <= 0:
            continue
        last_q, shippable, _short = _shippable_for_item(it, gate_enabled=True, qualified_map=qmap)
        if qty > shippable:
            colors, sizes = _color_size_names(db, [(it.color_id, it.size_id)])
            cname = colors.get(it.color_id) if it.color_id else "—"
            sname = sizes.get(it.size_id) if it.size_id else "—"
            raise ShipmentError(
                "not_shippable",
                (
                    f"{cname}/{sname} 齐码不足：末道「{last.process_name}」合格 {last_q}，"
                    f"已出 {int(it.shipped_qty or 0)}，可出 {shippable}，本次 {qty}"
                ),
            )


def _shipment_out(db: Session, sh: Shipment) -> dict:
    order = db.get(Order, sh.order_id) if sh.order_id else None
    tenant = db.get(Tenant, sh.tenant_id)
    product = (
        db.get(OwnProduct, order.own_product_id) if order and order.own_product_id else None
    )
    so_id = sh.sales_order_id
    so_no = sh.sales_order_no
    if so_id is None and order is not None:
        so_id, so_no = sales_order_snapshot(db, order)
    elif so_no is None and so_id is not None:
        so = db.get(SalesOrder, so_id)
        so_no = so.order_no if so else None
    # 无桥接生产单时，从销售行取货号
    if product is None and so_id:
        line = db.scalar(
            select(SalesOrderLine)
            .where(SalesOrderLine.sales_order_id == so_id)
            .order_by(SalesOrderLine.sort_order, SalesOrderLine.id)
            .limit(1)
        )
        if line:
            product = db.get(OwnProduct, line.own_product_id)
    partner = db.get(Partner, sh.customer_id) if sh.customer_id else None
    contact = (
        _primary_partner_contact(db, sh.tenant_id, sh.customer_id) if partner else None
    )
    colors, sizes = _color_size_names(db, [(ln.color_id, ln.size_id) for ln in sh.lines])
    unit_price = sh.unit_price if sh.unit_price is not None else Decimal("0")
    lines = []
    for i, ln in enumerate(sh.lines, start=1):
        qty = int(ln.qty or 0)
        line_amount = (unit_price * qty).quantize(Decimal("0.0001"))
        line_product = product
        soli = getattr(ln, "sales_order_line_item_id", None)
        if soli:
            sitem = db.get(SalesOrderLineItem, soli)
            if sitem:
                sline = db.get(SalesOrderLine, sitem.sales_order_line_id)
                if sline:
                    line_product = db.get(OwnProduct, sline.own_product_id) or line_product
        lines.append(
            {
                "id": ln.id,
                "seq": i,
                "order_item_id": ln.order_item_id,
                "sales_order_line_item_id": soli,
                "product_code": line_product.product_code if line_product else None,
                "color_id": ln.color_id,
                "color_name": colors.get(ln.color_id) if ln.color_id else None,
                "size_id": ln.size_id,
                "size_value": sizes.get(ln.size_id) if ln.size_id else None,
                "qty": qty,
                "unit_price": unit_price,
                "amount": line_amount,
            }
        )
    return {
        "id": sh.id,
        "shipment_no": sh.shipment_no,
        "order_id": sh.order_id,
        "order_no": order.order_no if order else None,
        "sales_order_id": so_id,
        "sales_order_no": so_no,
        "own_product_id": (
            order.own_product_id if order else (product.id if product else None)
        ),
        "product_code": product.product_code if product else None,
        "customer_id": sh.customer_id,
        "customer_name": sh.customer_name,
        "customer_address": partner.address if partner else None,
        "customer_contact_name": contact.name if contact else None,
        "customer_contact_mobile": contact.mobile if contact else None,
        "seller_name": tenant.name if tenant else None,
        "seller_contact_person": tenant.contact_person if tenant else None,
        "seller_contact_mobile": tenant.contact_mobile if tenant else None,
        "seller_address": tenant.address if tenant else None,
        "status": sh.status.value if hasattr(sh.status, "value") else sh.status,
        "ship_date": sh.ship_date,
        "logistics_company": sh.logistics_company,
        "tracking_no": sh.tracking_no,
        "tracking_search_url": (
            f"https://www.baidu.com/s?wd={sh.tracking_no}" if sh.tracking_no else None
        ),
        "unit_price": sh.unit_price,
        "total_qty": sh.total_qty,
        "amount": sh.amount,
        "notes": sh.notes,
        "created_at": sh.created_at,
        "lines": lines,
    }


def get_shipment(db: Session, tenant_id: int, shipment_id: int) -> Shipment:
    sh = db.scalar(
        select(Shipment)
        .where(Shipment.id == shipment_id, Shipment.tenant_id == tenant_id)
        .options(selectinload(Shipment.lines))
    )
    if not sh:
        raise ShipmentError("not_found", "出货单不存在")
    return sh


def list_shipments(
    db: Session,
    tenant_id: int,
    *,
    order_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    q = (
        select(Shipment)
        .where(Shipment.tenant_id == tenant_id)
        .options(selectinload(Shipment.lines))
        .order_by(Shipment.id.desc())
    )
    if order_id:
        q = q.where(Shipment.order_id == order_id)
    if status:
        q = q.where(Shipment.status == ShipmentStatus(status))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.outerjoin(Order, Order.id == Shipment.order_id).where(
            or_(
                Shipment.shipment_no.ilike(like),
                Shipment.customer_name.ilike(like),
                Shipment.sales_order_no.ilike(like),
                Shipment.tracking_no.ilike(like),
                Order.order_no.ilike(like),
            )
        )
    return [_shipment_out(db, sh) for sh in db.scalars(q).unique().all()]


def order_delivery_summary(db: Session, tenant_id: int, order_id: int) -> dict:
    """兼容旧路径：生产单齐码可发（手工出货已改销售口径，保留给旧调用）。"""
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items))
    )
    if not order:
        raise ShipmentError("order_not_found", "订单不存在")
    product = db.get(OwnProduct, order.own_product_id) if order.own_product_id else None
    product_code = product.product_code if product else None
    colors, sizes = _color_size_names(db, [(it.color_id, it.size_id) for it in order.items])
    last, qmap = _last_process_qualified_by_sku(db, tenant_id, order.id)
    gate_enabled = last is not None
    items = []
    shipped_total = 0
    for it in order.items:
        sq = int(it.shipped_qty or 0)
        shipped_total += sq
        last_q, shippable, short = _shippable_for_item(
            it, gate_enabled=gate_enabled, qualified_map=qmap
        )
        items.append(
            {
                "order_item_id": it.id,
                "product_code": product_code,
                "color_id": it.color_id,
                "color_name": colors.get(it.color_id) if it.color_id else None,
                "size_id": it.size_id,
                "size_value": sizes.get(it.size_id) if it.size_id else None,
                "plan_qty": it.qty,
                "shipped_qty": sq,
                "backlog_qty": max(0, it.qty - sq),
                "last_qualified_qty": last_q if gate_enabled else None,
                "shippable_qty": shippable,
                "short_qty": short if gate_enabled else None,
            }
        )
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "own_product_id": order.own_product_id,
        "product_code": product_code,
        "total_qty": order.total_qty,
        "shipped_qty": shipped_total,
        "backlog_qty": max(0, order.total_qty - shipped_total),
        "unit_price": order.unit_price,
        "gate_enabled": gate_enabled,
        "last_process_id": last.id if last else None,
        "last_process_name": last.process_name if last else None,
        "gate_note": (
            f"可出码 = 末道「{last.process_name}」色码合格 − 已出"
            if last
            else "本单无工序，未启用齐码闸（仅卡计划欠交）"
        ),
        "items": items,
    }


def _sales_item_shippable(item: SalesOrderLineItem) -> tuple[int, int, int]:
    """返回 (plan, shipped, shippable)。有 produced 时卡产量；否则仅卡计划欠交。"""
    plan = int(item.qty or 0)
    shipped = int(getattr(item, "shipped_qty", 0) or 0)
    produced = int(getattr(item, "produced_qty", 0) or 0)
    backlog = max(0, plan - shipped)
    if produced > 0:
        shippable = max(0, min(backlog, produced - shipped))
    else:
        shippable = backlog
    return plan, shipped, shippable


def _bridge_for_sales_item(
    db: Session, tenant_id: int, line: SalesOrderLine, item: SalesOrderLineItem
) -> tuple[Order | None, OrderItem | None]:
    """销售色码 → 可选桥接生产单/色码行（双写 shipped）。"""
    order_id = line.production_order_id
    if not order_id and getattr(line, "execution_header_id", None):
        from app.models import ExecutionHeader

        hdr = db.get(ExecutionHeader, line.execution_header_id)
        if hdr and hdr.shop_order_id:
            order_id = hdr.shop_order_id
    if not order_id:
        return None, None
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items))
    )
    if not order:
        return None, None
    color_id = item.color_id if item.color_id is not None else line.color_id
    oi = next(
        (
            it
            for it in order.items
            if int(it.size_id or 0) == int(item.size_id)
            and (
                (it.color_id == color_id)
                or (it.color_id is None and color_id is None)
            )
        ),
        None,
    )
    return order, oi


def sales_delivery_summary(db: Session, tenant_id: int, sales_order_id: int) -> dict:
    """销售单可出汇总：按销售色码；有产量卡产量，否则卡计划欠交。"""
    so = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == sales_order_id, SalesOrder.tenant_id == tenant_id)
        .options(
            selectinload(SalesOrder.lines).selectinload(SalesOrderLine.items),
        )
    )
    if not so:
        raise ShipmentError("sales_order_not_found", "销售单不存在")
    items_out: list[dict] = []
    shipped_total = 0
    plan_total = 0
    unit_price = None
    product_code = None
    for line in sorted(so.lines or [], key=lambda x: (x.sort_order or 0, x.id)):
        if unit_price is None and line.unit_price is not None:
            unit_price = line.unit_price
        product = db.get(OwnProduct, line.own_product_id)
        pcode = product.product_code if product else None
        if product_code is None:
            product_code = pcode
        colors, sizes = _color_size_names(
            db, [(it.color_id or line.color_id, it.size_id) for it in (line.items or [])]
        )
        for it in line.items or []:
            plan, shipped, shippable = _sales_item_shippable(it)
            plan_total += plan
            shipped_total += shipped
            cid = it.color_id if it.color_id is not None else line.color_id
            items_out.append(
                {
                    "sales_order_line_id": line.id,
                    "sales_order_line_item_id": it.id,
                    "product_code": pcode,
                    "color_id": cid,
                    "color_name": colors.get(cid) if cid else None,
                    "size_id": it.size_id,
                    "size_value": sizes.get(it.size_id) if it.size_id else None,
                    "plan_qty": plan,
                    "produced_qty": int(getattr(it, "produced_qty", 0) or 0),
                    "shipped_qty": shipped,
                    "backlog_qty": max(0, plan - shipped),
                    "shippable_qty": shippable,
                    "unit_price": line.unit_price,
                }
            )
    return {
        "sales_order_id": so.id,
        "sales_order_no": so.order_no,
        "customer_id": so.customer_id,
        "customer_name": so.customer_name,
        "product_code": product_code,
        "total_qty": plan_total,
        "shipped_qty": shipped_total,
        "backlog_qty": max(0, plan_total - shipped_total),
        "unit_price": unit_price,
        "gate_enabled": True,
        "gate_note": "可出 = min(计划−已出, 有产量时再卡 产量−已出)；无产量时仅卡计划欠交",
        "items": items_out,
    }


def create_shipment(
    db: Session,
    tenant_id: int,
    *,
    order_id: int | None = None,
    sales_order_id: int | None = None,
    lines: list[dict],
    ship_date: date | None = None,
    logistics_company: str | None = None,
    tracking_no: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
    confirm: bool = False,
) -> dict:
    """新建出货：优先销售单口径；仍接受 order_id 旧路径。"""
    if sales_order_id:
        return _create_shipment_from_sales(
            db,
            tenant_id,
            sales_order_id=sales_order_id,
            lines=lines,
            ship_date=ship_date,
            logistics_company=logistics_company,
            tracking_no=tracking_no,
            notes=notes,
            user_id=user_id,
            confirm=confirm,
        )
    if order_id:
        return _create_shipment_from_order(
            db,
            tenant_id,
            order_id=order_id,
            lines=lines,
            ship_date=ship_date,
            logistics_company=logistics_company,
            tracking_no=tracking_no,
            notes=notes,
            user_id=user_id,
            confirm=confirm,
        )
    raise ShipmentError("missing_subject", "请选择销售单（或兼容传入生产单）")


def _create_shipment_from_sales(
    db: Session,
    tenant_id: int,
    *,
    sales_order_id: int,
    lines: list[dict],
    ship_date: date | None = None,
    logistics_company: str | None = None,
    tracking_no: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
    confirm: bool = False,
) -> dict:
    so = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == sales_order_id, SalesOrder.tenant_id == tenant_id)
        .options(selectinload(SalesOrder.lines).selectinload(SalesOrderLine.items))
    )
    if not so:
        raise ShipmentError("sales_order_not_found", "销售单不存在")
    if not lines:
        raise ShipmentError("empty", "出货明细不能为空")

    item_index: dict[int, tuple[SalesOrderLine, SalesOrderLineItem]] = {}
    for line in so.lines or []:
        for it in line.items or []:
            item_index[it.id] = (line, it)

    total_qty = 0
    built: list[tuple[SalesOrderLine, SalesOrderLineItem, int]] = []
    unit_price = Decimal("0")
    for row in lines:
        sid = int(row.get("sales_order_line_item_id") or 0)
        qty = int(row.get("qty") or 0)
        if sid <= 0 or qty <= 0:
            continue
        pair = item_index.get(sid)
        if not pair:
            raise ShipmentError("item_not_found", f"销售色码行不存在：{sid}")
        line, item = pair
        _plan, _shipped, shippable = _sales_item_shippable(item)
        if qty > shippable:
            raise ShipmentError("over_plan", f"色码超出可出数量（剩余 {shippable}）")
        if line.unit_price is not None:
            unit_price = line.unit_price
        total_qty += qty
        built.append((line, item, qty))
    if total_qty <= 0:
        raise ShipmentError("empty", "出货数量须大于 0")

    # 桥接：同单尽量取第一条能解析到的生产单（双写）
    bridge_order: Order | None = None
    for line, item, _qty in built:
        o, _oi = _bridge_for_sales_item(db, tenant_id, line, item)
        if o:
            bridge_order = o
            break
        if unit_price == 0 and bridge_order and bridge_order.unit_price is not None:
            unit_price = bridge_order.unit_price

    if unit_price == 0 and bridge_order and bridge_order.unit_price is not None:
        unit_price = bridge_order.unit_price

    sh = Shipment(
        tenant_id=tenant_id,
        shipment_no=generate_shipment_no(db, tenant_id),
        order_id=bridge_order.id if bridge_order else None,
        sales_order_id=so.id,
        sales_order_no=so.order_no,
        customer_id=so.customer_id,
        customer_name=so.customer_name,
        status=ShipmentStatus.draft,
        ship_date=ship_date or date.today(),
        logistics_company=logistics_company,
        tracking_no=tracking_no,
        unit_price=unit_price,
        total_qty=total_qty,
        amount=(unit_price * total_qty).quantize(Decimal("0.0001")),
        notes=notes,
        created_by=user_id,
    )
    db.add(sh)
    db.flush()
    for line, item, qty in built:
        _o, oi = _bridge_for_sales_item(db, tenant_id, line, item)
        color_id = item.color_id if item.color_id is not None else line.color_id
        db.add(
            ShipmentLine(
                tenant_id=tenant_id,
                shipment_id=sh.id,
                sales_order_line_item_id=item.id,
                order_item_id=oi.id if oi else None,
                color_id=color_id,
                size_id=item.size_id,
                qty=qty,
            )
        )
    db.flush()
    if confirm:
        return confirm_shipment(db, tenant_id, sh.id)
    db.commit()
    return _shipment_out(db, get_shipment(db, tenant_id, sh.id))


def _create_shipment_from_order(
    db: Session,
    tenant_id: int,
    *,
    order_id: int,
    lines: list[dict],
    ship_date: date | None = None,
    logistics_company: str | None = None,
    tracking_no: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
    confirm: bool = False,
) -> dict:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items))
    )
    if not order:
        raise ShipmentError("order_not_found", "订单不存在")
    if not lines:
        raise ShipmentError("empty", "出货明细不能为空")

    unit_price = order.unit_price if order.unit_price is not None else Decimal("0")
    item_map = {it.id: it for it in order.items}
    total_qty = 0
    built: list[tuple[OrderItem, int]] = []
    for row in lines:
        it = item_map.get(row["order_item_id"])
        if not it:
            raise ShipmentError("item_not_found", "订单明细不存在")
        qty = int(row["qty"])
        if qty <= 0:
            continue
        backlog = it.qty - int(it.shipped_qty or 0)
        if qty > backlog:
            raise ShipmentError("over_plan", f"色码超出可出数量（剩余 {backlog}）")
        total_qty += qty
        built.append((it, qty))
    if total_qty <= 0:
        raise ShipmentError("empty", "出货数量须大于 0")

    so_id, so_no = sales_order_snapshot(db, order)
    sh = Shipment(
        tenant_id=tenant_id,
        shipment_no=generate_shipment_no(db, tenant_id),
        order_id=order.id,
        sales_order_id=so_id,
        sales_order_no=so_no,
        customer_id=order.customer_id,
        customer_name=order.customer_name,
        status=ShipmentStatus.draft,
        ship_date=ship_date or date.today(),
        logistics_company=logistics_company,
        tracking_no=tracking_no,
        unit_price=unit_price,
        total_qty=total_qty,
        amount=(unit_price * total_qty).quantize(Decimal("0.0001")),
        notes=notes,
        created_by=user_id,
    )
    db.add(sh)
    db.flush()
    for it, qty in built:
        db.add(
            ShipmentLine(
                tenant_id=tenant_id,
                shipment_id=sh.id,
                order_item_id=it.id,
                color_id=it.color_id,
                size_id=it.size_id,
                qty=qty,
            )
        )
    db.flush()
    if confirm:
        return confirm_shipment(db, tenant_id, sh.id)
    db.commit()
    return _shipment_out(db, get_shipment(db, tenant_id, sh.id))


def create_direct_shipments(
    db: Session,
    *,
    tenant_id: int,
    execution: SpecExecutionOrder,
    allocations: list[ExecutionAllocation],
    qtys: list[int],
    user_id: int | None = None,
    note: str | None = None,
) -> list[dict]:
    """按执行单分配创建已确认销售出货单（销售为主；桥接可选双写）。"""
    if len(allocations) != len(qtys):
        raise ShipmentError("invalid_allocation", "直发分配数量不一致")
    order = None
    order_item = None
    if execution.shop_order_id:
        order = db.scalar(
            select(Order)
            .where(Order.id == execution.shop_order_id, Order.tenant_id == tenant_id)
            .options(selectinload(Order.items))
        )
        if order:
            order_item = next(
                (
                    it
                    for it in order.items
                    if it.color_id == execution.color_id and it.size_id == execution.size_id
                ),
                None,
            )

    from app.services.finance_service import create_receivable_for_shipment

    out: list[dict] = []
    for allocation, qty in zip(allocations, qtys):
        qty = int(qty)
        if qty <= 0:
            continue
        so = db.get(SalesOrder, allocation.sales_order_id)
        line = db.get(SalesOrderLine, allocation.sales_order_line_id)
        item = db.get(SalesOrderLineItem, allocation.sales_order_line_item_id)
        if not so or not line or not item or so.tenant_id != tenant_id:
            raise ShipmentError("sales_source_not_found", "直发销售来源不存在")
        if int(item.produced_qty or 0) < qty:
            raise ShipmentError("not_produced", f"销售单 {so.order_no} 精确产量不足")
        if int(item.shipped_qty or 0) + qty > int(item.qty or 0):
            raise ShipmentError("over_plan", f"销售单 {so.order_no} 色码超出可出数量")
        unit_price = line.unit_price if line.unit_price is not None else (
            order.unit_price if order and order.unit_price is not None else Decimal("0")
        )
        sh = Shipment(
            tenant_id=tenant_id,
            shipment_no=generate_shipment_no(db, tenant_id),
            order_id=order.id if order else None,
            sales_order_id=so.id,
            sales_order_no=so.order_no,
            customer_id=so.customer_id,
            customer_name=so.customer_name,
            status=ShipmentStatus.shipped,
            ship_date=date.today(),
            unit_price=unit_price,
            total_qty=qty,
            amount=(unit_price * qty).quantize(Decimal("0.0001")),
            notes=note or f"执行单 {execution.execution_no} 筐直发",
            created_by=user_id,
        )
        db.add(sh)
        db.flush()
        color_id = item.color_id if item.color_id is not None else line.color_id
        db.add(
            ShipmentLine(
                tenant_id=tenant_id,
                shipment_id=sh.id,
                sales_order_line_item_id=item.id,
                order_item_id=order_item.id if order_item else None,
                color_id=color_id if color_id is not None else execution.color_id,
                size_id=item.size_id,
                qty=qty,
            )
        )
        if order_item:
            order_item.shipped_qty = int(order_item.shipped_qty or 0) + qty
        item.shipped_qty = int(item.shipped_qty or 0) + qty
        db.flush()
        create_receivable_for_shipment(db, tenant_id, sh)
        out.append(_shipment_out(db, sh))
        sync_sales_order_after_ship(db, tenant_id, so.id)
    if not out:
        raise ShipmentError("empty", "按分配计算后无可直发数量")
    return out


def sync_sales_order_after_ship(db: Session, tenant_id: int, sales_order_id: int | None) -> None:
    """出货后：色码全出完则产品行/销售单标已完成。"""
    if not sales_order_id:
        return
    so = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == sales_order_id, SalesOrder.tenant_id == tenant_id)
        .options(selectinload(SalesOrder.lines).selectinload(SalesOrderLine.items))
    )
    if not so or so.status in (SalesOrderStatus.cancelled,):
        return
    all_lines_done = True
    any_item = False
    for line in so.lines or []:
        if line.status == SalesOrderLineStatus.cancelled:
            continue
        items = [it for it in (line.items or []) if int(it.qty or 0) > 0]
        if not items:
            all_lines_done = False
            continue
        any_item = True
        line_done = all(
            int(getattr(it, "shipped_qty", 0) or 0) >= int(it.qty or 0) for it in items
        )
        if line_done:
            line.status = SalesOrderLineStatus.completed
        else:
            all_lines_done = False
            # 有出货但未出完：标在产，便于列表不再停在「待确认」
            if any(int(getattr(it, "shipped_qty", 0) or 0) > 0 for it in items):
                if line.status == SalesOrderLineStatus.pending:
                    line.status = SalesOrderLineStatus.in_production
    if any_item and all_lines_done:
        so.status = SalesOrderStatus.completed


def confirm_shipment(db: Session, tenant_id: int, shipment_id: int) -> dict:
    from app.services.finance_service import create_receivable_for_shipment

    sh = get_shipment(db, tenant_id, shipment_id)
    if sh.status != ShipmentStatus.draft:
        raise ShipmentError("invalid_status", "仅草稿可确认出货")

    # 销售色码路径
    sales_pairs: list[tuple[SalesOrderLineItem, int]] = []
    for ln in sh.lines:
        soli = getattr(ln, "sales_order_line_item_id", None)
        if not soli:
            continue
        item = db.get(SalesOrderLineItem, soli)
        if not item or item.tenant_id != tenant_id:
            raise ShipmentError("item_not_found", "销售色码行不存在")
        _plan, _shipped, shippable = _sales_item_shippable(item)
        if int(ln.qty or 0) > shippable:
            raise ShipmentError("over_plan", f"色码超出可出数量（剩余 {shippable}）")
        sales_pairs.append((item, int(ln.qty or 0)))

    order = None
    item_map: dict[int, OrderItem] = {}
    if sh.order_id:
        order = db.scalar(
            select(Order)
            .where(Order.id == sh.order_id)
            .options(selectinload(Order.items))
        )
        if order:
            item_map = {it.id: it for it in order.items}
            for ln in sh.lines:
                if not ln.order_item_id:
                    continue
                it = item_map.get(ln.order_item_id)
                if not it:
                    raise ShipmentError("item_not_found", "订单明细不存在")
                backlog = it.qty - int(it.shipped_qty or 0)
                if ln.qty > backlog:
                    raise ShipmentError("over_plan", f"色码超出可出数量（剩余 {backlog}）")
            order_pairs = [
                (item_map[ln.order_item_id], int(ln.qty or 0))
                for ln in sh.lines
                if ln.order_item_id and ln.order_item_id in item_map
            ]
            if order_pairs:
                _assert_lines_shippable(db, tenant_id, order, order_pairs)

    if not sales_pairs and not item_map:
        raise ShipmentError("empty", "出货明细无效")

    for item, qty in sales_pairs:
        item.shipped_qty = int(getattr(item, "shipped_qty", 0) or 0) + qty
    for ln in sh.lines:
        if not ln.order_item_id:
            continue
        it = item_map.get(ln.order_item_id)
        if it:
            it.shipped_qty = int(it.shipped_qty or 0) + ln.qty

    sh.status = ShipmentStatus.shipped
    if not sh.ship_date:
        sh.ship_date = date.today()
    create_receivable_for_shipment(db, tenant_id, sh)
    sync_sales_order_after_ship(db, tenant_id, sh.sales_order_id)
    try:
        from app.services.packing_service import ensure_shipment_packing_cartons

        ensure_shipment_packing_cartons(db, tenant_id, sh.id)
    except Exception:
        # 箱唛落成失败不阻断出货
        pass
    db.commit()
    return _shipment_out(db, get_shipment(db, tenant_id, sh.id))


def void_shipment(db: Session, tenant_id: int, shipment_id: int) -> dict:
    sh = get_shipment(db, tenant_id, shipment_id)
    if sh.status != ShipmentStatus.shipped:
        raise ShipmentError("invalid_status", "仅已出货单可作废")
    ar = db.scalar(
        select(Receivable).where(
            Receivable.tenant_id == tenant_id,
            Receivable.shipment_id == sh.id,
            Receivable.status != ReceivableStatus.void,
        )
    )
    if ar and (ar.received_amount or 0) > 0:
        raise ShipmentError("has_payment", "应收已核销，请先撤销回款核销再作出货")
    if ar:
        ar.status = ReceivableStatus.void
    for ln in sh.lines:
        soli = getattr(ln, "sales_order_line_item_id", None)
        if soli:
            item = db.get(SalesOrderLineItem, soli)
            if item:
                item.shipped_qty = max(0, int(getattr(item, "shipped_qty", 0) or 0) - int(ln.qty or 0))
    if sh.order_id:
        order = db.scalar(
            select(Order)
            .where(Order.id == sh.order_id)
            .options(selectinload(Order.items))
        )
        if order:
            item_map = {it.id: it for it in order.items}
            for ln in sh.lines:
                it = item_map.get(ln.order_item_id) if ln.order_item_id else None
                if it:
                    it.shipped_qty = max(0, int(it.shipped_qty or 0) - ln.qty)
    sh.status = ShipmentStatus.void
    db.commit()
    return _shipment_out(db, get_shipment(db, tenant_id, sh.id))
