"""租户角色与权限：内置职能角色自动灌库；用户可多角色（权限并集）。"""

from __future__ import annotations

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Department, Employee, EmployeeRoleAssignment, RolePermission, TenantRole
from app.permissions import (
    ROLES,
    all_permission_codes,
    default_permissions_for_role,
    permission_catalog,
    permission_tree_for_ui,
    pick_primary_role,
)


class RbacError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
# API 天花板仅两档；细权靠菜单权限
_BASE_ROLES = ("admin", "manager", "worker")
_SYSTEM_ROLE_CODES = {r["code"] for r in ROLES}
_LEGACY_LEADER = "leader"
_LEGACY_MERCHANDISER = "merchandiser"
_MOBILE_PERMISSION_MARKER = "__mobile_role_permissions_v1__"
_MOBILE_EXPENSE_MARKER = "__mobile_expense_permission_v1__"
_MOBILE_CATALOG_MARKER = "__mobile_supplier_products_permission_v1__"
_MOBILE_CATALOG_CODES = {
    "mobile.supplier_products",
    "mobile.supplier_products.write",
    "mobile.supplier_products.approve",
}
_MOBILE_CATALOG_BUY_MARKER = "__mobile_supplier_products_batch_buy_v1__"
_MOBILE_CATALOG_BUY_CODES = {"mobile.supplier_products.batch_buy"}
_MOBILE_PARTNERS_MARKER = "__mobile_partners_permission_v1__"
_MOBILE_PARTNERS_CODES = {
    "mobile.partners",
    "mobile.partners.customer",
    "mobile.partners.supplier",
    "mobile.partners.subcontractor",
    "mobile.partners.brand",
}
_MOBILE_PARTNER_ACTION_MARKER = "__mobile_partner_type_permissions_v1__"
_MOBILE_PARTNER_ACTIONS = (
    "mobile.partners.customer",
    "mobile.partners.supplier",
    "mobile.partners.subcontractor",
    "mobile.partners.brand",
)
_MOBILE_ATTENDANCE_MARKER = "__mobile_attendance_rules_permission_v1__"
_MOBILE_ATTENDANCE_CODES = {
    "mobile.attendance_rules",
    "mobile.attendance_rules.write",
}
_MOBILE_LEAVE_MARKER = "__mobile_leaves_permission_v1__"
_MOBILE_LEAVE_CODES = {
    "mobile.leaves",
    "mobile.leaves.write",
}
_MOBILE_WORKERS_MARKER = "__mobile_workers_permission_v1__"
_MOBILE_WORKERS_CODES = {
    "mobile.workers",
    "mobile.workers.write",
}
_MOBILE_PREP_MARKER = "__mobile_material_prep_permission_v1__"
_MOBILE_PREP_CODES = {"mobile.material_prep"}
_MOBILE_WAREHOUSE_MARKER = "__mobile_shared_materials_permission_v1__"
_MOBILE_WAREHOUSE_CODES = {
    "mobile.shared_materials",
    "mobile.shared_materials.write",
}
_MOBILE_PURCHASE_MARKER = "__mobile_purchase_orders_permission_v1__"
_MOBILE_PURCHASE_CODES = {
    "mobile.purchase_orders",
    "mobile.purchase_orders.submit",
    "mobile.purchase_orders.loss",
    "mobile.purchase_orders.receive",
}
_MOBILE_PO_ACTION_MARKER = "__mobile_purchase_order_actions_v1__"
_MOBILE_PO_ACTIONS = (
    "mobile.purchase_orders.submit",
    "mobile.purchase_orders.loss",
    "mobile.purchase_orders.receive",
)
_MOBILE_CUT_USAGE_MARKER = "__mobile_cut_material_usage_permission_v1__"
_MOBILE_CUT_USAGE_CODES = {
    "mobile.cut_material_usage",
    "mobile.cut_material_usage.write",
}
_MOBILE_OWN_PRODUCT_MARKER = "__mobile_own_products_permission_v1__"
_MOBILE_OWN_PRODUCT_CODES = {
    "mobile.own_products",
    "mobile.own_products.basic_create",
    "mobile.own_products.basic_edit",
    "mobile.own_products.route",
    "mobile.own_products.quote",
    "mobile.own_products.brand_quote",
    "mobile.own_products.approve",
}
_OWN_PRODUCT_SECTION_MARKER = "__own_product_section_permissions_v1__"
_OWN_PRODUCT_PC_SECTIONS = (
    "btn.own_products.basic_create",
    "btn.own_products.basic_edit",
    "btn.own_products.route",
    "btn.own_products.quote",
    "btn.own_products.brand_quote",
)
_OWN_PRODUCT_MOBILE_SECTIONS = (
    "mobile.own_products.basic_create",
    "mobile.own_products.basic_edit",
    "mobile.own_products.route",
    "mobile.own_products.quote",
    "mobile.own_products.brand_quote",
)
_OWN_PRODUCT_ACTION_MARKER = "__own_product_action_permissions_v1__"
_MOBILE_FLOOR_MARKER = "__mobile_floor_report_permission_v1__"
_PARTNER_CATEGORY_MARKER = "__partner_category_permissions_v1__"
_PARTNER_CATEGORY_COPIES = {
    "menu.masters": "menu.brands",
    "btn.masters.write": "btn.brands.write",
    "menu.subcontract_out": "menu.subcontractors",
    "btn.subcontract_out.write": "btn.subcontractors.write",
}
_TOOLING_PERMISSION_MARKER = "__warehouse_tooling_permissions_v1__"
_TOOLING_PERMISSION_COPIES = {
    "menu.shared_materials": "menu.tooling",
    "btn.shared_materials.write": "btn.tooling.write",
}
# PC 裁断用料从生产进度菜单拆出。只补一次，之后允许单独取消。
_PC_CUT_USAGE_MARKER = "__pc_cut_material_usage_permission_v1__"
_PC_CUT_USAGE_APPLY_ROLES = frozenset(
    {"manager", "general_manager", "deputy_manager"}
)
_CATALOG_BUY_MARKER = "__supplier_products_batch_buy_v1__"
_SALES_ORDER_ACTION_MARKER = "__sales_order_action_permissions_v1__"
_SALES_ORDER_ACTION_CODES = (
    "btn.sales_orders.confirm",
    "btn.sales_orders.merge",
    "btn.sales_orders.auto_merge",
    "btn.sales_orders.cancel",
)
_SAMPLE_REMAKE_MARKER = "__sample_remake_permissions_v1__"
_SAMPLE_REMAKE_COPIES = {
    "menu.own_products": "menu.sample_remakes",
    "btn.own_products.write": "btn.sample_remakes.write",
}
_FG_BUTTON_MARKER = "__fg_stock_button_permissions_v1__"
_FG_BUTTON_CODES = ("btn.fg_stocks.ship", "btn.fg_stocks.defective")
_FG_SHIPPED_ACTION_MARKER = "__fg_shipped_action_permissions_v1__"
_FG_SHIPPED_VIEW_CODES = ("btn.fg_stocks.print", "btn.fg_stocks.export")
_FG_SHIPPED_WRITE_CODES = ("btn.fg_stocks.logistics", "btn.fg_stocks.return")
_DEFECT_BUTTON_MARKER = "__defect_button_permissions_v1__"
_DEFECT_BUTTON_CODES = (
    "btn.defects.confirm",
    "btn.defects.edit",
    "btn.defects.delete",
    "btn.defects.print",
)
_MOBILE_FLOOR_CODES = {
    "mobile.work_report",
    "mobile.scrap",
    "mobile.product_scrap",
}
# 首页原先不看权限就会显示的入口。只补一次，之后允许单独取消。
_MOBILE_HOME_MARKER = "__mobile_home_entry_permissions_v1__"
_MOBILE_HOME_CODES = (
    "mobile.production_progress",
    "mobile.piecework",
    "mobile.salary",
    "mobile.scrap_records",
)
# 报废记录和「报废」分开。首页原先不看权限就会显示，只补一次。
_MOBILE_SCRAP_RECORDS_MARKER = "__mobile_scrap_records_permission_v1__"
_SPLIT_PURCHASING_MARKER = "__split_purchasing_role_v1__"
# 一次性：把当时已有的自定义角色改成内置。之后新建的角色仍是自定义。
_PROMOTE_EXISTING_ROLES_MARKER = "__promote_existing_roles_system_v1__"
# 一次性：给后加的内置角色灌默认权限（角色行已有、权限却是空的）。
_SEED_NEW_SYSTEM_ROLES_MARKER = "__seed_floor_and_gm_roles_v1__"
_SEED_NEW_SYSTEM_ROLE_CODES = (
    "general_manager",
    "deputy_manager",
    "cutting_supervisor",
    "upper_supervisor",
    "bottom_supervisor",
    "cutting_worker",
)
_PROCESS_STAFF_MARKER = "__process_staff_permission_v1__"
_PO_ACTION_MARKER = "__purchase_order_action_permissions_v1__"
_AFTER_SALES_ACTION_MARKER = "__after_sales_action_permissions_v1__"
_ORDER_PROFIT_MARKER = "__order_profit_permission_v1__"
_AFTER_SALES_ACTIONS = (
    "btn.after_sales.create",
    "btn.after_sales.edit",
    "btn.after_sales.delete",
    "btn.after_sales.complete",
    "btn.after_sales.refund",
    "btn.after_sales.repair",
    "btn.after_sales.remake",
)
_SUBCONTRACT_SETTLEMENT_MARKER = "__subcontract_settlement_permission_v1__"
_PO_WRITE_CODES = (
    "btn.purchase_orders.export",
    "btn.purchase_orders.print",
    "btn.purchase_orders.loss",
    "btn.purchase_orders.submit",
    "btn.purchase_orders.receive",
    "btn.purchase_orders.unsubscribe",
    "btn.purchase_orders.cancel",
)
_PO_VIEW_CODES = ("btn.purchase_orders.export", "btn.purchase_orders.print")


