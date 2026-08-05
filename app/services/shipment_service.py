"""出货单与欠交。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Order,
    OrderItem,
    Receivable,
    ReceivableStatus,
    Shipment,
    ShipmentLine,
    ShipmentStatus,
)


class ShipmentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


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


def _shipment_out(db: Session, sh: Shipment) -> dict:
    order = db.get(Order, sh.order_id)
    lines = []
    for ln in sh.lines:
        lines.append(
            {
                "id": ln.id,
                "order_item_id": ln.order_item_id,
                "color_id": ln.color_id,
                "size_id": ln.size_id,
                "qty": ln.qty,
            }
        )
    return {
        "id": sh.id,
        "shipment_no": sh.shipment_no,
        "order_id": sh.order_id,
        "order_no": order.order_no if order else None,
        "customer_id": sh.customer_id,
        "customer_name": sh.customer_name,
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
    items = []
    shipped_total = 0
    for it in order.items:
        sq = int(it.shipped_qty or 0)
        shipped_total += sq
        items.append(
            {
                "order_item_id": it.id,
                "color_id": it.color_id,
                "size_id": it.size_id,
                "plan_qty": it.qty,
                "shipped_qty": sq,
                "backlog_qty": max(0, it.qty - sq),
            }
        )
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "total_qty": order.total_qty,
        "shipped_qty": shipped_total,
        "backlog_qty": max(0, order.total_qty - shipped_total),
        "unit_price": order.unit_price,
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
