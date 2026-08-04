from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    PriceType,
    ProcessDefinition,
    StyleProcessRoute,
)
from app.schemas.api import OrderCreate


class OrderError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def generate_order_no(db: Session, tenant_id: int) -> str:
    today = date.today().strftime("%y%m%d")
    prefix = today
    existing = db.scalars(
        select(Order).where(Order.tenant_id == tenant_id, Order.order_no.like(f"{prefix}%"))
    ).all()
    seq = len(existing) + 1
    return f"{prefix}{seq:02d}"


def create_order(db: Session, tenant_id: int, payload: OrderCreate, created_by: int | None) -> Order:
    if not payload.items:
        raise OrderError("empty_items", "订单明细不能为空")

    total_qty = sum(i.qty for i in payload.items)
    order_no = payload.order_no or generate_order_no(db, tenant_id)

    exists = db.scalar(select(Order).where(Order.tenant_id == tenant_id, Order.order_no == order_no))
    if exists:
        raise OrderError("duplicate_order_no", f"订单号已存在: {order_no}")

    routes = db.scalars(
        select(StyleProcessRoute)
        .where(
            StyleProcessRoute.tenant_id == tenant_id,
            StyleProcessRoute.style_id == payload.style_id,
            StyleProcessRoute.price_type == PriceType.normal,
            StyleProcessRoute.is_active.is_(True),
        )
        .order_by(StyleProcessRoute.seq)
    ).all()
    if not routes:
        raise OrderError("no_route", "该款式未配置正常计价工艺路线")

    order = Order(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name=payload.customer_name,
        style_id=payload.style_id,
        total_qty=total_qty,
        delivery_date=payload.delivery_date,
        status=OrderStatus.confirmed,
        created_by=created_by,
        notes=payload.notes,
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
            )
        )

    for route in routes:
        process = db.get(ProcessDefinition, route.process_id)
        if not process:
            continue
        db.add(
            OrderProcess(
                tenant_id=tenant_id,
                order_id=order.id,
                process_id=process.id,
                process_name=process.name,
                process_type=process.type,
                plan_qty=total_qty,
                completed_qty=0,
                defect_qty=0,
                rework_qty=0,
                status=OrderProcessStatus.pending,
                end_date=payload.delivery_date,
            )
        )

    db.commit()
    return get_order(db, tenant_id, order.id)


def get_order(db: Session, tenant_id: int, order_id: int) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items), selectinload(Order.processes))
    )
    if not order:
        raise OrderError("not_found", "订单不存在")
    return order


def list_orders(db: Session, tenant_id: int) -> list[Order]:
    return list(
        db.scalars(
            select(Order)
            .where(Order.tenant_id == tenant_id)
            .options(selectinload(Order.items), selectinload(Order.processes))
            .order_by(Order.id.desc())
        ).all()
    )


def get_order_by_no(db: Session, tenant_id: int, order_no: str) -> Order | None:
    return db.scalar(
        select(Order)
        .where(Order.tenant_id == tenant_id, Order.order_no == order_no)
        .options(selectinload(Order.items), selectinload(Order.processes))
    )
