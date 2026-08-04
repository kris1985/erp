from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import Color, PriceType, Size, Style, StyleProcessRoute, User
from app.schemas.api import ColorOut, RouteCreate, RouteOut, SizeOut, StyleCreate, StyleOut
from app.schemas.common import ok

router = APIRouter(tags=["styles"])


@router.get("/styles")
def list_styles(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Style).where(Style.tenant_id == user.tenant_id).order_by(Style.id.desc())).all()
    items = [StyleOut.model_validate(r).model_dump() for r in rows]
    return ok({"items": items, "total": len(items)})


@router.post("/styles")
def create_style(body: StyleCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = Style(
        tenant_id=user.tenant_id,
        style_code=body.style_code,
        style_name=body.style_name,
        default_color=body.default_color,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return ok(StyleOut.model_validate(s).model_dump())


@router.get("/routes")
def list_routes(style_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(StyleProcessRoute).where(StyleProcessRoute.tenant_id == user.tenant_id)
    if style_id:
        q = q.where(StyleProcessRoute.style_id == style_id)
    rows = db.scalars(q.order_by(StyleProcessRoute.seq)).all()
    items = [
        RouteOut(
            id=r.id,
            style_id=r.style_id,
            process_id=r.process_id,
            seq=r.seq,
            price=r.price,
            price_type=r.price_type.value if hasattr(r.price_type, "value") else str(r.price_type),
            is_active=r.is_active,
        ).model_dump()
        for r in rows
    ]
    return ok({"items": items, "total": len(items)})


@router.post("/routes")
def create_route(body: RouteCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = StyleProcessRoute(
        tenant_id=user.tenant_id,
        style_id=body.style_id,
        process_id=body.process_id,
        seq=body.seq,
        price=body.price,
        price_type=PriceType(body.price_type) if body.price_type in PriceType.__members__ else PriceType.normal,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return ok(
        RouteOut(
            id=r.id,
            style_id=r.style_id,
            process_id=r.process_id,
            seq=r.seq,
            price=r.price,
            price_type=r.price_type.value,
            is_active=r.is_active,
        ).model_dump()
    )


@router.get("/colors")
def list_colors(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Color).where(Color.tenant_id == user.tenant_id)).all()
    return ok({"items": [ColorOut.model_validate(r).model_dump() for r in rows], "total": len(rows)})


@router.get("/sizes")
def list_sizes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Size).where(Size.tenant_id == user.tenant_id).order_by(Size.sort_order)).all()
    return ok({"items": [SizeOut.model_validate(r).model_dump() for r in rows], "total": len(rows)})
