"""出货单与欠交。

B0a 齐码可发口径（禁止用 order_items.completed_qty）：
  可发 = 末道工序该色码有效合格累计 − 已出货；
  确认出货硬拦超可发；草稿仅卡计划欠交。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
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
    order = db.get(Order, sh.order_id)
    tenant = db.get(Tenant, sh.tenant_id)
    product = (
        db.get(OwnProduct, order.own_product_id) if order and order.own_product_id else None
    )
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
        lines.append(
            {
                "id": ln.id,
                "seq": i,
                "order_item_id": ln.order_item_id,
                "product_code": product.product_code if product else None,
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
        "own_product_id": order.own_product_id if order else None,
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
    return [_shipment_out(db, sh) for sh in db.scalars(q).all()]


def order_delivery_summary(db: Session, tenant_id: int, order_id: int) -> dict:
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
                # B0a：末道合格 / 可出码 / 欠码（非 completed_qty）
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


def create_shipment(
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

    sh = Shipment(
        tenant_id=tenant_id,
        shipment_no=generate_shipment_no(db, tenant_id),
        order_id=order.id,
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


def confirm_shipment(db: Session, tenant_id: int, shipment_id: int) -> dict:
    from app.services.finance_service import create_receivable_for_shipment

    sh = get_shipment(db, tenant_id, shipment_id)
    if sh.status != ShipmentStatus.draft:
        raise ShipmentError("invalid_status", "仅草稿可确认出货")
    order = db.scalar(
        select(Order)
        .where(Order.id == sh.order_id)
        .options(selectinload(Order.items))
    )
    if not order:
        raise ShipmentError("order_not_found", "订单不存在")
    item_map = {it.id: it for it in order.items}
    for ln in sh.lines:
        it = item_map.get(ln.order_item_id)
        if not it:
            raise ShipmentError("item_not_found", "订单明细不存在")
        backlog = it.qty - int(it.shipped_qty or 0)
        if ln.qty > backlog:
            raise ShipmentError("over_plan", f"色码超出可出数量（剩余 {backlog}）")

    _assert_lines_shippable(
        db,
        tenant_id,
        order,
        [
            (item_map[ln.order_item_id], int(ln.qty or 0))
            for ln in sh.lines
            if ln.order_item_id in item_map
        ],
    )

    for ln in sh.lines:
        it = item_map.get(ln.order_item_id)
        if not it:
            continue
        it.shipped_qty = int(it.shipped_qty or 0) + ln.qty

    sh.status = ShipmentStatus.shipped
    if not sh.ship_date:
        sh.ship_date = date.today()
    create_receivable_for_shipment(db, tenant_id, sh)
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
    order = db.scalar(
        select(Order)
        .where(Order.id == sh.order_id)
        .options(selectinload(Order.items))
    )
    if order:
        item_map = {it.id: it for it in order.items}
        for ln in sh.lines:
            it = item_map.get(ln.order_item_id)
            if it:
                it.shipped_qty = max(0, int(it.shipped_qty or 0) - ln.qty)
    sh.status = ShipmentStatus.void
    db.commit()
    return _shipment_out(db, get_shipment(db, tenant_id, sh.id))
