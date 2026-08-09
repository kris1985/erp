"""B1a：客供收货台 — 列表 / 登记到货 / 催客户。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CustomerSupplyReceipt,
    Order,
    OrderMaterialRequirement,
    OrderStatus,
    OwnProduct,
    Size,
)
from app.services.material_service import MaterialError, build_kit_context

CHASE_OPEN = "open"
CHASE_CHASED = "chased"
CHASE_CLEARED = "cleared"
CHASE_STATUSES = frozenset({CHASE_OPEN, CHASE_CHASED, CHASE_CLEARED})

OPEN_ORDER_STATUSES = (
    OrderStatus.confirmed,
    OrderStatus.in_progress,
)


def _row_out(db: Session, tenant_id: int, row: OrderMaterialRequirement, order: Order) -> dict:
    ctx = build_kit_context(db, tenant_id, include_shared=False)
    d = ctx.row_dict(row)
    product = db.get(OwnProduct, order.own_product_id) if order.own_product_id else None
    size_value = d.get("size_value")
    if not size_value and row.size_id:
        sz = db.get(Size, row.size_id)
        size_value = sz.size_value if sz else None
    owed = max(Decimal("0"), Decimal(str(d.get("required_qty") or 0)) - Decimal(str(d.get("arrived_qty") or 0)))
    return {
        **d,
        "order_no": order.order_no,
        "customer_name": order.customer_name,
        "customer_id": getattr(order, "customer_id", None),
        "product_code": product.product_code if product else None,
        "is_rush": bool(getattr(order, "is_rush", False)),
        "order_status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "owed_qty": owed,
        "size_value": size_value,
    }


def list_customer_supply(
    db: Session,
    tenant_id: int,
    *,
    order_id: int | None = None,
    order_no: str | None = None,
    chase_status: str | None = None,
    owed_only: bool = False,
    include_closed_orders: bool = False,
) -> list[dict]:
    q = (
        select(OrderMaterialRequirement, Order)
        .join(Order, Order.id == OrderMaterialRequirement.order_id)
        .where(
            OrderMaterialRequirement.tenant_id == tenant_id,
            OrderMaterialRequirement.is_customer_supplied.is_(True),
        )
    )
    if not include_closed_orders:
        q = q.where(Order.status.in_(list(OPEN_ORDER_STATUSES)))
    if order_id:
        q = q.where(Order.id == order_id)
    if order_no and order_no.strip():
        q = q.where(Order.order_no.contains(order_no.strip()))
    if chase_status:
        if chase_status not in CHASE_STATUSES:
            raise MaterialError("invalid_chase", "催办状态无效")
        q = q.where(OrderMaterialRequirement.customer_chase_status == chase_status)
    rows = list(db.execute(q).all())
    out: list[dict] = []
    for row, order in rows:
        item = _row_out(db, tenant_id, row, order)
        if owed_only and float(item.get("owed_qty") or 0) <= 0:
            continue
        out.append(item)
    out.sort(
        key=lambda x: (
            0 if float(x.get("owed_qty") or 0) > 0 else 1,
            0 if x.get("customer_chase_status") == CHASE_CHASED else 1,
            str(x.get("order_no") or ""),
            int(x.get("id") or 0),
        )
    )
    return out


def receive_customer_supply(
    db: Session,
    tenant_id: int,
    req_id: int,
    *,
    qty: Decimal,
    note: str | None = None,
    created_by: int | None = None,
) -> dict:
    if qty is None or Decimal(qty) <= 0:
        raise MaterialError("invalid_qty", "到货数量须大于 0")
    qty = Decimal(qty)
    row = db.get(OrderMaterialRequirement, req_id)
    if not row or row.tenant_id != tenant_id:
        raise MaterialError("not_found", "用料行不存在")
    if not row.is_customer_supplied:
        raise MaterialError("not_customer_supplied", "仅客供料可在此登记到货")
    order = db.get(Order, row.order_id)
    if not order or order.tenant_id != tenant_id:
        raise MaterialError("order_not_found", "生产单不存在")

    row.arrived_qty = (row.arrived_qty or Decimal("0")) + qty
    receipt = CustomerSupplyReceipt(
        tenant_id=tenant_id,
        order_id=order.id,
        requirement_id=row.id,
        qty=qty,
        note=(note or "").strip() or None,
        created_by=created_by,
    )
    db.add(receipt)

    required = row.required_qty or Decimal("0")
    if row.arrived_qty >= required:
        row.customer_chase_status = CHASE_CLEARED
    db.commit()
    db.refresh(row)
    return {
        "receipt_id": receipt.id,
        "line": _row_out(db, tenant_id, row, order),
    }


def chase_customer_supply(
    db: Session,
    tenant_id: int,
    req_id: int,
    *,
    status: str,
    note: str | None = None,
) -> dict:
    if status not in CHASE_STATUSES:
        raise MaterialError("invalid_chase", "催办状态无效")
    row = db.get(OrderMaterialRequirement, req_id)
    if not row or row.tenant_id != tenant_id:
        raise MaterialError("not_found", "用料行不存在")
    if not row.is_customer_supplied:
        raise MaterialError("not_customer_supplied", "仅客供料可催办")
    order = db.get(Order, row.order_id)
    if not order:
        raise MaterialError("order_not_found", "生产单不存在")

    row.customer_chase_status = status
    if note is not None:
        row.customer_chase_note = note.strip() or None
    if status == CHASE_CHASED:
        row.customer_chased_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _row_out(db, tenant_id, row, order)


def list_customer_supply_receipts(
    db: Session, tenant_id: int, req_id: int
) -> list[dict]:
    row = db.get(OrderMaterialRequirement, req_id)
    if not row or row.tenant_id != tenant_id:
        raise MaterialError("not_found", "用料行不存在")
    receipts = db.scalars(
        select(CustomerSupplyReceipt)
        .where(
            CustomerSupplyReceipt.tenant_id == tenant_id,
            CustomerSupplyReceipt.requirement_id == req_id,
        )
        .order_by(CustomerSupplyReceipt.id.desc())
    ).all()
    return [
        {
            "id": r.id,
            "order_id": r.order_id,
            "requirement_id": r.requirement_id,
            "qty": r.qty,
            "note": r.note,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in receipts
    ]
