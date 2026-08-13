"""销售订单 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
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
from app.services.sales_order_ai_import import (
    apply_clarifications,
    confirm_import_session,
    create_import_session,
    get_import_session,
    patch_import_draft,
)
from app.services.sales_order_import import build_sales_order_import_template_bytes
from app.services.sales_order_service import (
    SalesOrderError,
    add_sales_order_line,
    cancel_sales_order,
    confirm_sales_order,
    confirm_sales_order_line,
    confirm_sales_order_lines_batch,
    create_demand_purchase_drafts,
    create_sales_order,
    count_sales_orders_by_status,
    delete_sales_order_line,
    get_sales_order,
    list_demand_shortages,
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


@router.get("/demand-shortages")
def api_list_demand_shortages(
    sales_order_id: int | None = None,
    include_shared: bool | None = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """需求缺料：已接单未排产销售行 × BOM，只读不锁。"""
    try:
        return ok(
            list_demand_shortages(
                db,
                user.tenant_id,
                sales_order_id=sales_order_id,
                include_shared=include_shared,
            )
        )
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/lines/purchase-drafts-from-mrp")
def api_create_demand_purchase_drafts(
    body: SalesOrderLinesSimulateMrpIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """按需求缺料生成采购草稿（挂销售单，不锁库存）。"""
    refs = [(item.sales_order_id, item.line_id) for item in body.lines]
    try:
        created = create_demand_purchase_drafts(
            db,
            user.tenant_id,
            refs,
            include_shared=body.include_shared,
            user_id=user.id,
        )
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok({"items": created, "count": len(created)})


@router.get("/import-template")
def api_sales_order_import_template(
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from urllib.parse import quote

    content = build_sales_order_import_template_bytes()
    filename = "销售订单导入模版.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="sales_order_import.xlsx"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.post("/import-sessions")
async def api_create_sales_order_import_session(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
    file: UploadFile | None = File(None),
):
    """上传 Excel，创建导入会话（不落库，需核对确认）。"""
    if not file:
        raise HTTPException(status_code=400, detail="请上传 Excel 文件（.xlsx）")
    name = (file.filename or "").lower()
    if not (name.endswith(".xlsx") or name.endswith(".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 订单模版")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        session = create_import_session(
            db,
            user.tenant_id,
            filename=file.filename or "order.xlsx",
            content=raw,
            created_by=user.id,
        )
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(session)


@router.get("/import-sessions/{session_id}")
def api_get_sales_order_import_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    _ = db
    try:
        return ok(get_import_session(user.tenant_id, session_id))
    except SalesOrderError as e:
        raise HTTPException(status_code=404, detail=e.message)


class ImportClarifyIn(BaseModel):
    answers: list[dict] = Field(default_factory=list)


@router.post("/import-sessions/{session_id}/clarify")
def api_clarify_sales_order_import_session(
    session_id: str,
    body: ImportClarifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(apply_clarifications(db, user.tenant_id, session_id, body.answers))
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)


class ImportDraftPatchIn(BaseModel):
    order_no: str | None = None
    ordered_at: str | None = None
    delivery_date: str | None = None
    notes: str | None = None
    customer: dict | None = None
    lines: list[dict] | None = None
    images: list[dict] | None = None


@router.patch("/import-sessions/{session_id}")
def api_patch_sales_order_import_session(
    session_id: str,
    body: ImportDraftPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            patch_import_draft(
                db,
                user.tenant_id,
                session_id,
                body.model_dump(exclude_unset=True),
            )
        )
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/import-sessions/{session_id}/confirm")
def api_confirm_sales_order_import_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(confirm_import_session(db, user.tenant_id, session_id, created_by=user.id))
    except SalesOrderError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/import")
async def api_sales_order_import(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
    file: UploadFile | None = File(None),
):
    """兼容旧入口：等价于创建导入会话（仍须确认建单）。"""
    return await api_create_sales_order_import_session(db=db, user=user, file=file)


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
