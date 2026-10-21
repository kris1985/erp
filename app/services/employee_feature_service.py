"""手机功能兼容层：功能码统一映射到角色权限。"""

from sqlalchemy.orm import Session

from app.models import Employee

FEATURES = {
    "claim_task": "领任务",
    "register_defect": "不良登记",
    "material_issue": "领料",
    "material_prep": "备料",
    "expense": "报销",
    "subcontract_out": "外发",
    "subcontract_acceptance": "外发验收",
    "supplier_products": "物料色卡",
    "supplier_products_write": "物料色卡新增/编辑",
    "supplier_products_approve": "物料色卡审批",
    "partners": "合作商",
    "partners_write": "合作商新增/编辑",
    "attendance_rules": "考勤规则",
    "attendance_rules_write": "考勤规则编辑",
}

# 手机功能码与角色权限一一对应，不复用电脑端 menu./btn. 权限。
FEATURE_PERMISSION_CODES = {code: f"mobile.{code}" for code in FEATURES}
FEATURE_PERMISSION_CODES["supplier_products_write"] = "mobile.supplier_products.write"
FEATURE_PERMISSION_CODES["supplier_products_approve"] = "mobile.supplier_products.approve"
FEATURE_PERMISSION_CODES["partners_write"] = "mobile.partners.write"
FEATURE_PERMISSION_CODES["attendance_rules_write"] = "mobile.attendance_rules.write"


def list_codes(db: Session, employee: Employee) -> list[str]:
    from app.services import rbac_service

    permissions = set(rbac_service.get_employee_permissions(db, employee))
    return sorted(code for code, permission in FEATURE_PERMISSION_CODES.items() if permission in permissions)


def has_feature(db: Session, employee: Employee, code: str) -> bool:
    if code not in FEATURES:
        return False
    return code in list_codes(db, employee)
