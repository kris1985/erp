"""底模：在供应商待结算里直接录入，不做到货。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services.sole_mold_service import SoleMoldError, create_entry, list_molds

router = APIRouter(prefix="/sole-molds", tags=["sole-molds"])


def _http(exc: SoleMoldError) -> HTTPException:
    return HTTPException(status_code=400, detail=exc.message)


class SoleMoldEntryIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    supplier_id: int
    unit_price: Decimal = Field(gt=0)
    qty: int = Field(ge=1, le=100000)
    ordered_at: datetime


@router.get("")
def api_list(
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.payables", "menu.supplier_payments")),
):
    return ok({"items": list_molds(db, user.tenant_id, keyword=keyword)})


@router.post("/entries")
def api_create_entry(
    body: SoleMoldEntryIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.supplier_payments.write")),
):
    try:
        data = create_entry(
            db,
            user.tenant_id,
            code=body.code,
            name=body.name,
            supplier_id=body.supplier_id,
            unit_price=body.unit_price,
            qty=body.qty,
            ordered_at=body.ordered_at,
            user_id=user.id,
        )
    except SoleMoldError as exc:
        raise _http(exc) from exc
    return ok(data)
