"""手机功能兼容层：功能码统一映射到角色权限。"""

from sqlalchemy.orm import Session

from app.models import Employee

FEATURES = {
    "claim_task": "领任务",
    "register_defect": "不良登记",
    "material_issue": "领料",
    "subcontract_out": "外发",
    "subcontract_acceptance": "外发验收",
}

FEATURE_PERMISSION_CODES = {code: f"mobile.{code}" for code in FEATURES}


def list_codes(db: Session, employee: Employee) -> list[str]:
    from app.services import rbac_service

    permissions = set(rbac_service.get_employee_permissions(db, employee))
    return sorted(code for code, permission in FEATURE_PERMISSION_CODES.items() if permission in permissions)


def has_feature(db: Session, employee: Employee, code: str) -> bool:
    if code not in FEATURES:
        return False
    return code in list_codes(db, employee)