def _valid_codes() -> set[str]:
    return set(all_permission_codes())


def _role_permission_codes(db: Session, tenant_id: int) -> dict[str, set[str]]:
    """已落库的角色权限。Session 关闭了自动刷新，先 flush 才能看到本轮刚加入的默认权限。"""
    db.flush()
    grants = db.scalars(
        select(RolePermission).where(RolePermission.tenant_id == tenant_id)
    ).all()
    by_role: dict[str, set[str]] = {}
    for row in grants:
        by_role.setdefault(row.role, set()).add(row.perm_code)
    return by_role


def ensure_system_roles(db: Session, tenant_id: int) -> None:
    """灌入内置角色及其默认权限；迁移废弃的用户·组长。"""
    mobile_permissions_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_PERMISSION_MARKER,
            ).limit(1)
        )
    )
    expense_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_EXPENSE_MARKER,
            ).limit(1)
        )
    )
    catalog_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_CATALOG_MARKER,
            ).limit(1)
        )
    )
    catalog_buy_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_CATALOG_BUY_MARKER,
            ).limit(1)
        )
    )
    partners_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_PARTNERS_MARKER,
            ).limit(1)
        )
    )
    attendance_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_ATTENDANCE_MARKER,
            ).limit(1)
        )
    )
    leave_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_LEAVE_MARKER,
            ).limit(1)
        )
    )
    workers_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_WORKERS_MARKER,
            ).limit(1)
        )
    )
    prep_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_PREP_MARKER,
            ).limit(1)
        )
    )
    warehouse_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_WAREHOUSE_MARKER,
            ).limit(1)
        )
    )
    purchase_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_PURCHASE_MARKER,
            ).limit(1)
        )
    )
    cut_usage_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_CUT_USAGE_MARKER,
            ).limit(1)
        )
    )
    own_product_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_OWN_PRODUCT_MARKER,
            ).limit(1)
        )
    )
    floor_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_FLOOR_MARKER,
            ).limit(1)
        )
    )
    home_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_HOME_MARKER,
            ).limit(1)
        )
    )
    for r in ROLES:
        row = db.scalar(
            select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.code == r["code"])
        )
        base = r.get("base_role") or r["code"]
        role_created = row is None
        if not row:
            db.add(
                TenantRole(
                    tenant_id=tenant_id,
                    code=r["code"],
                    name=r["name"],
                    description=r.get("description"),
                    base_role=base,
                    is_system=True,
                    is_active=True,
                )
            )
            db.flush()
        else:
            row.name = r["name"]
            row.description = r.get("description")
            row.base_role = base
            row.is_system = True
            row.is_active = True

        if r["code"] == "admin":
            continue
        existing_codes = set(
            db.scalars(
                select(RolePermission.perm_code).where(
                    RolePermission.tenant_id == tenant_id,
                    RolePermission.role == r["code"],
                )
            ).all()
        )
        for code in default_permissions_for_role(r["code"]):
            if code in existing_codes:
                continue
            # 已有角色不再补回被取消的电脑端权限。新权限只靠下面的一次性迁移补一次。
            # 否则保存后刷新会把勾选写回去；角色列表和权限矩阵同时刷新时还会撞上唯一键报错。
            if not role_created and not code.startswith("mobile."):
                continue
            # 手机权限仅在角色首次创建或本次版本迁移时灌入；之后允许管理员取消。
            if code.startswith("mobile.") and not role_created and mobile_permissions_seeded:
                allow_new_mobile = (code == "mobile.expense" and not expense_permission_seeded) or (
                    code in _MOBILE_CATALOG_CODES and not catalog_permission_seeded
                ) or (
                    code in _MOBILE_CATALOG_BUY_CODES and not catalog_buy_permission_seeded
                ) or (
                    code in _MOBILE_PARTNERS_CODES and not partners_permission_seeded
                ) or (
                    code in _MOBILE_ATTENDANCE_CODES and not attendance_permission_seeded
                ) or (
                    code in _MOBILE_LEAVE_CODES and not leave_permission_seeded
                ) or (
                    code in _MOBILE_WORKERS_CODES and not workers_permission_seeded
                ) or (
                    code in _MOBILE_PREP_CODES and not prep_permission_seeded
                ) or (
                    code in _MOBILE_WAREHOUSE_CODES and not warehouse_permission_seeded
                ) or (
                    code in _MOBILE_PURCHASE_CODES and not purchase_permission_seeded
                ) or (
                    code in _MOBILE_CUT_USAGE_CODES and not cut_usage_permission_seeded
                ) or (
                    code in _MOBILE_OWN_PRODUCT_CODES and not own_product_permission_seeded
                ) or (
                    code in _MOBILE_FLOOR_CODES and not floor_permission_seeded
                )
                if not allow_new_mobile:
                    continue
            db.add(RolePermission(tenant_id=tenant_id, role=r["code"], perm_code=code))

    if not mobile_permissions_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_PERMISSION_MARKER,
            )
        )
    if not expense_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_EXPENSE_MARKER,
            )
        )
    if not catalog_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_CATALOG_MARKER,
            )
        )
    if not catalog_buy_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_CATALOG_BUY_MARKER,
            )
        )
    if not partners_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_PARTNERS_MARKER,
            )
        )
    if not attendance_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_ATTENDANCE_MARKER,
            )
        )
    if not leave_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_LEAVE_MARKER,
            )
        )
    if not workers_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_WORKERS_MARKER,
            )
        )
    if not prep_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_PREP_MARKER,
            )
        )
    if not warehouse_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_WAREHOUSE_MARKER,
            )
        )
    if not purchase_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_PURCHASE_MARKER,
            )
        )
    if not cut_usage_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_CUT_USAGE_MARKER,
            )
        )
    if not own_product_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_OWN_PRODUCT_MARKER,
            )
        )
    if not floor_permission_seeded:
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_FLOOR_MARKER,
            )
        )
    # 已有角色（含自定义角色）当前都能看见这些首页入口，补一次后即可单独取消。
    if not home_permission_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        role_codes = set(by_role)
        role_codes.update(
            db.scalars(select(TenantRole.code).where(TenantRole.tenant_id == tenant_id)).all()
        )
        for role in role_codes:
            if role in {"__system__", "admin"}:
                continue
            codes = by_role.setdefault(role, set())
            for code in _MOBILE_HOME_CODES:
                if code in codes:
                    continue
                db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=code))
                codes.add(code)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_HOME_MARKER,
            )
        )
    scrap_records_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_SCRAP_RECORDS_MARKER,
            ).limit(1)
        )
    )
    if not scrap_records_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        role_codes = set(by_role)
        role_codes.update(
            db.scalars(select(TenantRole.code).where(TenantRole.tenant_id == tenant_id)).all()
        )
        for role in role_codes:
            if role in {"__system__", "admin"}:
                continue
            codes = by_role.setdefault(role, set())
            if "mobile.scrap_records" in codes:
                continue
            db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code="mobile.scrap_records"))
            codes.add("mobile.scrap_records")
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_SCRAP_RECORDS_MARKER,
            )
        )

    # 合作商品牌、外加工厂从共用权限拆出。只补一次，之后允许单独取消。
    partner_category_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _PARTNER_CATEGORY_MARKER,
            ).limit(1)
        )
    )
    if not partner_category_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            for src, dest in _PARTNER_CATEGORY_COPIES.items():
                if src in codes and dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_PARTNER_CATEGORY_MARKER,
            )
        )

    # 色卡批量购买从菜单可见拆出。只补一次，之后允许单独取消。
    catalog_buy_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _CATALOG_BUY_MARKER,
            ).limit(1)
        )
    )
    if not catalog_buy_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "menu.supplier_products" in codes and "btn.supplier_products.batch_buy" not in codes:
                db.add(
                    RolePermission(
                        tenant_id=tenant_id,
                        role=role,
                        perm_code="btn.supplier_products.batch_buy",
                    )
                )
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_CATALOG_BUY_MARKER,
            )
        )

    # 订单管理的确认、合单、取消从「新建」拆出。只补一次，之后允许单独取消。
    sales_order_action_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _SALES_ORDER_ACTION_MARKER,
            ).limit(1)
        )
    )
    if not sales_order_action_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "btn.sales_orders.write" not in codes:
                continue
            for dest in _SALES_ORDER_ACTION_CODES:
                if dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_SALES_ORDER_ACTION_MARKER,
            )
        )

    # 成品仓的出货、次品从独立出货菜单拆出。只补一次，之后允许单独取消。
    fg_button_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _FG_BUTTON_MARKER,
            ).limit(1)
        )
    )
    if not fg_button_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "menu.fg_stocks" not in codes and "menu.shipments" not in codes:
                continue
            if "menu.fg_stocks" not in codes:
                db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code="menu.fg_stocks"))
                codes.add("menu.fg_stocks")
            for dest in _FG_BUTTON_CODES:
                if dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_FG_BUTTON_MARKER,
            )
        )

    # 已出货的打印、导出原先跟菜单走；填写运单、退回工厂原先跟已取消的开单权限走。只补一次。
    fg_shipped_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _FG_SHIPPED_ACTION_MARKER,
            ).limit(1)
        )
    )
    if not fg_shipped_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "menu.fg_stocks" in codes or "menu.shipments" in codes:
                for dest in _FG_SHIPPED_VIEW_CODES:
                    if dest not in codes:
                        db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                        codes.add(dest)
            if "btn.shipments.write" in codes:
                for dest in _FG_SHIPPED_WRITE_CODES:
                    if dest not in codes:
                        db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                        codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_FG_SHIPPED_ACTION_MARKER,
            )
        )

    # 报废记录的确认、编辑、删除、打印原先跟菜单走。只补一次，之后允许单独取消。
    defect_button_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _DEFECT_BUTTON_MARKER,
            ).limit(1)
        )
    )
    if not defect_button_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "menu.defects" not in codes:
                continue
            for dest in _DEFECT_BUTTON_CODES:
                if dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_DEFECT_BUTTON_MARKER,
            )
        )

    # 复版记录从产品开发拆出。只补一次，之后允许单独取消。
    sample_remake_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _SAMPLE_REMAKE_MARKER,
            ).limit(1)
        )
    )
    if not sample_remake_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            for src, dest in _SAMPLE_REMAKE_COPIES.items():
                if src in codes and dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_SAMPLE_REMAKE_MARKER,
            )
        )

    # 产品开发从「新增/编辑/删除」拆成基础数据、工艺路线和报价。只补一次。
    own_product_section_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _OWN_PRODUCT_SECTION_MARKER,
            ).limit(1)
        )
    )
    if not own_product_section_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "btn.own_products.write" in codes:
                for dest in _OWN_PRODUCT_PC_SECTIONS:
                    if dest not in codes:
                        db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                        codes.add(dest)
            if "mobile.own_products.write" in codes:
                for dest in _OWN_PRODUCT_MOBILE_SECTIONS:
                    if dest not in codes:
                        db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                        codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_OWN_PRODUCT_SECTION_MARKER,
            )
        )

    # 删除、导出、复制、修改记录从查看/编辑里拆出。只补一次，之后允许单独取消。
    own_product_action_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _OWN_PRODUCT_ACTION_MARKER,
            ).limit(1)
        )
    )
    if not own_product_action_seeded:
        by_role = _role_permission_codes(db, tenant_id)

        def _grant(role: str, codes: set[str], dest: str) -> None:
            if dest in codes:
                return
            db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
            codes.add(dest)

        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "btn.own_products.basic_edit" in codes or "btn.own_products.write" in codes:
                _grant(role, codes, "btn.own_products.delete")
            if "btn.own_products.basic_create" in codes or "btn.own_products.write" in codes:
                _grant(role, codes, "btn.own_products.copy")
            if "menu.own_products" in codes or "btn.own_products.write" in codes:
                _grant(role, codes, "btn.own_products.export")
                _grant(role, codes, "btn.own_products.history")
            if "mobile.own_products.basic_edit" in codes or "mobile.own_products.write" in codes:
                _grant(role, codes, "mobile.own_products.delete")
            if "mobile.own_products.basic_create" in codes or "mobile.own_products.write" in codes:
                _grant(role, codes, "mobile.own_products.copy")
            if "mobile.own_products" in codes or "mobile.own_products.write" in codes:
                _grant(role, codes, "mobile.own_products.export")
                _grant(role, codes, "mobile.own_products.history")
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_OWN_PRODUCT_ACTION_MARKER,
            )
        )

    # 模具从物料仓权限拆出。只补一次，之后允许单独取消。
    tooling_permission_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _TOOLING_PERMISSION_MARKER,
            ).limit(1)
        )
    )
    if not tooling_permission_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            for src, dest in _TOOLING_PERMISSION_COPIES.items():
                if src in codes and dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_TOOLING_PERMISSION_MARKER,
            )
        )

    # PC 裁断用料从生产进度拆出。原先挂 menu.orders，只补一次，之后允许单独取消。
    pc_cut_usage_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _PC_CUT_USAGE_MARKER,
            ).limit(1)
        )
    )
    if not pc_cut_usage_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if (
                "menu.orders" in codes or "menu.sales_orders" in codes
            ) and "menu.cut_material_usage" not in codes:
                db.add(
                    RolePermission(
                        tenant_id=tenant_id,
                        role=role,
                        perm_code="menu.cut_material_usage",
                    )
                )
                codes.add("menu.cut_material_usage")
            if (
                "mobile.cut_material_usage.write" in codes or role in _PC_CUT_USAGE_APPLY_ROLES
            ) and "btn.cut_material_usage.apply" not in codes:
                db.add(
                    RolePermission(
                        tenant_id=tenant_id,
                        role=role,
                        perm_code="btn.cut_material_usage.apply",
                    )
                )
                codes.add("btn.cut_material_usage.apply")
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_PC_CUT_USAGE_MARKER,
            )
        )

    # 工序&人员从基础数据拆出。有基础数据或员工与部门的角色补一次，之后可单独取消。
    process_staff_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _PROCESS_STAFF_MARKER,
            ).limit(1)
        )
    )
    if not process_staff_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "menu.process_staff" in codes:
                continue
            if "menu.masters" in codes or "menu.workers" in codes:
                db.add(
                    RolePermission(
                        tenant_id=tenant_id,
                        role=role,
                        perm_code="menu.process_staff",
                    )
                )
                codes.add("menu.process_staff")
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_PROCESS_STAFF_MARKER,
            )
        )

    # 订单利润从成本分析里拆出。已有成本分析的角色，以及财务，补一次。
    order_profit_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _ORDER_PROFIT_MARKER,
            ).limit(1)
        )
    )
    if not order_profit_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "menu.profit" not in codes and role != "finance":
                continue
            if "menu.order_profit" not in codes:
                db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code="menu.order_profit"))
                codes.add("menu.order_profit")
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_ORDER_PROFIT_MARKER,
            )
        )

    # 售后按钮从菜单里拆出。已能打开售后的角色补一次，之后允许单独取消。
    after_sales_action_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _AFTER_SALES_ACTION_MARKER,
            ).limit(1)
        )
    )
    if not after_sales_action_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "menu.after_sales" not in codes:
                continue
            for dest in _AFTER_SALES_ACTIONS:
                if dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_AFTER_SALES_ACTION_MARKER,
            )
        )

    # 手机合作商从「新增/编辑」拆成客户、供应商、外加工厂、品牌。只补一次。
    mobile_partner_action_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_PARTNER_ACTION_MARKER,
            ).limit(1)
        )
    )
    if not mobile_partner_action_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "mobile.partners.write" not in codes:
                continue
            for dest in _MOBILE_PARTNER_ACTIONS:
                if dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_PARTNER_ACTION_MARKER,
            )
        )

    # 手机物料采购从「下单反馈/损耗/到货」拆成三项。只补一次，之后允许单独取消。
    mobile_po_action_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _MOBILE_PO_ACTION_MARKER,
            ).limit(1)
        )
    )
    if not mobile_po_action_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "mobile.purchase_orders.write" not in codes:
                continue
            for dest in _MOBILE_PO_ACTIONS:
                if dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_MOBILE_PO_ACTION_MARKER,
            )
        )

    # 在途按钮从「下单/到货/退订」拆开，并补上原先没有的导出、打印。只补一次。
    po_action_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _PO_ACTION_MARKER,
            ).limit(1)
        )
    )
    if not po_action_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "btn.purchase_orders.write" in codes:
                grant = _PO_WRITE_CODES
            elif "menu.purchase_orders" in codes:
                grant = _PO_VIEW_CODES
            else:
                continue
            for dest in grant:
                if dest not in codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=dest))
                    codes.add(dest)
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_PO_ACTION_MARKER,
            )
        )

    # 外加工厂对账从供应商付款里拆出。已有供应商对账或付款的角色补一次。
    subcontract_settlement_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _SUBCONTRACT_SETTLEMENT_MARKER,
            ).limit(1)
        )
    )
    if not subcontract_settlement_seeded:
        by_role = _role_permission_codes(db, tenant_id)
        for role, codes in by_role.items():
            if role == "__system__":
                continue
            if "menu.subcontract_settlements" in codes:
                continue
            if "menu.payables" in codes or "menu.supplier_payments" in codes:
                db.add(
                    RolePermission(
                        tenant_id=tenant_id,
                        role=role,
                        perm_code="menu.subcontract_settlements",
                    )
                )
                codes.add("menu.subcontract_settlements")
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_SUBCONTRACT_SETTLEMENT_MARKER,
            )
        )

    # 采购仓管拆成采购、仓管。原来挂着采购仓管的人两边都保留。
    purchasing_split = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _SPLIT_PURCHASING_MARKER,
            ).limit(1)
        )
    )
    if not purchasing_split:
        purchasing_only = set(default_permissions_for_role("purchasing")) - set(
            default_permissions_for_role("warehouse")
        )
        if purchasing_only:
            db.execute(
                delete(RolePermission).where(
                    RolePermission.tenant_id == tenant_id,
                    RolePermission.role == "warehouse",
                    RolePermission.perm_code.in_(purchasing_only),
                )
            )
        warehouse_people = db.scalars(
            select(EmployeeRoleAssignment).where(
                EmployeeRoleAssignment.tenant_id == tenant_id,
                EmployeeRoleAssignment.role_code == "warehouse",
            )
        ).all()
        for item in warehouse_people:
            has_purchasing = db.scalar(
                select(EmployeeRoleAssignment.id).where(
                    EmployeeRoleAssignment.employee_id == item.employee_id,
                    EmployeeRoleAssignment.role_code == "purchasing",
                ).limit(1)
            )
            if not has_purchasing:
                db.add(
                    EmployeeRoleAssignment(
                        tenant_id=tenant_id,
                        employee_id=item.employee_id,
                        role_code="purchasing",
                    )
                )
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_SPLIT_PURCHASING_MARKER,
            )
        )

    # 废弃用户角色「组长」→ 车间主管
    leader_row = db.scalar(
        select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.code == _LEGACY_LEADER)
    )
    if leader_row and leader_row.is_active:
        leader_row.is_active = False
        leader_row.is_system = False
        leader_row.description = (leader_row.description or "") + "（已废弃，请用员工组长）"
        leader_row.base_role = "manager"

    # 废弃内置角色「跟单」→ 开发部文员
    merchandiser_row = db.scalar(
        select(TenantRole).where(
            TenantRole.tenant_id == tenant_id,
            TenantRole.code == _LEGACY_MERCHANDISER,
        )
    )
    if merchandiser_row and (merchandiser_row.is_active or merchandiser_row.is_system):
        merchandiser_row.is_active = False
        merchandiser_row.is_system = False
        merchandiser_row.description = "已废弃，请改用开发部文员或生管"
        merchandiser_row.base_role = "manager"
    merchandiser_assignments = db.scalars(
        select(EmployeeRoleAssignment).where(
            EmployeeRoleAssignment.tenant_id == tenant_id,
            EmployeeRoleAssignment.role_code == _LEGACY_MERCHANDISER,
        )
    ).all()
    for item in merchandiser_assignments:
        has_clerk = db.scalar(
            select(EmployeeRoleAssignment.id).where(
                EmployeeRoleAssignment.employee_id == item.employee_id,
                EmployeeRoleAssignment.role_code == "clerk",
            ).limit(1)
        )
        if has_clerk:
            db.delete(item)
        else:
            item.role_code = "clerk"

    db.execute(delete(RolePermission).where(RolePermission.perm_code == "btn.orders.halt"))

    new_system_roles_seeded = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _SEED_NEW_SYSTEM_ROLES_MARKER,
            ).limit(1)
        )
    )
    if not new_system_roles_seeded:
        for role_code in _SEED_NEW_SYSTEM_ROLE_CODES:
            existing = set(
                db.scalars(
                    select(RolePermission.perm_code).where(
                        RolePermission.tenant_id == tenant_id,
                        RolePermission.role == role_code,
                    )
                ).all()
            )
            if existing:
                continue
            for code in default_permissions_for_role(role_code):
                db.add(RolePermission(tenant_id=tenant_id, role=role_code, perm_code=code))
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_SEED_NEW_SYSTEM_ROLES_MARKER,
            )
        )

    roles_promoted = bool(
        db.scalar(
            select(RolePermission.id).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.perm_code == _PROMOTE_EXISTING_ROLES_MARKER,
            ).limit(1)
        )
    )
    if not roles_promoted:
        custom_rows = db.scalars(
            select(TenantRole).where(
                TenantRole.tenant_id == tenant_id,
                TenantRole.is_system.is_(False),
                TenantRole.code.notin_([_LEGACY_LEADER, _LEGACY_MERCHANDISER]),
            )
        ).all()
        for row in custom_rows:
            row.is_system = True
        db.add(
            RolePermission(
                tenant_id=tenant_id,
                role="__system__",
                perm_code=_PROMOTE_EXISTING_ROLES_MARKER,
            )
        )

    db.commit()


