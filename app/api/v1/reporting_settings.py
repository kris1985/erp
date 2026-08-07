"""租户报工规则。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import Tenant, User
from app.schemas.common import ok
from app.services import reporting_settings

router = APIRouter(prefix="/reporting-settings", tags=["reporting-settings"])


class ReportingPatchIn(BaseModel):
    allow_unassigned_report: bool | None = None
    rework_pays: bool | None = None
    allow_over_plan: bool | None = None
    over_plan_requires_confirm: bool | None = None


@router.get("")
def get_reporting_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    tenant = db.get(Tenant, user.tenant_id)
    return ok(reporting_settings.get_reporting_for_tenant(tenant))


@router.patch("")
def patch_reporting_settings(
    body: ReportingPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无有效更新字段")
    try:
        return ok(reporting_settings.save_reporting_patch(db, user.tenant_id, patch))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
