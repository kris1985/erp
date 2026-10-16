"""物料仓当场领料：仓管开单出二维码，领料人用手机扫码确认后出库。"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_employee, require_permissions
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services.warehouse_pickup_service import (
    WarehousePickupError,
    cancel_pickup,
    create_aux_pickup,
    create_aux_return,
    create_dev_pickup,
    create_dev_return,
    create_production_pickup,
    create_production_return,
    get_by_token,
    get_pickup,
    list_pickups,
    make_sign_qr,
    collapse_production_size_lines,
    preview_production,
    quote_pool_returnable,
    search_production_headers,
    search_dev_materials,
    sign_pickup,
)

router = APIRouter(prefix="/warehouse-pickups", tags=["warehouse-pickups"])


def _http(exc: WarehousePickupError) -> HTTPException:
    status = 404 if exc.code in ("not_found", "header_not_found", "picker_not_found") else 400
    return HTTPException(status_code=status, detail=exc.message)


class PickupLineIn(BaseModel):
    supplier_product_id: Optional[int] = None
    size_id: Optional[int] = None
    requirement_id: Optional[int] = None
    qty: Decimal


class PickupCreateIn(BaseModel):
    kind: str
    header_no: Optional[str] = None
    notes: Optional[str] = None
    origin: Optional[str] = None
    lines: list[PickupLineIn] = Field(min_length=1, max_length=40)


class ReturnableLineIn(BaseModel):
    supplier_product_id: int
    size_id: Optional[int] = None


class ReturnableIn(BaseModel):
    kind: str
    lines: list[ReturnableLineIn] = Field(default_factory=list, max_length=40)


@router.get("/materials")
def api_search_materials(
    keyword: str = "",
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.shared_materials.write")),
):
    return ok(search_dev_materials(db, user.tenant_id, keyword))


@router.get("/production-options")
def api_search_production(
    q: str = "",
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.shared_materials.write")),
):
    return ok(search_production_headers(db, user.tenant_id, q))


@router.get("/production")
def api_preview_production(
    header_no: str = "",
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.shared_materials.write")),
):
    try:
        data = preview_production(db, user.tenant_id, header_no)
    except WarehousePickupError as exc:
        raise _http(exc) from exc
    if not data.get("ambiguous"):
        data = {**data, "lines": collapse_production_size_lines(data.get("lines") or [])}
    return ok(data)


@router.post("/returnable")
def api_quote_returnable(
    body: ReturnableIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.shared_materials.write")),
):
    try:
        return ok(quote_pool_returnable(db, user.tenant_id, body.kind, [line.model_dump() for line in body.lines]))
    except WarehousePickupError as exc:
        raise _http(exc) from exc


@router.get("")
def api_list_pickups(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    kind: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    return ok(list_pickups(db, user.tenant_id, kind=kind, status=status, page=page, page_size=page_size))


@router.get("/by-token/{token}")
def api_get_by_token(
    token: str,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(get_by_token(db, user.tenant_id, token))
    except WarehousePickupError as exc:
        raise _http(exc) from exc


@router.post("/by-token/{token}/sign")
def api_sign_by_token(
    token: str,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(sign_pickup(db, user.tenant_id, token, user))
    except WarehousePickupError as exc:
        raise _http(exc) from exc


@router.get("/{pickup_id}")
def api_get_pickup(
    pickup_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(get_pickup(db, user.tenant_id, pickup_id))
    except WarehousePickupError as exc:
        raise _http(exc) from exc


@router.get("/{pickup_id}/sign-qr")
def api_sign_qr(
    pickup_id: int,
    origin: str = "",
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.shared_materials.write")),
):
    try:
        data = get_pickup(db, user.tenant_id, pickup_id)
        if data.get("status") != "pending" or not data.get("sign_token"):
            raise WarehousePickupError("not_pending", "这张单不用再确认")
        return ok(make_sign_qr(origin, data["sign_token"]))
    except WarehousePickupError as exc:
        raise _http(exc) from exc


@router.post("/{pickup_id}/cancel")
def api_cancel_pickup(
    pickup_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.shared_materials.write")),
):
    try:
        return ok(cancel_pickup(db, user.tenant_id, user.id, pickup_id))
    except WarehousePickupError as exc:
        raise _http(exc) from exc


@router.post("")
def api_create_pickup(
    body: PickupCreateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.shared_materials.write")),
):
    lines = [line.model_dump() for line in body.lines]
    try:
        if body.kind == "dev":
            data = create_dev_pickup(
                db,
                user.tenant_id,
                user.id,
                lines=lines,
                notes=body.notes,
            )
        elif body.kind == "aux":
            data = create_aux_pickup(
                db,
                user.tenant_id,
                user.id,
                lines=lines,
                notes=body.notes,
            )
        elif body.kind == "production":
            data = create_production_pickup(
                db,
                user.tenant_id,
                user.id,
                header_no=body.header_no or "",
                lines=lines,
                notes=body.notes,
            )
        elif body.kind == "dev_return":
            data = create_dev_return(
                db,
                user.tenant_id,
                user.id,
                lines=lines,
                notes=body.notes,
            )
        elif body.kind == "aux_return":
            data = create_aux_return(
                db,
                user.tenant_id,
                user.id,
                lines=lines,
                notes=body.notes,
            )
        elif body.kind == "production_return":
            data = create_production_return(
                db,
                user.tenant_id,
                user.id,
                header_no=body.header_no or "",
                lines=lines,
                notes=body.notes,
            )
        else:
            raise WarehousePickupError("invalid_kind", "类型无效")
        if body.origin and data.get("sign_token"):
            data.update(make_sign_qr(body.origin, data["sign_token"]))
    except WarehousePickupError as exc:
        raise _http(exc) from exc
    return ok(data)
