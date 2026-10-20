"""AU-I2：成品仓 API。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services import fg_service
from app.services.fg_service import FgError

router = APIRouter(prefix="/fg-stocks", tags=["fg"])


class FgShipIn(BaseModel):
    sales_order_id: int | None = None


class FgIntakeOrderIn(BaseModel):
    sales_order_id: int
    carton_qty: int = Field(ge=0)


class FgIntakeIn(BaseModel):
    orders: list[FgIntakeOrderIn]


@router.get("")
def api_list_fg_stocks(
    q: str | None = Query(None),
    only_positive: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    items = fg_service.list_fg_stocks(
        db,
        tenant_id=user.tenant_id,
        q=q,
        only_positive=only_positive,
        limit=limit,
    )
    return ok({"items": items, "total": len(items)})


@router.get("/cartons")
def api_list_fg_cartons(
    q: str | None = Query(None),
    status: str = Query("in_stock", pattern="^(in_stock|shipped)$"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    """按箱查询当前成品库存或出库记录。"""
    return ok(
        fg_service.list_fg_cartons(
            db,
            tenant_id=user.tenant_id,
            q=q,
            limit=limit,
            status=status,
            date_from=date_from,
            date_to=date_to,
        )
    )


@router.get("/orders")
def api_list_fg_orders(
    q: str | None = Query(None),
    status: str = Query("in_stock", pattern="^(in_stock|shipped|defective)$"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    """最后工序段完工后的成品仓，以及出货后的出库记录。按生产单列。"""
    return ok(
        fg_service.list_finished_orders(
            db,
            tenant_id=user.tenant_id,
            q=q,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    )


@router.get("/orders/{header_id}/intake")
def api_fg_intake_sources(
    header_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    try:
        data = fg_service.fg_intake_sources(db, tenant_id=user.tenant_id, header_id=header_id)
    except FgError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/orders/{header_id}/intake")
def api_fg_intake(
    header_id: int,
    body: FgIntakeIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    try:
        data = fg_service.intake_finished_cartons(
            db,
            tenant_id=user.tenant_id,
            header_id=header_id,
            orders=[row.model_dump() for row in body.orders],
        )
    except FgError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/orders/{header_id}/ship")
def api_ship_fg_order(
    header_id: int,
    body: FgShipIn | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    try:
        data = fg_service.ship_finished_order(
            db,
            tenant_id=user.tenant_id,
            header_id=header_id,
            employee_id=user.id,
            sales_order_id=body.sales_order_id if body else None,
        )
    except FgError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/orders/{header_id}/defective")
def api_mark_fg_defective(
    header_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    try:
        data = fg_service.mark_finished_defective(
            db,
            tenant_id=user.tenant_id,
            header_id=header_id,
            employee_id=user.id,
        )
    except FgError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.get("/{fg_stock_id}/ledgers")
def api_list_fg_ledgers(
    fg_stock_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    try:
        items = fg_service.list_fg_ledgers(
            db, tenant_id=user.tenant_id, fg_stock_id=fg_stock_id, limit=limit
        )
    except FgError as e:
        raise HTTPException(status_code=404, detail=e.message) from e
    return ok({"items": items, "total": len(items)})