def get_tenant_role(db: Session, tenant_id: int, code: str) -> TenantRole | None:
    return db.scalar(
        select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.code == code)
    )


def admin_employee_ids_select(tenant_id: int):
    """本租户绑了管理员角色的员工 id 子查询（员工管理列表/部门人数默认排除）。"""
    return select(EmployeeRoleAssignment.employee_id).where(
        EmployeeRoleAssignment.tenant_id == tenant_id,
        EmployeeRoleAssignment.role_code == "admin",
    )


def list_employee_role_codes(db: Session, employee: Employee) -> list[str]:
    ensure_system_roles(db, employee.tenant_id)
    codes = list(
        db.scalars(
            select(EmployeeRoleAssignment.role_code).where(
                EmployeeRoleAssignment.employee_id == employee.id
            )
        ).all()
    )
    mapped: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code == _LEGACY_LEADER:
            code = "workshop"
        elif code == _LEGACY_MERCHANDISER:
            code = "clerk"
        if code in seen:
            continue
        seen.add(code)
        mapped.append(code)
    return mapped


def list_user_role_codes(db: Session, employee: Employee) -> list[str]:
    """兼容别名。"""
    return list_employee_role_codes(db, employee)


def set_employee_roles(db: Session, employee: Employee, role_codes: list[str]) -> list[str]:
    """设置员工后台角色列表（可为空=纯生产员工）。"""
    ensure_system_roles(db, employee.tenant_id)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in role_codes or []:
        code = str(raw or "").strip()
        if not code or code in seen:
            continue
        if code == _LEGACY_LEADER:
            code = "workshop"
        elif code == _LEGACY_MERCHANDISER:
            code = "clerk"
        assert_assignable_role(db, employee.tenant_id, code)
        seen.add(code)
        cleaned.append(code)

    db.execute(
        delete(EmployeeRoleAssignment).where(
            EmployeeRoleAssignment.employee_id == employee.id
        )
    )
    for code in cleaned:
        db.add(
            EmployeeRoleAssignment(
                tenant_id=employee.tenant_id,
                employee_id=employee.id,
                role_code=code,
            )
        )
    db.flush()
    return cleaned


