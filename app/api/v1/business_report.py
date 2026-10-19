"""经营报告。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_permissions, require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.api import ApplyCutAverageIn, RestoreMaterialUsageIn
from app.schemas.common import ok
from app.services import business_report_service, cut_material_usage_service
from app.services.material_usage_history_service import (
    MaterialUsageApplyError,
    apply_cut_average,
    restore_material_usage,
)

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


@router.get("/business-report/cut-material-models")
def api_cut_material_models(
    db: Session = Depends(get_db),
    user: Employee = Depends(
        require_permissions(
            "menu.business_report",
            "menu.profit",
            "menu.orders",
            "menu.sales_orders",
        )
    ),
):
    """裁断用料的工厂型号下拉，不跑用料汇总。"""
    return ok(cut_material_usage_service.factory_model_options(db, user.tenant_id))


@router.get("/business-report/cut-material-usage")
def api_cut_material_usage(
    date_from: date | None = None,
    date_to: date | None = None,
    factory_model: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(
        require_permissions(
            "menu.business_report",
            "menu.profit",
            "menu.orders",
            "menu.sales_orders",
        )
    ),
):
    """裁断用料：默认全部，可按工厂型号收窄。只计裁断段已签收领料和有效合格报工。"""
    return ok(
        cut_material_usage_service.cut_material_usage(
            db,
            user.tenant_id,
            date_from=date_from,
            date_to=date_to,
            factory_model=factory_model,
        )
    )


@router.post("/business-report/cut-material-usage/apply")
def api_apply_cut_average(
    body: ApplyCutAverageIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """把当前实际平均用量覆盖到该产品裁断用料的对应物料，并记用量历史。"""
    try:
        result = apply_cut_average(
            db,
            user.tenant_id,
            own_product_id=body.own_product_id,
            supplier_product_id=body.supplier_product_id,
            date_from=body.date_from,
            date_to=body.date_to,
            changed_by=user.id,
        )
    except MaterialUsageApplyError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    db.commit()
    return ok(result)


@router.post("/business-report/cut-material-usage/restore")
def api_restore_material_usage(
    body: RestoreMaterialUsageIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """按一条用量历史，把产品裁断用料改回当时的用量。"""
    try:
        result = restore_material_usage(
            db,
            user.tenant_id,
            history_id=body.history_id,
            changed_by=user.id,
        )
    except MaterialUsageApplyError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    db.commit()
    return ok(result)
