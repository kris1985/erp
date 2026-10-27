"""手机备料：生产单列表、第一工序段物料、扣库存并绑定空闲备料码。"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_employee, require_permissions
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services.material_prep_service import (
    MaterialPrepError,
    create_prep,
    get_by_token,
    list_orders,
    list_qrs,
    preview_materials,
    release_qr,
    sign_prep,
)

router = APIRouter(prefix="/material-preps", tags=["material-preps"])


def _http(exc: MaterialPrepError) -> HTTPException:
    status = 404 if exc.code in ("not_found", "header_not_found", "picker_not_found") else 400
    return HTTPException(status_code=status, detail=exc.message)


class PrepLineIn(BaseModel):
    supplier_product_id: int
    actual_qty: Decimal = Field(ge=0)


class PrepCreateIn(BaseModel):
    header_id: int
    pairs: int = Field(gt=0, le=100000)
    lines: list[PrepLineIn] = Field(min_length=1, max_length=80)
    origin: str = ""


@router.get("/orders")
def api_orders(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("mobile.material_prep")),
):
    return ok(list_orders(db, user.tenant_id))


@router.get("/qrs")
def api_qrs(
    origin: str = "",
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("mobile.material_prep", "menu.masters")),
):
    return ok(list_qrs(db, user.tenant_id, origin))


@router.post("/qrs/{slot}/release")
def api_release_qr(
    slot: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("mobile.material_prep", "menu.masters")),
):
    try:
        return ok(release_qr(db, user.tenant_id, slot, user.id))
    except MaterialPrepError as exc:
        raise _http(exc) from exc


@router.get("/orders/{header_id}/materials")
def api_materials(
    header_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("mobile.material_prep")),
):
    try:
        return ok(preview_materials(db, user.tenant_id, header_id))
    except MaterialPrepError as exc:
        raise _http(exc) from exc


@router.post("")
def api_create(
    body: PrepCreateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("mobile.material_prep")),
):
    try:
        return ok(
            create_prep(
                db,
                user.tenant_id,
                user.id,
                header_id=body.header_id,
                pairs=body.pairs,
                lines=[line.model_dump() for line in body.lines],
                origin=body.origin,
            )
        )
    except MaterialPrepError as exc:
        raise _http(exc) from exc


@router.get("/by-token/{token}")
def api_by_token(
    token: str,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(get_by_token(db, user.tenant_id, token))
    except MaterialPrepError as exc:
        raise _http(exc) from exc


@router.post("/by-token/{token}/sign")
def api_sign(
    token: str,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        return ok(sign_prep(db, user.tenant_id, token, user))
    except MaterialPrepError as exc:
        raise _http(exc) from exc
