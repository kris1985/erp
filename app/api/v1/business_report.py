"""经营报告。"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services import business_report_service

router = APIRouter(tags=["business-report"])


@router.get("/business-report")
def api_business_report(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.business_report", "menu.profit")),
):
    """按日期范围汇总出货量、综合利润、报废率、损失与开发成本。"""
    return ok(
        business_report_service.business_report(
            db,
            user.tenant_id,
            date_from=date_from,
            date_to=date_to,
        )
    )
