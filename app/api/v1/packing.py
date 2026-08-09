"""B2b：装箱计划 + 箱唛 + 验箱 API。"""

from __future__ import annotations

import io

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import PackingCarton, User
from app.schemas.common import ok
from app.services import packing_service
from app.services.packing_service import PackingError

router = APIRouter(tags=["packing"])


class PackingPlanCreate(BaseModel):
    mode: str = Field(description="single_size | mixed")
    pairs_per_carton: int = Field(gt=0, default=12)
    note: str | None = None
    replace_draft: bool = True


class PackingVerifyLine(BaseModel):
    color_id: int | None = None
    size_id: int
    qty: int = Field(ge=0)


class PackingVerifyIn(BaseModel):
    lines: list[PackingVerifyLine]


def _raise(e: PackingError) -> None:
    raise HTTPException(status_code=400, detail=e.message)


def _qr_png_bytes(payload: str) -> bytes:
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.post("/orders/{order_id}/packing-plans")
def create_order_packing_plan(
    order_id: int,
    body: PackingPlanCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            packing_service.create_packing_plan(
                db,
                user.tenant_id,
                order_id,
                mode=body.mode,
                pairs_per_carton=body.pairs_per_carton,
                note=body.note,
                created_by=user.id,
                replace_draft=body.replace_draft,
            )
        )
    except PackingError as e:
        _raise(e)
        return


@router.get("/orders/{order_id}/packing-plans")
def list_order_packing_plans(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ok({"items": packing_service.list_packing_plans(db, user.tenant_id, order_id)})


@router.get("/packing-plans/{plan_id}")
def get_packing_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return ok(packing_service.get_packing_plan(db, user.tenant_id, plan_id))
    except PackingError as e:
        _raise(e)
        return


@router.get("/packing-cartons/by-code/{code}/qr.png")
def packing_carton_qr_png_by_code(code: str, db: Session = Depends(get_db)):
    """公开箱唛二维码（内容=箱码，方便打印与扫码验箱）。"""
    carton = packing_service.get_packing_carton_by_code(db, code)
    if not carton:
        raise HTTPException(status_code=404, detail="箱不存在")
    return Response(
        content=_qr_png_bytes(carton.code),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="carton_{carton.code}.png"'},
    )


@router.get("/packing-cartons/{carton_id}/qr.png")
def packing_carton_qr_png(carton_id: int, db: Session = Depends(get_db)):
    carton = db.get(PackingCarton, carton_id)
    if not carton:
        raise HTTPException(status_code=404, detail="箱不存在")
    return Response(
        content=_qr_png_bytes(carton.code),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="carton_{carton.code}.png"'},
    )


@router.get("/packing-cartons/{carton_id}")
def get_packing_carton(
    carton_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return ok(packing_service.get_packing_carton(db, user.tenant_id, carton_id))
    except PackingError as e:
        _raise(e)
        return


@router.post("/packing-cartons/{carton_id}/verify")
def verify_packing_carton(
    carton_id: int,
    body: PackingVerifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            packing_service.verify_packing_carton(
                db,
                user.tenant_id,
                carton_id,
                lines=[x.model_dump() for x in body.lines],
            )
        )
    except PackingError as e:
        _raise(e)
        return