def set_user_roles(db: Session, employee: Employee, role_codes: list[str]) -> list[str]:
    """兼容别名。"""
    return set_employee_roles(db, employee, role_codes)


def effective_base_role(db: Session, tenant_id: int, role_code: str) -> str:
    """单个角色的 API 天花板。"""
    if role_code == "admin":
        return "admin"
    if role_code == _LEGACY_LEADER or role_code == _LEGACY_MERCHANDISER:
        return "manager"
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, role_code)
    if not row or not row.is_active:
        if role_code in _BASE_ROLES:
            return role_code
        if role_code in _SYSTEM_ROLE_CODES:
            return "manager"
        return "manager"
    base = row.base_role or "manager"
    if base == _LEGACY_LEADER:
        return "manager"
    return base if base in _BASE_ROLES else "manager"


def employee_effective_base_role(db: Session, employee: Employee) -> str:
    """多角色取最高天花板（有 admin 则为 admin，否则 manager）。

    无任何后台角色（纯生产员工）返回空串，不能通过 require_roles 校验。
    """
    codes = list_employee_role_codes(db, employee)
    if not codes:
        return ""
    bases = {effective_base_role(db, employee.tenant_id, c) for c in codes}
    if "admin" in bases or "admin" in codes:
        return "admin"
    return "manager"


