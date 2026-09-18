from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services import production_efficiency_service


router = APIRouter(prefix="/production-efficiency", tags=["production-efficiency"])


def _parse_product_codes(
    product_codes: list[str] | None,
    product_code: str | None,
) -> list[str] | None:
    codes: list[str] = []
    if product_codes:
        for item in product_codes:
            codes.extend(part.strip() for part in str(item).split(",") if part.strip())
    if product_code:
        codes.extend(part.strip() for part in product_code.split(",") if part.strip())
    # 去重保序
    seen: set[str] = set()
    ordered: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered or None


@router.get("/recent-products")
def recent_reported_products(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_permissions("menu.production_efficiency")),
):
    """近期有报工的工厂型号（按最近报工时间倒序），供单款平均效率平铺选择。"""
    return ok(
        production_efficiency_service.recent_reported_products(
            db,
            employee.tenant_id,
            date_from=date_from,
            date_to=date_to,
        )
    )


@router.get("/model-avg")
def model_avg_efficiency(
    date_from: date | None = None,
    date_to: date | None = None,
    product_codes: list[str] | None = Query(default=None),
    product_code: str | None = None,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_permissions("menu.production_efficiency")),
):
    """单款平均效率矩阵：日期 ×（工序段→工序），单位双/人/小时。日期倒序。"""
    return ok(
        production_efficiency_service.model_avg_efficiency_matrix(
            db,
            employee.tenant_id,
            date_from=date_from,
            date_to=date_to,
            product_codes=_parse_product_codes(product_codes, product_code),
        )
    )


@router.get("/person-avg")
def person_avg_efficiency(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_permissions("menu.production_efficiency")),
):
    """单人平均效率矩阵：日期 ×（工序段→工序），单位双/人/小时。日期倒序。"""
    return ok(
        production_efficiency_service.person_avg_efficiency_matrix(
            db,
            employee.tenant_id,
            date_from=date_from,
            date_to=date_to,
        )
    )


@router.get("/process-team")
def process_team_efficiency(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_permissions("menu.production_efficiency")),
):
    """工序多人效率矩阵：日期 ×（工序段→工序），单位双/小时。日期倒序。"""
    return ok(
        production_efficiency_service.process_team_efficiency_matrix(
            db,
            employee.tenant_id,
            date_from=date_from,
            date_to=date_to,
        )
    )


@router.get("/personal")
def personal_efficiency(
    date_from: date | None = None,
    date_to: date | None = None,
    segment_id: int | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_permissions("menu.production_efficiency")),
):
    """个人效率：日期 ×（工序→员工产量双 / 损失元）。按工序段切换，日期倒序。"""
    return ok(
        production_efficiency_service.personal_output_matrix(
            db,
            employee.tenant_id,
            date_from=date_from,
            date_to=date_to,
            segment_id=segment_id,
            include_inactive=include_inactive,
        )
    )


@router.get("/department")
def department_efficiency(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_permissions("menu.production_efficiency")),
):
    """部门效率矩阵：日期 ×（部门→上班时间/产量/效率）。效率为几′几″/双。日期倒序。"""
    return ok(
        production_efficiency_service.department_efficiency_matrix(
            db,
            employee.tenant_id,
            date_from=date_from,
            date_to=date_to,
        )
    )
