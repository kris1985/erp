"""人事工资加减项：奖惩、预支、迟到重算、发薪日配置。"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_permissions, require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services import hr_service, payroll_settings
from app.services.report_service import ReportError

router = APIRouter(tags=["hr"])


def _http_from_err(err: Exception) -> HTTPException:
    if isinstance(err, ReportError):
        return HTTPException(status_code=400, detail=err.message)
    msg = str(err)
    code_map = {
        "not_found": (404, "记录不存在"),
        "worker_not_found": (400, "员工不存在"),
        "year_month_invalid": (400, "月份格式应为 YYYY-MM"),
        "kind_invalid": (400, "类型无效"),
        "category_invalid": (400, "分类无效"),
        "amount_invalid": (400, "金额须大于 0"),
        "auto_readonly": (400, "自动生成项不可手工修改"),
        "advance_linked": (400, "预支扣回请从预支作废"),
        "payday_invalid": (400, "发薪日须为 1–28"),
        "tenant_not_found": (404, "租户不存在"),
    }
    status, detail = code_map.get(msg, (400, msg))
    return HTTPException(status_code=status, detail=detail)


class AdjustmentIn(BaseModel):
    worker_id: int
    year_month: str
    kind: str = Field(description="reward | penalty")
    amount: float
    category: str = "other"
    title: str | None = None
    notes: str | None = None
    occurred_on: date | None = None


class AdjustmentPatchIn(BaseModel):
    kind: str | None = None
    category: str | None = None
    amount: float | None = None
    title: str | None = None
    notes: str | None = None
    occurred_on: date | None = None
    year_month: str | None = None


class AdvanceIn(BaseModel):
    worker_id: int
    amount: float
    repay_year_month: str
    advanced_at: date | None = None
    notes: str | None = None


class PayrollPatchIn(BaseModel):
    payday: int | None = Field(default=None, ge=1, le=28)


@router.get("/worker-adjustments")
def api_list_adjustments(
    year_month: str | None = None,
    worker_id: int | None = None,
    kind: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.adjustments")),
):
    return ok(
        hr_service.list_adjustments(
            db,
            user.tenant_id,
            year_month=year_month,
            worker_id=worker_id,
            kind=kind,
            category=category,
        )
    )


@router.post("/worker-adjustments")
def api_create_adjustment(
    body: AdjustmentIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.adjustments.write")),
):
    try:
        data = hr_service.create_adjustment(
            db,
            user.tenant_id,
            worker_id=body.worker_id,
            year_month=body.year_month,
            kind=body.kind,
            amount=body.amount,
            category=body.category,
            title=body.title,
            notes=body.notes,
            occurred_on=body.occurred_on,
            created_by=user.id,
        )
    except (ValueError, ReportError) as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.patch("/worker-adjustments/{adjustment_id}")
def api_patch_adjustment(
    adjustment_id: int,
    body: AdjustmentPatchIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.adjustments.write")),
):
    patch = body.model_dump(exclude_unset=True)
    if "occurred_on" in patch and patch["occurred_on"] is not None:
        patch["occurred_on"] = patch["occurred_on"].isoformat()
    try:
        data = hr_service.update_adjustment(db, user.tenant_id, adjustment_id, patch=patch)
    except (ValueError, ReportError) as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.delete("/worker-adjustments/{adjustment_id}")
def api_delete_adjustment(
    adjustment_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.adjustments.write")),
):
    try:
        hr_service.delete_adjustment(db, user.tenant_id, adjustment_id)
    except (ValueError, ReportError) as err:
        raise _http_from_err(err) from err
    return ok({"deleted": True})


@router.get("/salary-advances")
def api_list_advances(
    repay_year_month: str | None = None,
    worker_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.advances")),
):
    return ok(
        hr_service.list_advances(
            db,
            user.tenant_id,
            repay_year_month=repay_year_month,
            worker_id=worker_id,
            status=status,
        )
    )


@router.post("/salary-advances")
def api_create_advance(
    body: AdvanceIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.advances.write")),
):
    try:
        data = hr_service.create_advance(
            db,
            user.tenant_id,
            worker_id=body.worker_id,
            amount=body.amount,
            repay_year_month=body.repay_year_month,
            advanced_at=body.advanced_at,
            notes=body.notes,
            created_by=user.id,
        )
    except (ValueError, ReportError) as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.post("/salary-advances/{advance_id}/void")
def api_void_advance(
    advance_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.advances.write")),
):
    try:
        data = hr_service.void_advance(db, user.tenant_id, advance_id)
    except (ValueError, ReportError) as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.post("/salary/rebuild-late-deductions")
def api_rebuild_late(
    body: dict[str, Any],
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.adjustments.write")),
):
    ym = str(body.get("year_month") or "").strip()
    try:
        data = hr_service.rebuild_late_deductions(
            db, user.tenant_id, ym, created_by=user.id
        )
    except (ValueError, ReportError) as err:
        raise _http_from_err(err) from err
    return ok(data)


@router.get("/payroll-settings")
def api_get_payroll(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    return ok(payroll_settings.get_payroll_by_tenant_id(db, user.tenant_id))


@router.patch("/payroll-settings")
def api_patch_payroll(
    body: PayrollPatchIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    patch = body.model_dump(exclude_unset=True)
    try:
        data = payroll_settings.save_payroll_patch(db, user.tenant_id, patch)
    except (ValueError, ReportError) as err:
        raise _http_from_err(err) from err
    return ok(data)