def user_effective_base_role(db: Session, employee: Employee) -> str:
    """兼容别名。"""
    return employee_effective_base_role(db, employee)


def get_role_permissions(db: Session, tenant_id: int, role: str) -> list[str]:
    ensure_system_roles(db, tenant_id)
    if role == _LEGACY_LEADER:
        role = "workshop"
    if role == _LEGACY_MERCHANDISER:
        role = "clerk"
    row = get_tenant_role(db, tenant_id, role)
    if not row:
        if role == "admin":
            return all_permission_codes()
        raise RbacError("invalid_role", f"无效角色：{role}")
    if not row.is_active:
        raise RbacError("role_inactive", f"角色已停用：{role}")
    if row.base_role == "admin" or row.code == "admin":
        return all_permission_codes()
    rows = db.scalars(
        select(RolePermission.perm_code).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role == role,
        )
    ).all()
    valid = _valid_codes()
    return sorted(c for c in rows if c in valid)


def get_employee_permissions(db: Session, employee: Employee) -> list[str]:
    """多角色权限并集。"""
    codes = list_employee_role_codes(db, employee)
    if not codes:
        # 无后台角色的生产员工，统一读取可配置的「生产员工」角色权限。
        return get_role_permissions(db, employee.tenant_id, "worker")
    if "admin" in codes:
        return all_permission_codes()
    merged: set[str] = set()
    for code in codes:
        try:
            merged.update(get_role_permissions(db, employee.tenant_id, code))
        except RbacError:
            continue
    return sorted(merged)


