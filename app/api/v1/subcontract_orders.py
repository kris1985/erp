"""B2a：外发工序单 API。"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
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
    get_subcontract_order,
    issue_subcontract,
    list_issues,
    list_receipts,
    list_subcontract_orders,
    receive_subcontract,
    update_subcontract_order,
    _out,
)

router = APIRouter(prefix="/subcontract-orders", tags=["subcontract-orders"])


class SubcontractOrderCreateIn(BaseModel):
    partner_id: int
    total_qty: int
    unit_price: Decimal = Decimal("0")
    process_id: int | None = None
    order_id: int | None = None
    header_id: int | None = None
    execution_id: int | None = None
    own_product_id: int | None = None
    notes: str | None = None


class SubcontractOrderUpdateIn(BaseModel):
    partner_id: int | None = None
    process_id: int | None = None
    total_qty: int | None = None
    unit_price: Decimal | None = None
    notes: str | None = None


class SubcontractIssueIn(BaseModel):
    qty: int
    note: str | None = None


class SubcontractReceiptIn(BaseModel):
    qty: int
    defect_qty: int = 0
    note: str | None = None


@router.get("")
def api_list_subcontract_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    outstanding: bool = False,
    keyword: str | None = None,
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
            page=page,
            page_size=page_size,
        )
    except SubcontractError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(page_payload(rows, total, page, page_size))


@router.post("")
def api_create_subcontract_order(
    body: SubcontractOrderCreateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        order = create_subcontract_order(
            db,
            user.tenant_id,
            partner_id=body.partner_id,
            total_qty=body.total_qty,
            unit_price=body.unit_price,
            process_id=body.process_id,
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
            total_qty=body.total_qty,
            unit_price=body.unit_price,
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            receive_subcontract(
                db,
                user.tenant_id,
                order_id,
                qty=body.qty,
                defect_qty=body.defect_qty,
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
