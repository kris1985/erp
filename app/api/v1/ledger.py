"""总账经营流水。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app.db import get_db
from app.models import Employee
from app.schemas.common import normalize_page, ok
from app.services import ledger_service

router = APIRouter(tags=["ledger"])


@router.get("/ledger")
def api_list_ledger(
    date_from: date | None = None,
    date_to: date | None = None,
    biz_type: str | None = None,
    include_void: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.ledger")),
):
    page, page_size, _ = normalize_page(page, page_size)
    data = ledger_service.list_entries(
        db,
        user.tenant_id,
        date_from=date_from,
        date_to=date_to,
        biz_type=biz_type,
        status=None if include_void else "posted",
        include_void=include_void,
        page=page,
        page_size=page_size,
    )
    return ok(data)


@router.get("/ledger/export")
def api_export_ledger(
    date_from: date | None = None,
    date_to: date | None = None,
    biz_type: str | None = None,
    include_void: bool = Query(False),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.ledger", "btn.ledger.export")),
):
    csv_text = ledger_service.export_csv(
        db,
        user.tenant_id,
        date_from=date_from,
        date_to=date_to,
        biz_type=biz_type,
        include_void=include_void,
    )
    filename = f"ledger-{(date_from or '')}-{(date_to or '')}.csv".replace("--", "-")
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/ledger/meta")
def api_ledger_meta(
    user: Employee = Depends(require_permissions("menu.ledger")),
):
    _ = user
    return ok(
        {
            "biz_types": [
                {"value": k, "label": ledger_service.BIZ_TYPE_LABELS[k]}
                for k in ledger_service.CASH_BIZ_TYPES
            ],
            "fund_accounts": [
                {"value": k, "label": v} for k, v in ledger_service.FUND_ACCOUNT_LABELS.items()
            ],
        }
    )