def get_user_permissions(db: Session, employee: Employee) -> list[str]:
    """兼容别名。"""
    return get_employee_permissions(db, employee)


def set_role_permissions(db: Session, tenant_id: int, role: str, codes: list[str]) -> list[str]:
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, role)
    if not row:
        raise RbacError("invalid_role", f"无效角色：{role}")
    if row.code == "admin" or row.base_role == "admin":
        raise RbacError("role_locked", "管理员权限固定为全部，不可编辑")
    if not row.is_active:
        raise RbacError("role_inactive", "已停用角色不可编辑权限")
    valid = _valid_codes()
    cleaned = sorted({c for c in codes if c in valid})
    db.execute(
        delete(RolePermission).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role == role,
        )
    )
    for code in cleaned:
        db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=code))
    db.commit()
    return cleaned


def _serialize_role(db: Session, tenant_id: int, row: TenantRole) -> dict:
    try:
        perms = get_role_permissions(db, tenant_id, row.code)
    except RbacError:
        perms = []
    editable = row.code != "admin" and row.base_role != "admin"
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "base_role": row.base_role,
        "is_system": bool(row.is_system),
        "is_active": bool(row.is_active),
        "editable": editable,
        "permission_count": len(perms),
        "permissions": perms,
    }


def list_role_members(db: Session, tenant_id: int, *, include_inactive: bool = False) -> list[dict]:
    """每个角色及其已绑定员工，供角色管理页查看角色-用户。"""
    ensure_system_roles(db, tenant_id)
    q = select(TenantRole).where(TenantRole.tenant_id == tenant_id)
    if not include_inactive:
        q = q.where(TenantRole.is_active.is_(True))
    roles = list(db.scalars(q.order_by(TenantRole.is_system.desc(), TenantRole.id)).all())
    if not include_inactive:
        roles = [r for r in roles if r.code not in {_LEGACY_LEADER, _LEGACY_MERCHANDISER}]

    assignments = db.execute(
        select(EmployeeRoleAssignment, Employee)
        .join(Employee, Employee.id == EmployeeRoleAssignment.employee_id)
        .where(
            EmployeeRoleAssignment.tenant_id == tenant_id,
            Employee.tenant_id == tenant_id,
        )
        .order_by(Employee.name, Employee.id)
    ).all()
    dept_ids = {emp.department_id for _, emp in assignments if emp.department_id}
    dept_names: dict[int, str] = {}
    if dept_ids:
        deps = db.scalars(select(Department).where(Department.id.in_(dept_ids))).all()
        dept_names = {dep.id: dep.name for dep in deps}

    users_by_role: dict[str, list[dict]] = {role.code: [] for role in roles}
    seen: set[tuple[int, str]] = set()
    for assign, emp in assignments:
        code = assign.role_code
        if code == _LEGACY_LEADER:
            code = "workshop"
        elif code == _LEGACY_MERCHANDISER:
            code = "clerk"
        if code not in users_by_role:
            continue
        key = (emp.id, code)
        if key in seen:
            continue
        seen.add(key)
        users_by_role[code].append(
            {
                "id": emp.id,
                "name": emp.name,
                "username": emp.username,
                "department_name": dept_names.get(emp.department_id) if emp.department_id else None,
                "is_active": bool(emp.is_active),
            }
        )
    return [
        {
            "code": role.code,
            "name": role.name,
            "is_system": bool(role.is_system),
            "is_active": bool(role.is_active),
            "user_count": len(users_by_role[role.code]),
            "users": users_by_role[role.code],
        }
        for role in roles
    ]


