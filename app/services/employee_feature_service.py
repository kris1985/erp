"""手机功能兼容层：功能码统一映射到角色权限。"""

from sqlalchemy.orm import Session

from app.models import Employee

FEATURES = {
    "production_progress": "生产进度",
    "piecework": "报工记录",
    "salary": "工资",
    "scrap_records": "报废记录",
    "work_report": "报工",
    "scrap": "报废",
    "product_scrap": "成品报废",
    "material_prep": "备料",
    "shared_materials": "物料仓",
    "shared_materials_write": "物料仓入库/领退/盘点",
    "purchase_orders": "物料采购",
    "purchase_orders_submit": "物料采购下单反馈",
    "purchase_orders_loss": "物料采购添加损耗",
    "purchase_orders_receive": "物料采购到货",
    "cut_material_usage": "裁断用料",
    "cut_material_usage_write": "裁断用料应用到产品用量",
    "own_products": "产品开发",
    "own_products_basic_create": "产品开发基础数据录入",
    "own_products_basic_edit": "产品开发基础数据编辑",
    "own_products_route": "产品开发工艺路线编辑",
    "own_products_quote": "产品开发客户报价",
    "own_products_brand_quote": "产品开发品牌报价",
    "own_products_delete": "产品开发删除",
    "own_products_export": "产品开发导出",
    "own_products_copy": "产品开发复制",
    "own_products_history": "产品开发修改记录",
    "own_products_approve": "产品开发审批",
    "expense": "报销",
    "subcontract_out": "外发",
    "subcontract_acceptance": "外发验收",
    "supplier_products": "物料色卡",
    "supplier_products_write": "物料色卡新增/编辑",
    "supplier_products_approve": "物料色卡审批",
    "supplier_products_batch_buy": "物料色卡批量采购",
    "partners": "合作商",
    "partners_customer": "合作商客户",
    "partners_supplier": "合作商供应商",
    "partners_subcontractor": "合作商外加工厂",
    "partners_brand": "合作商品牌",
    "attendance_rules": "考勤规则",
    "attendance_rules_write": "考勤规则编辑",
    "leaves": "请假登记",
    "leaves_write": "请假登记",
    "workers": "员工管理",
    "workers_write": "员工管理新增/编辑",
}

# 手机功能码与角色权限一一对应，不复用电脑端 menu./btn. 权限。
FEATURE_PERMISSION_CODES = {code: f"mobile.{code}" for code in FEATURES}
FEATURE_PERMISSION_CODES["supplier_products_write"] = "mobile.supplier_products.write"
FEATURE_PERMISSION_CODES["supplier_products_approve"] = "mobile.supplier_products.approve"
FEATURE_PERMISSION_CODES["supplier_products_batch_buy"] = "mobile.supplier_products.batch_buy"
FEATURE_PERMISSION_CODES["partners_customer"] = "mobile.partners.customer"
FEATURE_PERMISSION_CODES["partners_supplier"] = "mobile.partners.supplier"
FEATURE_PERMISSION_CODES["partners_subcontractor"] = "mobile.partners.subcontractor"
FEATURE_PERMISSION_CODES["partners_brand"] = "mobile.partners.brand"
FEATURE_PERMISSION_CODES["attendance_rules_write"] = "mobile.attendance_rules.write"
FEATURE_PERMISSION_CODES["leaves_write"] = "mobile.leaves.write"
FEATURE_PERMISSION_CODES["workers_write"] = "mobile.workers.write"
FEATURE_PERMISSION_CODES["shared_materials_write"] = "mobile.shared_materials.write"
FEATURE_PERMISSION_CODES["purchase_orders_submit"] = "mobile.purchase_orders.submit"
FEATURE_PERMISSION_CODES["purchase_orders_loss"] = "mobile.purchase_orders.loss"
FEATURE_PERMISSION_CODES["purchase_orders_receive"] = "mobile.purchase_orders.receive"
FEATURE_PERMISSION_CODES["cut_material_usage_write"] = "mobile.cut_material_usage.write"
FEATURE_PERMISSION_CODES["own_products_basic_create"] = "mobile.own_products.basic_create"
FEATURE_PERMISSION_CODES["own_products_basic_edit"] = "mobile.own_products.basic_edit"
FEATURE_PERMISSION_CODES["own_products_route"] = "mobile.own_products.route"
FEATURE_PERMISSION_CODES["own_products_quote"] = "mobile.own_products.quote"
FEATURE_PERMISSION_CODES["own_products_brand_quote"] = "mobile.own_products.brand_quote"
FEATURE_PERMISSION_CODES["own_products_delete"] = "mobile.own_products.delete"
FEATURE_PERMISSION_CODES["own_products_export"] = "mobile.own_products.export"
FEATURE_PERMISSION_CODES["own_products_copy"] = "mobile.own_products.copy"
FEATURE_PERMISSION_CODES["own_products_history"] = "mobile.own_products.history"
FEATURE_PERMISSION_CODES["own_products_approve"] = "mobile.own_products.approve"


def list_codes(db: Session, employee: Employee) -> list[str]:
    from app.services import rbac_service

    permissions = set(rbac_service.get_employee_permissions(db, employee))
    return sorted(code for code, permission in FEATURE_PERMISSION_CODES.items() if permission in permissions)


def has_feature(db: Session, employee: Employee, code: str) -> bool:
    if code not in FEATURES:
        return False
    return code in list_codes(db, employee)
