"""销售订单 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import User
from app.schemas.api import (
    SalesOrderCreate,
    SalesOrderLineIn,
    SalesOrderLinesConfirmBatchIn,
    SalesOrderLinesSimulateMrpIn,
    SalesOrderUpdate,
)
from app.schemas.common import normalize_page, ok, page_payload
from app.services.order_service import OrderError
from app.services.sales_order_service import (
    SalesOrderError,
    add_sales_order_line,
    cancel_sales_order,
    confirm_sales_order,
    confirm_sales_order_line,
    confirm_sales_order_lines_batch,
    create_sales_order,
    count_sales_orders_by_status,
    delete_sales_order_line,
    get_sales_order,
    list_sales_order_product_lines,
    list_sales_orders,
    serialize_sales_order,
    simulate_sales_order_lines_mrp,
    update_sales_order,
    update_sales_order_line,
)

router = APIRouter(prefix="/sales-orders", tags=["sales-orders"])


@router.get("")
def api_list_sales_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    customer_id: int | None = None,
    status: str | None = None,
    product_code: str | None = None,
    view: str = Query("split", description="split|product"),
    sort_by: str | None = Query(
        None,
        description="order_no|customer_name|ordered_at|line_no|product_code|customer_sku|total_qty|unit_price|line_total|delivery_date|id",
    ),
    sort_order: str | None = Query(None, description="asc|desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    page, page_size, _ = normalize_page(page, page_size)
    try:
        if view == "product":
            items, total = list_sales_order_product_lines(
                db,
                user.tenant_id,
                page=page,
                page_size=page_size,
                status=status,
                product_code=product_code,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            return ok(page_payload(items, total, page, page_size))
        rows, total = list_sales_orders(
            db,
            user.tenant_id,
            page=page,
            page_size=page_size,
            keyword=keyword,
            customer_id=customer_id,
            status=status,
            product_code=product_code,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    items = [serialize_sales_order(db, user.tenant_id, r) for r in rows]
    return ok(page_payload(items, total, page, page_size))


@router.get("/status-stats")
def api_sales_order_status_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按展示状态统计订单数量（待确认/待生产/生产中/已完成/已取消）。"""
    return ok(count_sales_orders_by_status(db, user.tenant_id))


@router.post("")
def api_create_sales_order(
    body: SalesOrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        so = create_sales_order(db, user.tenant_id, body, created_by=user.id)
    except (SalesOrderError, OrderError) as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(serialize_sales_order(db, user.tenant_id, so))


@router.post("/lines/confirm-batch")
def api_confirm_sales_order_lines_batch(
    body: SalesOrderLinesConfirmBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    refs = [(item.sales_order_id, item.line_id) for item in body.lines]
    try:
        count = confirm_sales_order_lines_batch(db, user.tenant_id, refs, created_by=user.id)
    except (SalesOrderError, OrderError) as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok({"confirmed_count": count})


@router.post("/lines/simulate-mrp")
def api_simulate_sales_order_lines_mrp(
    body: SalesOrderLinesSimulateMrpIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """销售行模拟 MRP：只算不锁，输出缺料清单。"""
    refs = [(item.sales_order_id, item.line_id) for item in body.lines]
    try:
        result = simulate_sales_order_lines_mrp(
            db,
            user.tenant_id,
            refs,
            include_shared=body.include_shared,
            shortages_only=body.shortages_only,
        )
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.get("/{sales_order_id}")
def api_get_sales_order(
    sales_order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        so = get_sales_order(db, user.tenant_id, sales_order_id)
    except SalesOrderError as e:
        raise HTTPException(status_code=404, detail=e.message)
    return ok(serialize_sales_order(db, user.tenant_id, so))


@router.patch("/{sales_order_id}")
def api_update_sales_order(
    sales_order_id: int,
    body: SalesOrderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        so = update_sales_order(db, user.tenant_id, sales_order_id, body)
    except (SalesOrderError, OrderError) as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(serialize_sales_order(db, user.tenant_id, so))


@router.post("/{sales_order_id}/lines")
def api_add_sales_order_line(
    sales_order_id: int,
    body: SalesOrderLineIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        so = add_sales_order_line(db, user.tenant_id, sales_order_id, body)
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(serialize_sales_order(db, user.tenant_id, so))


@router.patch("/{sales_order_id}/lines/{line_id}")
def api_update_sales_order_line(
    sales_order_id: int,
    line_id: int,
    body: SalesOrderLineIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        so = update_sales_order_line(db, user.tenant_id, sales_order_id, line_id, body)
    except SalesOrderError as e:
        status = 404 if e.code == "line_not_found" else 400
        raise HTTPException(status_code=status, detail=e.message)
    return ok(serialize_sales_order(db, user.tenant_id, so))


@router.delete("/{sales_order_id}/lines/{line_id}")
def api_delete_sales_order_line(
    sales_order_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        so = delete_sales_order_line(db, user.tenant_id, sales_order_id, line_id)
    except SalesOrderError as e:
        status = 404 if e.code == "line_not_found" else 400
        raise HTTPException(status_code=status, detail=e.message)
    return ok(serialize_sales_order(db, user.tenant_id, so))


@router.post("/{sales_order_id}/cancel")
def api_cancel_sales_order(
    sales_order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """取消销售订单：状态改为已取消，记录保留（与删除明细不同）。"""
    try:
        so = cancel_sales_order(db, user.tenant_id, sales_order_id)
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(serialize_sales_order(db, user.tenant_id, so))


@router.post("/{sales_order_id}/lines/{line_id}/confirm")
def api_confirm_sales_order_line(
    sales_order_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        so = confirm_sales_order_line(
            db, user.tenant_id, sales_order_id, line_id, created_by=user.id
        )
    except (SalesOrderError, OrderError) as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(serialize_sales_order(db, user.tenant_id, so))


@router.post("/{sales_order_id}/confirm")
def api_confirm_sales_order(
    sales_order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        so = confirm_sales_order(db, user.tenant_id, sales_order_id, created_by=user.id)
    except (SalesOrderError, OrderError) as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(serialize_sales_order(db, user.tenant_id, so))