def list_roles(db: Session, tenant_id: int, *, include_inactive: bool = False) -> list[dict]:
    ensure_system_roles(db, tenant_id)
    q = select(TenantRole).where(TenantRole.tenant_id == tenant_id)
    if not include_inactive:
        q = q.where(TenantRole.is_active.is_(True))
    rows = db.scalars(q.order_by(TenantRole.is_system.desc(), TenantRole.id)).all()
    # 隐藏已废弃的 leader（即使 include_inactive，默认列表也不突出；include 时仍可见）
    if not include_inactive:
        rows = [r for r in rows if r.code not in {_LEGACY_LEADER, _LEGACY_MERCHANDISER}]
    return [_serialize_role(db, tenant_id, r) for r in rows]


def create_role(
    db: Session,
    tenant_id: int,
    *,
    name: str,
    code: str | None = None,
    description: str | None = None,
    base_role: str = "manager",
    permissions: list[str] | None = None,
) -> dict:
    ensure_system_roles(db, tenant_id)
    name = (name or "").strip()
    if not name:
        raise RbacError("name_required", "请填写角色名称")
    if base_role == _LEGACY_LEADER:
        base_role = "manager"
    if base_role not in ("manager",):
        raise RbacError("invalid_base", "自定义角色接口级别仅支持「业务级」")

    raw = (code or "").strip().lower()
    auto = not raw
    if auto:
        raw = "role_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        raw = raw[:28].strip("_") or "role_custom"
        if not _CODE_RE.match(raw):
            n = db.scalar(
                select(func.count()).select_from(TenantRole).where(TenantRole.tenant_id == tenant_id)
            ) or 0
            raw = f"role_{n}"
    if not _CODE_RE.match(raw):
        raise RbacError("invalid_code", "角色编码须为小写字母开头，仅含字母数字下划线，2–31 位")
    if raw in _SYSTEM_ROLE_CODES or raw == "admin" or raw in {_LEGACY_LEADER, _LEGACY_MERCHANDISER}:
        raise RbacError("code_reserved", "该编码为系统保留，请换一个")

    if get_tenant_role(db, tenant_id, raw):
        if not auto:
            raise RbacError("duplicate_code", f"角色编码已存在：{raw}")
        base = raw[:24].rstrip("_")
        i = 2
        while get_tenant_role(db, tenant_id, f"{base}_{i}") or f"{base}_{i}" in _SYSTEM_ROLE_CODES:
            i += 1
            if i > 9999:
                raise RbacError("duplicate_code", "无法生成唯一角色编码")
        raw = f"{base}_{i}"

    row = TenantRole(
        tenant_id=tenant_id,
        code=raw,
        name=name,
        description=(description or "").strip() or None,
        base_role=base_role,
        is_system=False,
        is_active=True,
    )
    db.add(row)
    db.flush()

    seed = permissions if permissions is not None else []
    valid = _valid_codes()
    for p in sorted({c for c in seed if c in valid}):
        db.add(RolePermission(tenant_id=tenant_id, role=raw, perm_code=p))
    db.commit()
    db.refresh(row)
    return _serialize_role(db, tenant_id, row)


