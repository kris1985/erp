"""模具仓：到货登记、入库记录、库存流水。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services.tooling_service import (
    ToolingError,
    adjust,
    get_receipt,
    list_items,
    list_ledgers,
    list_receipts,
    list_use_departments,
    receive,
    update_receipt,
)

router = APIRouter(prefix="/tooling", tags=["tooling"])


def _http(exc: ToolingError) -> HTTPException:
    status = 404 if exc.code == "not_found" else 400
    return HTTPException(status_code=status, detail=exc.message)


class SizeQtyIn(BaseModel):
    size_id: int
    qty: Decimal = Field(ge=0, le=100000)


class ReceiptLineIn(BaseModel):
    department_id: int
    code: str = Field(min_length=1, max_length=50)
    unit_price: Decimal = Field(gt=0)
    sizes: list[SizeQtyIn] = Field(min_length=1, max_length=80)


class ReceiptIn(BaseModel):
    kind: str
    supplier_id: int
    receipt_date: Optional[date] = None
    delivery_note_no: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=255)
    lines: list[ReceiptLineIn] = Field(min_length=1, max_length=40)


class AdjustIn(BaseModel):
    department_id: Optional[int] = None
    target_department_id: Optional[int] = None
    notes: Optional[str] = Field(default=None, max_length=255)
    sizes: list[SizeQtyIn] = Field(min_length=1, max_length=80)


@router.get("/items")
def api_list_items(
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.tooling")),
):
    try:
        items = list_items(db, user.tenant_id, kind=kind, keyword=keyword)
    except ToolingError as exc:
        raise _http(exc) from exc
    return ok({"items": items, "total": len(items)})


@router.get("/items/{item_id}/ledgers")
def api_ledgers(
    item_id: int,
    department_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.tooling")),
):
    try:
        rows = list_ledgers(db, user.tenant_id, item_id, department_id=department_id)
    except ToolingError as exc:
        raise _http(exc) from exc
    return ok({"items": rows})


@router.post("/items/{item_id}/adjust")
def api_adjust(
    item_id: int,
    body: AdjustIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.tooling.write")),
):
    try:
        item = adjust(
            db,
            user.tenant_id,
            item_id,
            department_id=body.department_id,
            target_department_id=body.target_department_id,
            sizes=[(row.size_id, row.qty) for row in body.sizes],
            notes=body.notes,
            user_id=user.id,
        )
    except ToolingError as exc:
        raise _http(exc) from exc
    return ok(item)


@router.get("/departments")
def api_use_departments(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.tooling")),
):
    return ok({"items": list_use_departments(db, user.tenant_id)})


def _receipt_lines(body: ReceiptIn) -> list[dict]:
    return [
        {
            "department_id": line.department_id,
            "code": line.code,
            "unit_price": line.unit_price,
            "sizes": [(row.size_id, row.qty) for row in line.sizes],
        }
        for line in body.lines
    ]


@router.get("/receipts/{receipt_id}")
def api_get_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.tooling")),
):
    try:
        data = get_receipt(db, user.tenant_id, receipt_id)
    except ToolingError as exc:
        raise _http(exc) from exc
    return ok(data)


@router.put("/receipts/{receipt_id}")
def api_update_receipt(
    receipt_id: int,
    body: ReceiptIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.tooling.write")),
):
    try:
        data = update_receipt(
            db,
            user.tenant_id,
            receipt_id,
            kind=body.kind,
            supplier_id=body.supplier_id,
            receipt_date=body.receipt_date,
            delivery_note_no=body.delivery_note_no,
            notes=body.notes,
            lines=_receipt_lines(body),
            user_id=user.id,
        )
    except ToolingError as exc:
        raise _http(exc) from exc
    return ok(data)


@router.get("/receipts")
def api_list_receipts(
    tooling_item_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.tooling")),
):
    try:
        rows = list_receipts(db, user.tenant_id, tooling_item_id=tooling_item_id)
    except ToolingError as exc:
        raise _http(exc) from exc
    return ok({"items": rows})


@router.post("/receipts")
def api_receive(
    body: ReceiptIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.tooling.write")),
):
    try:
        data = receive(
            db,
            user.tenant_id,
            kind=body.kind,
            supplier_id=body.supplier_id,
            receipt_date=body.receipt_date,
            delivery_note_no=body.delivery_note_no,
            notes=body.notes,
            lines=_receipt_lines(body),
            user_id=user.id,
        )
    except ToolingError as exc:
        raise _http(exc) from exc
    return ok(data)
