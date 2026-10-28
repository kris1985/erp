"""手机功能兼容层：功能码统一映射到角色权限。"""

from sqlalchemy.orm import Session

from app.models import Employee

FEATURES = {
    "claim_task": "领任务",
    "register_defect": "不良登记",
    "material_issue": "领料",
    "material_prep": "备料",
    "shared_materials": "物料仓",
    "shared_materials_write": "物料仓入库/领退/盘点",
    "purchase_orders": "物料采购",
    "purchase_orders_write": "物料采购下单反馈/损耗/到货",
    "cut_material_usage": "裁断用料",
    "cut_material_usage_write": "裁断用料应用到产品用量",
    "own_products": "产品开发",
    "own_products_write": "产品开发录入基础信息",
    "own_products_approve": "产品开发审批",
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
    "leaves": "请假登记",
    "leaves_write": "请假登记",
}

# 手机功能码与角色权限一一对应，不复用电脑端 menu./btn. 权限。
FEATURE_PERMISSION_CODES = {code: f"mobile.{code}" for code in FEATURES}
FEATURE_PERMISSION_CODES["supplier_products_write"] = "mobile.supplier_products.write"
FEATURE_PERMISSION_CODES["supplier_products_approve"] = "mobile.supplier_products.approve"
FEATURE_PERMISSION_CODES["partners_write"] = "mobile.partners.write"
FEATURE_PERMISSION_CODES["attendance_rules_write"] = "mobile.attendance_rules.write"
FEATURE_PERMISSION_CODES["leaves_write"] = "mobile.leaves.write"
FEATURE_PERMISSION_CODES["shared_materials_write"] = "mobile.shared_materials.write"
FEATURE_PERMISSION_CODES["purchase_orders_write"] = "mobile.purchase_orders.write"
FEATURE_PERMISSION_CODES["cut_material_usage_write"] = "mobile.cut_material_usage.write"
FEATURE_PERMISSION_CODES["own_products_write"] = "mobile.own_products.write"
FEATURE_PERMISSION_CODES["own_products_approve"] = "mobile.own_products.approve"


def list_codes(db: Session, employee: Employee) -> list[str]:
    from app.services import rbac_service

    permissions = set(rbac_service.get_employee_permissions(db, employee))
    return sorted(code for code, permission in FEATURE_PERMISSION_CODES.items() if permission in permissions)


def has_feature(db: Session, employee: Employee, code: str) -> bool:
    if code not in FEATURES:
        return False
    return code in list_codes(db, employee)