def _count_users_with_role(db: Session, tenant_id: int, code: str, *, active_only: bool = False) -> int:
    q = (
        select(func.count())
        .select_from(EmployeeRoleAssignment)
        .where(
            EmployeeRoleAssignment.tenant_id == tenant_id,
            EmployeeRoleAssignment.role_code == code,
        )
    )
    if active_only:
        q = q.join(
            Employee, Employee.id == EmployeeRoleAssignment.employee_id
        ).where(Employee.is_active.is_(True))
    return int(db.scalar(q) or 0)


def update_role(
    db: Session,
    tenant_id: int,
    code: str,
    *,
    name: str | None = None,
    description: str | None = None,
    base_role: str | None = None,
    is_active: bool | None = None,
) -> dict:
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, code)
    if not row:
        raise RbacError("invalid_role", f"无效角色：{code}")
    if row.is_system and is_active is False:
        raise RbacError("system_role", "系统内置角色不可停用")
    if name is not None:
        name = name.strip()
        if not name:
            raise RbacError("name_required", "请填写角色名称")
        row.name = name
    if description is not None:
        row.description = description.strip() or None
    if base_role is not None:
        if row.is_system:
            raise RbacError("system_role", "系统内置角色不可改基础角色")
        if base_role == _LEGACY_LEADER:
            base_role = "manager"
        if base_role not in ("manager",):
            raise RbacError("invalid_base", "自定义角色接口级别仅支持「业务级」")
        row.base_role = base_role
    if is_active is not None:
        if row.is_system:
            raise RbacError("system_role", "系统内置角色不可停用")
        if is_active is False:
            used = _count_users_with_role(db, tenant_id, code, active_only=True)
            if used:
                raise RbacError("role_in_use", f"仍有 {used} 个启用用户使用该角色，无法停用")
        row.is_active = is_active
    db.commit()
    db.refresh(row)
    return _serialize_role(db, tenant_id, row)


def delete_role(db: Session, tenant_id: int, code: str) -> None:
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, code)
    if not row:
        raise RbacError("invalid_role", f"无效角色：{code}")
    if row.is_system:
        raise RbacError("system_role", "系统内置角色不可删除")
    used = _count_users_with_role(db, tenant_id, code)
    if used:
        raise RbacError("role_in_use", f"仍有 {used} 个用户使用该角色，无法删除")
    db.execute(
        delete(RolePermission).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role == code,
        )
    )
    db.execute(
        delete(EmployeeRoleAssignment).where(
            EmployeeRoleAssignment.tenant_id == tenant_id,
            EmployeeRoleAssignment.role_code == code,
        )
    )
    db.delete(row)
    db.commit()


def assert_assignable_role(db: Session, tenant_id: int, role: str) -> None:
    ensure_system_roles(db, tenant_id)
    if role == _LEGACY_LEADER:
        raise RbacError("invalid_role", "「组长」用户角色已废弃，请改用员工组长")
    if role == _LEGACY_MERCHANDISER:
        raise RbacError("invalid_role", "「跟单」已废弃，请改用开发部文员或生管")
    row = get_tenant_role(db, tenant_id, role)
    if not row or not row.is_active:
        raise RbacError("invalid_role", f"无效或已停用角色：{role}")


def permissions_matrix(db: Session, tenant_id: int) -> dict:
    roles = list_roles(db, tenant_id)
    role_list = [{"code": r["code"], "name": r["name"]} for r in roles]
    granted_map = {r["code"]: set(r["permissions"]) for r in roles}
    items = []
    for p in permission_catalog():
        items.append(
            {
                "code": p["code"],
                "name": p["name"],
                "module": p["module"],
                "kind": p["kind"],
                "roles": {rc: (p["code"] in granted_map.get(rc, set())) for rc in granted_map},
            }
        )
    return {"roles": role_list, "items": items, "tree": permission_tree_for_ui()}


def user_has_permission(db: Session, tenant_id: int, role: str, perm_code: str) -> bool:
    try:
        perms = get_role_permissions(db, tenant_id, role)
    except RbacError:
        return False
    return perm_code in perms


def user_has_any_permission(db: Session, employee: Employee, perm_code: str) -> bool:
    return perm_code in get_employee_permissions(db, employee)
