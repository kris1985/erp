from __future__ import annotations

import io

import qrcode
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import Principal, get_principal, require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services import cut_output_service
from app.services.cut_output_service import CutOutputError


router = APIRouter(tags=["cut-outputs"])


class BasketCreate(BaseModel):
    basket_code: str
    location: str | None = None


class BasketBind(BaseModel):
    header_id: int
    basket_code: str
    qualified_pairs: int = Field(gt=0)
    defect_pairs: int = Field(default=0, ge=0)
    completion_mode: str = "complete"
    sales_order_line_id: int | None = None
    qty: int = Field(gt=0)


class BasketUpdate(BaseModel):
    location: str | None = None
    status: str | None = None
    is_active: bool | None = None


class BasketQtyUpdate(BaseModel):
    qty: int = Field(gt=0)


class ContributionIn(BaseModel):
    worker_id: int
    credited_pairs: int = Field(gt=0)
    process_id: int | None = None
    material_requirement_id: int | None = None
    component_group: str | None = None


class CutOutputConfirm(BaseModel):
    qualified_pairs: int = Field(gt=0)
    defect_pairs: int = Field(default=0, ge=0)
    completion_mode: str = "complete"
    contributions: list[ContributionIn] = Field(default_factory=list)


def _employee(principal: Principal) -> Employee:
    if not principal.employee:
        raise HTTPException(status_code=403, detail="请登录后操作")
    return principal.employee


def _call(fn, *args, **kwargs):
    try:
        return ok(fn(*args, **kwargs))
    except CutOutputError as exc:
        code = 404 if exc.code.endswith("not_found") else 400
        raise HTTPException(status_code=code, detail=exc.message) from exc


@router.post("/reusable-baskets")
def api_create_basket(
    body: BasketCreate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    return _call(
        cut_output_service.create_basket,
        db,
        user.tenant_id,
        basket_code=body.basket_code,
        location=body.location,
        user_id=user.id,
    )


@router.get("/reusable-baskets")
def api_list_baskets(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    _employee(principal)
    return _call(cut_output_service.list_baskets, db, principal.tenant_id, status=status)


@router.get("/reusable-baskets/by-code/{basket_code}")
def api_basket_by_code(
    basket_code: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    _employee(principal)
    return _call(cut_output_service.get_basket_by_code, db, principal.tenant_id, basket_code)


@router.patch("/reusable-baskets/{basket_id}")
def api_update_basket(
    basket_id: int,
    body: BasketUpdate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    return _call(
        cut_output_service.update_basket,
        db,
        user.tenant_id,
        basket_id,
        **body.model_dump(exclude_unset=True),
    )


@router.get("/reusable-baskets/{basket_id}/qr.png")
def api_basket_qr_png(
    basket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    basket = cut_output_service.get_basket(db, user.tenant_id, basket_id)
    base = str(request.base_url).rstrip("/")
    image = qrcode.make(f"{base}/basket/{basket.basket_code}")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="basket_{basket.basket_code}.png"'},
    )


@router.post("/cut-outputs/bind-basket")
def api_bind_basket(
    body: BasketBind,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    user = _employee(principal)
    return _call(
        cut_output_service.bind_basket,
        db,
        principal.tenant_id,
        header_id=body.header_id,
        basket_code=body.basket_code,
        reporter_id=user.id,
        qualified_pairs=body.qualified_pairs,
        defect_pairs=body.defect_pairs,
        completion_mode=body.completion_mode,
        sales_order_line_id=body.sales_order_line_id,
        qty=body.qty,
    )


@router.get("/cut-outputs/quote")
def api_cut_report_quote(
    header_id: int = Query(gt=0),
    order_process_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    _employee(principal)
    return _call(
        cut_output_service.cut_report_quote,
        db,
        principal.tenant_id,
        header_id,
        order_process_id=order_process_id,
    )


@router.patch("/cut-outputs/{output_id}/baskets/{link_id}")
def api_update_basket_qty(
    output_id: int,
    link_id: int,
    body: BasketQtyUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    user = _employee(principal)
    return _call(
        cut_output_service.update_basket_qty,
        db,
        principal.tenant_id,
        output_id,
        link_id,
        qty=body.qty,
        reporter_id=user.id,
    )


@router.delete("/cut-outputs/{output_id}/baskets/{link_id}")
def api_remove_basket(
    output_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    user = _employee(principal)
    return _call(
        cut_output_service.remove_basket,
        db,
        principal.tenant_id,
        output_id,
        link_id,
        reporter_id=user.id,
    )


@router.post("/cut-outputs/{output_id}/confirm")
def api_confirm_output(
    output_id: int,
    body: CutOutputConfirm,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    user = _employee(principal)
    return _call(
        cut_output_service.confirm_output,
        db,
        principal.tenant_id,
        output_id,
        reporter_id=user.id,
        qualified_pairs=body.qualified_pairs,
        defect_pairs=body.defect_pairs,
        completion_mode=body.completion_mode,
        contributions=[row.model_dump() for row in body.contributions],
    )


@router.post("/cut-outputs/{output_id}/cancel")
def api_cancel_output(
    output_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    user = _employee(principal)
    return _call(
        cut_output_service.cancel_output,
        db,
        principal.tenant_id,
        output_id,
        reporter_id=user.id,
    )


@router.get("/cut-outputs/{output_id}")
def api_get_output(
    output_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    _employee(principal)
    return _call(cut_output_service.get_output, db, principal.tenant_id, output_id)


@router.get("/execution-headers/{header_id}/cut-outputs")
def api_list_outputs(
    header_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    _employee(principal)
    return _call(cut_output_service.list_outputs, db, principal.tenant_id, header_id=header_id)
