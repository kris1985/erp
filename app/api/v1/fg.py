"""AU-I2：成品仓 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import User
from app.schemas.common import ok
from app.services import fg_service
from app.services.fg_service import FgError

router = APIRouter(prefix="/fg-stocks", tags=["fg"])


@router.get("")
def api_list_fg_stocks(
    q: str | None = Query(None),
    only_positive: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    items = fg_service.list_fg_stocks(
        db,
        tenant_id=user.tenant_id,
        q=q,
        only_positive=only_positive,
        limit=limit,
    )
    return ok({"items": items, "total": len(items)})


@router.get("/{fg_stock_id}/ledgers")
def api_list_fg_ledgers(
    fg_stock_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader", "warehouse")),
):
    try:
        items = fg_service.list_fg_ledgers(
            db, tenant_id=user.tenant_id, fg_stock_id=fg_stock_id, limit=limit
        )
    except FgError as e:
        raise HTTPException(status_code=404, detail=e.message) from e
    return ok({"items": items, "total": len(items)})
