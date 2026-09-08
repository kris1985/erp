"""B2a：外发工序单 API。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_employee, require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.common import normalize_page, ok, page_payload
from app.services.subcontract_out_service import (
    SubcontractError,
    cancel_subcontract_order,
    create_subcontract_order,
    delete_subcontract_order,
    get_subcontract_order,
    issue_subcontract,
    list_issues,
    list_receipts,
    list_subcontract_orders,
    receive_subcontract,
    suggest_subcontract_material_unit_price,
    update_subcontract_order,
    _out,
)

router = APIRouter(prefix="/subcontract-orders", tags=["subcontract-orders"])


def require_subcontract_order_creator(
    employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
) -> Employee:
    """后台管理角色或已获现场“外发”授权的员工可以创建外发单。"""
    from app.services import employee_feature_service, rbac_service

    if employee_feature_service.has_feature(db, employee, "subcontract_out"):
        return employee
    if rbac_service.employee_effective_base_role(db, employee) in ("admin", "manager"):
        return employee
    raise HTTPException(status_code=403, detail="你没有外发权限，请联系后台管理员在员工档案中开通")


def require_subcontract_acceptor(
    employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
) -> Employee:
    """后台管理角色或已获现场“外发验收”授权的员工可以验收外发单。"""
    from app.services import employee_feature_service, rbac_service

    if employee_feature_service.has_feature(db, employee, "subcontract_acceptance"):
        return employee
    if rbac_service.employee_effective_base_role(db, employee) in ("admin", "manager"):
        return employee
    raise HTTPException(status_code=403, detail="你没有外发验收权限，请联系后台管理员在员工档案中开通")


class SubcontractOrderCreateIn(BaseModel):
    partner_id: int
    total_qty: int
    unit_price: Decimal = Decimal("0")
    material_unit_price: Decimal = Decimal("0")
    subcontract_unit_consumption: Decimal = Decimal("0")
    delivery_date: date | None = None
    process_id: int | None = None
    order_process_ids: list[int] | None = None
    order_id: int | None = None
    header_id: int | None = None
    execution_id: int | None = None
    own_product_id: int | None = None
    notes: str | None = None


class SubcontractOrderUpdateIn(BaseModel):
    partner_id: int | None = None
    process_id: int | None = None
    order_process_ids: list[int] | None = None
    header_id: int | None = None
    total_qty: int | None = None
    unit_price: Decimal | None = None
    material_unit_price: Decimal | None = None
    subcontract_unit_consumption: Decimal | None = None
    delivery_date: date | None = None
    notes: str | None = None


class SubcontractIssueIn(BaseModel):
    qty: int
    note: str | None = None


class SubcontractReceiptIn(BaseModel):
    qty: int
    defect_qty: int = 0
    shared_loss_amount: Decimal = Field(default=Decimal("0"), ge=0)
    note: str | None = None


@router.get("")
def api_list_subcontract_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    outstanding: bool = False,
    keyword: str | None = None,
    partner_id: int | None = Query(None, ge=1),
    header_id: int | None = Query(None, ge=1),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    page, page_size, _ = normalize_page(page, page_size)
    try:
        rows, total = list_subcontract_orders(
            db,
            user.tenant_id,
            status=status,
            outstanding=outstanding,
            keyword=keyword,
            partner_id=partner_id,
            header_id=header_id,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    except SubcontractError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(page_payload(rows, total, page, page_size))


@router.get("/price-quote")
def api_subcontract_price_quote(
    header_id: int = Query(gt=0),
    order_process_ids: str = Query(..., min_length=1, description="逗号分隔的工艺路由 id"),
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    ids: list[int] = []
    for part in order_process_ids.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            ids.append(int(text))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="工序参数无效") from exc
    try:
        quote = suggest_subcontract_material_unit_price(
            db,
            tenant_id=user.tenant_id,
            header_id=header_id,
            order_process_ids=ids,
        )
    except SubcontractError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    return ok(quote)


@router.post("")
def api_create_subcontract_order(
    body: SubcontractOrderCreateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_subcontract_order_creator),
):
    try:
        order = create_subcontract_order(
            db,
            user.tenant_id,
            partner_id=body.partner_id,
            total_qty=body.total_qty,
            unit_price=body.unit_price,
            material_unit_price=body.material_unit_price,
            subcontract_unit_consumption=body.subcontract_unit_consumption,
            delivery_date=body.delivery_date,
            process_id=body.process_id,
            order_process_ids=body.order_process_ids,
            order_id=body.order_id,
            header_id=body.header_id,
            execution_id=body.execution_id,
            own_product_id=body.own_product_id,
            notes=body.notes,
            created_by=user.id,
        )
    except SubcontractError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(_out(db, order))


@router.get("/{order_id}/qr.png")
def api_subcontract_receive_qr(order_id: int, request: Request):
    """外发验收二维码（公开图片，扫码进入页面后仍需登录）。"""
    import io

    import qrcode
    from fastapi.responses import Response

    if order_id <= 0:
        raise HTTPException(status_code=400, detail="外发单无效")
    base = str(request.base_url).rstrip("/")
    image = qrcode.make(f"{base}/subcontract-acceptance/{order_id}")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="subcontract_{order_id}.png"'},
    )


@router.get("/{order_id}")
def api_get_subcontract_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        order = get_subcontract_order(db, user.tenant_id, order_id)
    except SubcontractError as e:
        raise HTTPException(status_code=404, detail=e.message)
    return ok(_out(db, order, include_flows=True))


@router.get("/{order_id}/acceptance")
def api_get_subcontract_acceptance(
    order_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_subcontract_acceptor),
):
    try:
        order = get_subcontract_order(db, user.tenant_id, order_id)
    except SubcontractError as e:
        raise HTTPException(status_code=404, detail=e.message)
    return ok(_out(db, order, include_flows=True))


@router.patch("/{order_id}")
def api_update_subcontract_order(
    order_id: int,
    body: SubcontractOrderUpdateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        order = update_subcontract_order(
            db,
            user.tenant_id,
            order_id,
            partner_id=body.partner_id,
            process_id=body.process_id,
            order_process_ids=body.order_process_ids,
            header_id=body.header_id,
            total_qty=body.total_qty,
            unit_price=body.unit_price,
            material_unit_price=body.material_unit_price,
            subcontract_unit_consumption=body.subcontract_unit_consumption,
            delivery_date=body.delivery_date,
            notes=body.notes,
        )
    except SubcontractError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(_out(db, order))


@router.post("/{order_id}/cancel")
def api_cancel_subcontract_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        order = cancel_subcontract_order(db, user.tenant_id, order_id)
    except SubcontractError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(_out(db, order))


@router.delete("/{order_id}")
def api_delete_subcontract_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        delete_subcontract_order(db, user.tenant_id, order_id)
    except SubcontractError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok({"id": order_id, "deleted": True})


@router.post("/{order_id}/issues")
def api_issue_subcontract(
    order_id: int,
    body: SubcontractIssueIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(issue_subcontract(db, user.tenant_id, order_id, qty=body.qty, note=body.note, created_by=user.id))
    except SubcontractError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/{order_id}/receipts")
def api_receive_subcontract(
    order_id: int,
    body: SubcontractReceiptIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_subcontract_acceptor),
):
    try:
        return ok(
            receive_subcontract(
                db,
                user.tenant_id,
                order_id,
                qty=body.qty,
                defect_qty=body.defect_qty,
                shared_loss_amount=body.shared_loss_amount,
                note=body.note,
                created_by=user.id,
            )
        )
    except SubcontractError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/{order_id}/issues")
def api_list_subcontract_issues(
    order_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(list_issues(db, user.tenant_id, order_id))
    except SubcontractError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.get("/{order_id}/receipts")
def api_list_subcontract_receipts(
    order_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(list_receipts(db, user.tenant_id, order_id))
    except SubcontractError as e:
        raise HTTPException(status_code=404, detail=e.message)
