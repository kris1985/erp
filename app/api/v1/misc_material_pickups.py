"""不跟生产单的领料。"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_employee
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services import employee_feature_service, misc_material_pickup_service
from app.services.misc_material_pickup_service import PickupError

router = APIRouter(prefix="/misc-material-pickups", tags=["misc-material-pickups"])


def require_material_issue(
    employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
) -> Employee:
    if employee_feature_service.has_feature(db, employee, "material_issue"):
        return employee
    raise HTTPException(status_code=403, detail="你没有领料权限，请联系管理员在角色权限中开通")


def _http(exc: PickupError) -> HTTPException:
    status = 404 if exc.code == "not_found" else 403 if exc.code == "forbidden" else 400
    return HTTPException(status_code=status, detail=exc.message)


class PickupLineIn(BaseModel):
    supplier_product_id: Optional[int] = None
    material_name: Optional[str] = None
    material_code: Optional[str] = None
    qty: Decimal


class PickupCreateIn(BaseModel):
    notes: Optional[str] = None
    lines: list[PickupLineIn] = Field(min_length=1, max_length=30)


@router.get("/materials")
def api_search_materials(
    keyword: str = "",
    db: Session = Depends(get_db),
    user: Employee = Depends(require_material_issue),
):
    return ok(misc_material_pickup_service.search_materials(db, user.tenant_id, keyword))


@router.get("")
def api_list_pickups(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_material_issue),
):
    return ok(
        misc_material_pickup_service.list_pickups(
            db,
            user.tenant_id,
            user.id,
            page=page,
            page_size=page_size,
        )
    )


@router.post("")
def api_create_pickup(
    body: PickupCreateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_material_issue),
):
    try:
        return ok(
            misc_material_pickup_service.create_pickup(
                db,
                user.tenant_id,
                user.id,
                lines=[line.model_dump() for line in body.lines],
                notes=body.notes,
            )
        )
    except PickupError as exc:
        raise _http(exc) from exc


@router.post("/{pickup_id}/receive")
def api_receive_pickup(
    pickup_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_material_issue),
):
    try:
        return ok(misc_material_pickup_service.receive_pickup(db, user.tenant_id, pickup_id, user.id))
    except PickupError as exc:
        raise _http(exc) from exc


@router.post("/{pickup_id}/cancel")
def api_cancel_pickup(
    pickup_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_material_issue),
):
    try:
        return ok(misc_material_pickup_service.cancel_pickup(db, user.tenant_id, pickup_id, user.id))
    except PickupError as exc:
        raise _http(exc) from exc
