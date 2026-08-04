from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import User
from app.schemas.api import OrderCreate, OrderOut, OrderItemOut, OrderProcessOut
from app.schemas.common import ok
from app.services.order_service import OrderError, create_order, get_order, list_orders

router = APIRouter(prefix="/orders", tags=["orders"])


def _serialize(order) -> dict:
    return OrderOut(
        id=order.id,
        order_no=order.order_no,
        customer_name=order.customer_name,
        style_id=order.style_id,
        total_qty=order.total_qty,
        delivery_date=order.delivery_date,
        status=order.status.value if hasattr(order.status, "value") else str(order.status),
        notes=order.notes,
        created_at=order.created_at,
        items=[OrderItemOut.model_validate(i) for i in order.items],
        processes=[
            OrderProcessOut(
                id=p.id,
                process_id=p.process_id,
                process_name=p.process_name,
                plan_qty=p.plan_qty,
                completed_qty=p.completed_qty,
                defect_qty=p.defect_qty,
                status=p.status.value if hasattr(p.status, "value") else str(p.status),
            )
            for p in order.processes
        ],
    ).model_dump()


@router.get("")
def api_list_orders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = list_orders(db, user.tenant_id)
    items = [_serialize(o) for o in rows]
    return ok({"items": items, "total": len(items)})


@router.post("")
def api_create_order(body: OrderCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        order = create_order(db, user.tenant_id, body, created_by=user.id)
    except OrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(_serialize(order))


@router.get("/{order_id}")
def api_get_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        order = get_order(db, user.tenant_id, order_id)
    except OrderError as e:
        raise HTTPException(status_code=404, detail=e.message)
    return ok(_serialize(order))
