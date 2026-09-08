"""现场功能按员工直接授权。"""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Employee, EmployeeFeaturePermission

FEATURES = {
    "claim_task": "领任务",
    "register_defect": "不良登记",
    "material_issue": "领料",
    "subcontract_out": "外发",
    "subcontract_acceptance": "外发验收",
}


def list_codes(db: Session, employee: Employee) -> list[str]:
    return sorted(db.scalars(select(EmployeeFeaturePermission.feature_code).where(
        EmployeeFeaturePermission.tenant_id == employee.tenant_id,
        EmployeeFeaturePermission.employee_id == employee.id,
    )).all())


def set_codes(db: Session, employee: Employee, codes: list[str]) -> list[str]:
    cleaned = sorted({str(code) for code in codes if str(code) in FEATURES})
    db.execute(delete(EmployeeFeaturePermission).where(
        EmployeeFeaturePermission.tenant_id == employee.tenant_id,
        EmployeeFeaturePermission.employee_id == employee.id,
    ))
    for code in cleaned:
        db.add(EmployeeFeaturePermission(
            tenant_id=employee.tenant_id,
            employee_id=employee.id,
            feature_code=code,
        ))
    db.flush()
    return cleaned


def is_configured(db: Session, tenant_id: int) -> bool:
    return bool(db.scalar(select(func.count()).select_from(EmployeeFeaturePermission).where(
        EmployeeFeaturePermission.tenant_id == tenant_id
    )))


def has_feature(db: Session, employee: Employee, code: str) -> bool:
    if code not in FEATURES:
        return False
    return bool(db.scalar(select(EmployeeFeaturePermission.id).where(
        EmployeeFeaturePermission.tenant_id == employee.tenant_id,
        EmployeeFeaturePermission.employee_id == employee.id,
        EmployeeFeaturePermission.feature_code == code,
    ).limit(1)))
