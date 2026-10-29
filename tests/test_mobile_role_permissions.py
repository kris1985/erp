from fastapi import HTTPException
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.partners import _ensure_partner_write
from app.db import Base
from app.models import Employee, RolePermission, Tenant, TenantRole
from app.services import employee_feature_service, rbac_service
from app.services.rbac_service import (
    _MOBILE_PARTNER_ACTION_MARKER,
    _MOBILE_PO_ACTION_MARKER,
    _ORDER_PROFIT_MARKER,
)


def test_production_employee_mobile_features_follow_worker_role():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机角色权限测试厂")
    db.add(tenant)
    db.flush()
    employee = Employee(tenant_id=tenant.id, name="生产员工", is_active=True)
    db.add(employee)
    db.commit()

    assert employee_feature_service.list_codes(db, employee) == [
        "expense",
        "piecework",
        "product_scrap",
        "production_progress",
        "salary",
        "scrap",
        "scrap_records",
        "work_report",
    ]
    assert rbac_service.employee_effective_base_role(db, employee) == ""

    rbac_service.set_role_permissions(
        db,
        tenant.id,
        "worker",
        ["mobile.scrap"],
    )

    assert employee_feature_service.list_codes(db, employee) == ["scrap"]
    assert employee_feature_service.has_feature(db, employee, "scrap") is True
    assert employee_feature_service.has_feature(db, employee, "product_scrap") is False
    assert employee_feature_service.has_feature(db, employee, "work_report") is False
    db.close()


def test_mobile_catalog_permission_is_not_the_pc_menu():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机色卡权限厂")
    db.add(tenant)
    db.flush()
    employee = Employee(tenant_id=tenant.id, name="仓管", is_active=True)
    db.add(employee)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    manager = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    assert "mobile.supplier_products" in manager
    assert "mobile.supplier_products.write" in manager
    assert "mobile.supplier_products.approve" in manager
    assert "mobile.supplier_products.batch_buy" in manager
    assert "menu.supplier_products" in manager

    rbac_service.set_employee_roles(db, employee, ["purchasing"])
    codes = set(employee_feature_service.list_codes(db, employee))
    assert "supplier_products" in codes
    assert "supplier_products_write" in codes
    assert "supplier_products_approve" not in codes
    assert "supplier_products_batch_buy" in codes

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "purchasing")
        if not code.startswith("mobile.supplier_products")
    ]
    kept.append("menu.supplier_products")
    rbac_service.set_role_permissions(db, tenant.id, "purchasing", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "purchasing"))
    assert "menu.supplier_products" in after
    assert "mobile.supplier_products" not in after
    assert employee_feature_service.has_feature(db, employee, "supplier_products") is False
    db.close()


def test_mobile_partners_permission_is_not_the_pc_menu():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机合作商权限厂")
    db.add(tenant)
    db.flush()
    employee = Employee(tenant_id=tenant.id, name="跟单", is_active=True)
    db.add(employee)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    manager = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    assert "mobile.partners" in manager
    assert "mobile.partners.customer" in manager
    assert "mobile.partners.supplier" in manager
    assert "mobile.partners.subcontractor" in manager
    assert "mobile.partners.brand" in manager
    assert "menu.customers" in manager
    finance = set(rbac_service.get_role_permissions(db, tenant.id, "finance"))
    assert "mobile.partners" in finance
    assert "mobile.partners.customer" not in finance
    assert "mobile.partners.supplier" not in finance

    rbac_service.set_employee_roles(db, employee, ["clerk"])
    codes = set(employee_feature_service.list_codes(db, employee))
    assert "partners" in codes
    assert "partners_customer" in codes
    assert "partners_supplier" in codes
    assert "partners_subcontractor" in codes
    assert "partners_brand" in codes

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "clerk")
        if not code.startswith("mobile.partners")
    ]
    kept.append("menu.customers")
    rbac_service.set_role_permissions(db, tenant.id, "clerk", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "clerk"))
    assert "menu.customers" in after
    assert "mobile.partners" not in after
    assert "mobile.partners.customer" not in after
    assert "mobile.partners.brand" not in after
    assert employee_feature_service.has_feature(db, employee, "partners") is False
    assert employee_feature_service.has_feature(db, employee, "partners_customer") is False
    db.close()


def test_mobile_attendance_rules_permission_is_not_the_pc_menu():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机考勤规则权限厂")
    db.add(tenant)
    db.flush()
    employee = Employee(tenant_id=tenant.id, name="财务", is_active=True)
    db.add(employee)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    manager = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    assert "mobile.attendance_rules" in manager
    assert "mobile.attendance_rules.write" in manager
    assert "menu.attendance_rules" in manager

    rbac_service.set_employee_roles(db, employee, ["finance"])
    codes = set(employee_feature_service.list_codes(db, employee))
    assert "attendance_rules" in codes
    assert "attendance_rules_write" not in codes

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "finance")
        if not code.startswith("mobile.attendance_rules")
    ]
    kept.append("menu.attendance_rules")
    rbac_service.set_role_permissions(db, tenant.id, "finance", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "finance"))
    assert "menu.attendance_rules" in after
    assert "mobile.attendance_rules" not in after
    assert employee_feature_service.has_feature(db, employee, "attendance_rules") is False
    db.close()


def test_mobile_shared_materials_permission_is_not_the_pc_menu():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机物料仓权限厂")
    db.add(tenant)
    db.flush()
    employee = Employee(tenant_id=tenant.id, name="仓管", is_active=True)
    db.add(employee)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    manager = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    warehouse = set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    assert "mobile.shared_materials" in manager
    assert "mobile.shared_materials.write" in manager
    assert "mobile.shared_materials" in warehouse
    assert "mobile.shared_materials.write" in warehouse
    assert "menu.shared_materials" in warehouse
    assert "mobile.shared_materials" not in set(rbac_service.get_role_permissions(db, tenant.id, "worker"))

    rbac_service.set_employee_roles(db, employee, ["warehouse"])
    codes = set(employee_feature_service.list_codes(db, employee))
    assert "shared_materials" in codes
    assert "shared_materials_write" in codes

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "warehouse")
        if not code.startswith("mobile.shared_materials")
    ]
    kept.append("menu.shared_materials")
    rbac_service.set_role_permissions(db, tenant.id, "warehouse", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    assert "menu.shared_materials" in after
    assert "mobile.shared_materials" not in after
    assert "mobile.shared_materials.write" not in after
    assert employee_feature_service.has_feature(db, employee, "shared_materials") is False
    db.close()


def test_mobile_purchase_orders_permission_is_not_the_pc_menu():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机物料采购权限厂")
    db.add(tenant)
    db.flush()
    employee = Employee(tenant_id=tenant.id, name="跟单", is_active=True)
    db.add(employee)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    manager = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    purchasing = set(rbac_service.get_role_permissions(db, tenant.id, "purchasing"))
    pmc = set(rbac_service.get_role_permissions(db, tenant.id, "pmc"))
    assert "mobile.purchase_orders" in manager
    assert "mobile.purchase_orders.submit" in manager
    assert "mobile.purchase_orders.loss" in manager
    assert "mobile.purchase_orders.receive" in manager
    assert "mobile.purchase_orders" in purchasing
    assert "mobile.purchase_orders.submit" in purchasing
    assert "mobile.purchase_orders.loss" in purchasing
    assert "mobile.purchase_orders.receive" in purchasing
    assert "mobile.purchase_orders" not in set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    assert "mobile.purchase_orders" in pmc
    assert "mobile.purchase_orders.submit" not in pmc
    assert "mobile.purchase_orders.loss" not in pmc
    assert "mobile.purchase_orders.receive" not in pmc
    assert "menu.purchase_orders" in pmc
    assert "mobile.purchase_orders" not in set(rbac_service.get_role_permissions(db, tenant.id, "worker"))

    rbac_service.set_employee_roles(db, employee, ["pmc"])
    assert employee_feature_service.has_feature(db, employee, "purchase_orders") is True
    assert employee_feature_service.has_feature(db, employee, "purchase_orders_submit") is False
    assert employee_feature_service.has_feature(db, employee, "purchase_orders_loss") is False
    assert employee_feature_service.has_feature(db, employee, "purchase_orders_receive") is False

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "purchasing")
        if not code.startswith("mobile.purchase_orders")
    ]
    kept.append("menu.purchase_orders")
    rbac_service.set_role_permissions(db, tenant.id, "purchasing", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "purchasing"))
    assert "menu.purchase_orders" in after
    assert "mobile.purchase_orders" not in after
    assert "mobile.purchase_orders.submit" not in after
    assert "mobile.purchase_orders.loss" not in after
    assert "mobile.purchase_orders.receive" not in after
    db.close()


def test_mobile_cut_material_usage_permission_is_not_the_pc_menu():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机裁断用料权限厂")
    db.add(tenant)
    db.flush()
    employee = Employee(tenant_id=tenant.id, name="车间", is_active=True)
    db.add(employee)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    manager = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    pmc = set(rbac_service.get_role_permissions(db, tenant.id, "pmc"))
    warehouse = set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    finance = set(rbac_service.get_role_permissions(db, tenant.id, "finance"))
    cutting = set(rbac_service.get_role_permissions(db, tenant.id, "cutting_supervisor"))
    assert "mobile.cut_material_usage" in manager
    assert "mobile.cut_material_usage.write" in manager
    assert "menu.cut_material_usage" in manager
    assert "btn.cut_material_usage.apply" in manager
    assert "mobile.cut_material_usage" in pmc
    assert "mobile.cut_material_usage.write" not in pmc
    assert "menu.cut_material_usage" in pmc
    assert "btn.cut_material_usage.apply" not in pmc
    assert "mobile.cut_material_usage" in warehouse
    assert "mobile.cut_material_usage.write" not in warehouse
    assert "menu.cut_material_usage" in warehouse
    assert "btn.cut_material_usage.apply" not in warehouse
    assert "mobile.cut_material_usage" in finance
    assert "mobile.cut_material_usage.write" not in finance
    assert "menu.cut_material_usage" in finance
    assert "btn.cut_material_usage.apply" not in finance
    assert "menu.cut_material_usage" in cutting
    assert "btn.cut_material_usage.apply" not in cutting
    assert "mobile.cut_material_usage.write" not in cutting
    assert "menu.orders" in manager
    assert "mobile.cut_material_usage" not in set(rbac_service.get_role_permissions(db, tenant.id, "worker"))
    assert "menu.cut_material_usage" not in set(rbac_service.get_role_permissions(db, tenant.id, "worker"))

    rbac_service.set_employee_roles(db, employee, ["manager"])
    assert employee_feature_service.has_feature(db, employee, "cut_material_usage") is True
    assert employee_feature_service.has_feature(db, employee, "cut_material_usage_write") is True

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "manager")
        if not code.startswith("mobile.cut_material_usage")
    ]
    kept.append("menu.orders")
    rbac_service.set_role_permissions(db, tenant.id, "manager", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    assert "menu.orders" in after
    assert "mobile.cut_material_usage" not in after
    assert "mobile.cut_material_usage.write" not in after
    db.close()


def test_pc_cut_material_usage_permission_splits_from_orders_menu():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="PC裁断用料拆分厂")
    db.add(tenant)
    db.flush()
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    # 模拟旧租户：只有 menu.orders，没有 PC 裁断用料权限；清掉 marker 再补一次。
    db.execute(
        delete(RolePermission).where(
            RolePermission.tenant_id == tenant.id,
            RolePermission.perm_code.in_(
                [
                    "menu.cut_material_usage",
                    "btn.cut_material_usage.apply",
                    "__pc_cut_material_usage_permission_v1__",
                ]
            ),
        )
    )
    db.commit()
    rbac_service.ensure_system_roles(db, tenant.id)
    manager = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    pmc = set(rbac_service.get_role_permissions(db, tenant.id, "pmc"))
    assert "menu.cut_material_usage" in manager
    assert "btn.cut_material_usage.apply" in manager
    assert "menu.cut_material_usage" in pmc
    assert "btn.cut_material_usage.apply" not in pmc

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "pmc")
        if code not in {"menu.cut_material_usage", "btn.cut_material_usage.apply"}
    ]
    rbac_service.set_role_permissions(db, tenant.id, "pmc", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "pmc"))
    assert "menu.cut_material_usage" not in after
    assert "btn.cut_material_usage.apply" not in after
    db.close()


def test_mobile_own_products_permission_is_not_the_pc_menu():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机产品开发权限厂")
    db.add(tenant)
    db.flush()
    employee = Employee(tenant_id=tenant.id, name="跟单", is_active=True)
    db.add(employee)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    manager = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    clerk = set(rbac_service.get_role_permissions(db, tenant.id, "clerk"))
    warehouse = set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    finance = set(rbac_service.get_role_permissions(db, tenant.id, "finance"))
    assert "mobile.own_products" in manager
    assert "mobile.own_products.basic_create" in manager
    assert "mobile.own_products.basic_edit" in manager
    assert "mobile.own_products.route" in manager
    assert "mobile.own_products.quote" in manager
    assert "mobile.own_products.brand_quote" in manager
    assert "mobile.own_products.delete" in manager
    assert "mobile.own_products.export" in manager
    assert "mobile.own_products.copy" in manager
    assert "mobile.own_products.history" in manager
    assert "mobile.own_products.approve" in manager
    assert "btn.own_products.basic_create" in manager
    assert "btn.own_products.delete" in manager
    assert "btn.own_products.export" in manager
    assert "btn.own_products.copy" in manager
    assert "btn.own_products.history" in manager
    assert "btn.own_products.route" in manager
    assert "btn.own_products.quote" in manager
    assert "menu.own_products" in manager
    assert "mobile.own_products" in clerk
    assert "mobile.own_products.basic_create" not in clerk
    assert "mobile.own_products.delete" not in clerk
    assert "mobile.own_products.copy" not in clerk
    assert "mobile.own_products.export" in clerk
    assert "mobile.own_products.history" in clerk
    assert "btn.own_products.delete" not in clerk
    assert "btn.own_products.copy" not in clerk
    assert "btn.own_products.export" in clerk
    assert "btn.own_products.history" in clerk
    assert "mobile.own_products.approve" not in clerk
    assert "mobile.own_products" in warehouse
    assert "mobile.own_products.basic_edit" not in warehouse
    assert "mobile.own_products" not in finance
    assert "mobile.own_products" not in set(rbac_service.get_role_permissions(db, tenant.id, "worker"))

    rbac_service.set_employee_roles(db, employee, ["clerk"])
    assert employee_feature_service.has_feature(db, employee, "own_products") is True
    assert employee_feature_service.has_feature(db, employee, "own_products_basic_create") is False
    assert employee_feature_service.has_feature(db, employee, "own_products_basic_edit") is False
    assert employee_feature_service.has_feature(db, employee, "own_products_quote") is False
    assert employee_feature_service.has_feature(db, employee, "own_products_approve") is False

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "manager")
        if not code.startswith("mobile.own_products")
    ]
    kept.append("menu.own_products")
    rbac_service.set_role_permissions(db, tenant.id, "manager", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    assert "menu.own_products" in after
    assert "mobile.own_products" not in after
    assert "mobile.own_products.basic_create" not in after
    assert "mobile.own_products.quote" not in after
    assert "mobile.own_products.approve" not in after
    db.close()


def test_mobile_material_prep_permission_seeds_once():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机备料权限厂")
    db.add(tenant)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    assert "mobile.material_prep" in set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    assert "mobile.material_prep" not in set(rbac_service.get_role_permissions(db, tenant.id, "worker"))

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "warehouse")
        if code != "mobile.material_prep"
    ]
    rbac_service.set_role_permissions(db, tenant.id, "warehouse", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    assert "mobile.material_prep" not in set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    db.close()


def test_removed_menu_permission_is_not_restored():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="取消菜单权限厂")
    db.add(tenant)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    before = rbac_service.get_role_permissions(db, tenant.id, "manager")
    assert "menu.board" in before
    kept = [code for code in before if code != "menu.board"]
    rbac_service.set_role_permissions(db, tenant.id, "manager", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    assert "menu.board" not in after
    assert len(after) == len(kept)
    db.close()


def test_purchase_order_buttons_are_split_and_not_restored():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="在途按钮权限厂")
    db.add(tenant)
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    purchasing = set(rbac_service.get_role_permissions(db, tenant.id, "purchasing"))
    for code in (
        "btn.purchase_orders.export",
        "btn.purchase_orders.print",
        "btn.purchase_orders.loss",
        "btn.purchase_orders.submit",
        "btn.purchase_orders.receive",
        "btn.purchase_orders.unsubscribe",
        "btn.purchase_orders.cancel",
    ):
        assert code in purchasing
    assert "btn.purchase_orders.write" not in purchasing

    pmc = set(rbac_service.get_role_permissions(db, tenant.id, "pmc"))
    assert "btn.purchase_orders.export" in pmc
    assert "btn.purchase_orders.print" in pmc
    assert "btn.purchase_orders.submit" not in pmc
    assert "btn.purchase_orders.cancel" not in pmc

    kept = [code for code in purchasing if code != "btn.purchase_orders.cancel"]
    rbac_service.set_role_permissions(db, tenant.id, "purchasing", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "purchasing"))
    assert "btn.purchase_orders.cancel" not in after
    db.close()


def test_legacy_mobile_purchase_write_splits_once():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机采购拆分厂")
    db.add(tenant)
    db.flush()
    rbac_service.ensure_system_roles(db, tenant.id)
    db.add(TenantRole(
        tenant_id=tenant.id,
        code="buyer_legacy",
        name="旧采购",
        base_role="manager",
        is_active=True,
    ))
    db.add(TenantRole(
        tenant_id=tenant.id,
        code="buyer_view",
        name="只看采购",
        base_role="manager",
        is_active=True,
    ))
    db.flush()
    db.add(RolePermission(
        tenant_id=tenant.id,
        role="buyer_legacy",
        perm_code="mobile.purchase_orders.write",
    ))
    db.add(RolePermission(
        tenant_id=tenant.id,
        role="buyer_view",
        perm_code="mobile.purchase_orders",
    ))
    db.execute(
        delete(RolePermission).where(
            RolePermission.tenant_id == tenant.id,
            RolePermission.perm_code == _MOBILE_PO_ACTION_MARKER,
        )
    )
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    legacy = set(rbac_service.get_role_permissions(db, tenant.id, "buyer_legacy"))
    view = set(rbac_service.get_role_permissions(db, tenant.id, "buyer_view"))
    for code in (
        "mobile.purchase_orders.submit",
        "mobile.purchase_orders.loss",
        "mobile.purchase_orders.receive",
    ):
        assert code in legacy
        assert code not in view

    kept = [code for code in legacy if code != "mobile.purchase_orders.loss"]
    rbac_service.set_role_permissions(db, tenant.id, "buyer_legacy", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "buyer_legacy"))
    assert "mobile.purchase_orders.loss" not in after
    assert "mobile.purchase_orders.submit" in after
    assert "mobile.purchase_orders.receive" in after
    db.close()


def test_legacy_mobile_partner_write_splits_once():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="手机合作商拆分厂")
    db.add(tenant)
    db.flush()
    rbac_service.ensure_system_roles(db, tenant.id)
    db.add(TenantRole(
        tenant_id=tenant.id,
        code="partner_legacy",
        name="旧合作商",
        base_role="manager",
        is_active=True,
    ))
    db.add(TenantRole(
        tenant_id=tenant.id,
        code="partner_view",
        name="只看合作商",
        base_role="manager",
        is_active=True,
    ))
    db.flush()
    db.add(RolePermission(
        tenant_id=tenant.id,
        role="partner_legacy",
        perm_code="mobile.partners.write",
    ))
    db.add(RolePermission(
        tenant_id=tenant.id,
        role="partner_view",
        perm_code="mobile.partners",
    ))
    db.execute(
        delete(RolePermission).where(
            RolePermission.tenant_id == tenant.id,
            RolePermission.perm_code == _MOBILE_PARTNER_ACTION_MARKER,
        )
    )
    db.commit()

    rbac_service.ensure_system_roles(db, tenant.id)
    legacy = set(rbac_service.get_role_permissions(db, tenant.id, "partner_legacy"))
    view = set(rbac_service.get_role_permissions(db, tenant.id, "partner_view"))
    for code in (
        "mobile.partners.customer",
        "mobile.partners.supplier",
        "mobile.partners.subcontractor",
        "mobile.partners.brand",
    ):
        assert code in legacy
        assert code not in view

    kept = [code for code in legacy if code != "mobile.partners.supplier"]
    rbac_service.set_role_permissions(db, tenant.id, "partner_legacy", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "partner_legacy"))
    assert "mobile.partners.supplier" not in after
    assert "mobile.partners.customer" in after
    assert "mobile.partners.brand" in after
    db.close()


def test_partner_type_writes_do_not_cross():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="合作商分权厂")
    db.add(tenant)
    db.flush()
    employee = Employee(tenant_id=tenant.id, name="只改客户", is_active=True)
    db.add(employee)
    db.commit()
    rbac_service.ensure_system_roles(db, tenant.id)
    db.add(TenantRole(
        tenant_id=tenant.id,
        code="customer_only",
        name="只改客户",
        base_role="manager",
        is_active=True,
    ))
    db.flush()
    db.add(RolePermission(
        tenant_id=tenant.id,
        role="customer_only",
        perm_code="mobile.partners.customer",
    ))
    db.commit()
    rbac_service.set_employee_roles(db, employee, ["customer_only"])

    _ensure_partner_write(db, employee, {
        "is_customer": True,
        "is_supplier": False,
        "is_subcontractor": False,
        "is_brand": False,
    })
    try:
        _ensure_partner_write(db, employee, {
            "is_customer": False,
            "is_supplier": True,
            "is_subcontractor": False,
            "is_brand": False,
        })
        raise AssertionError("客户权限不应能改供应商")
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "供应商" in exc.detail
    try:
        _ensure_partner_write(db, employee, {
            "is_customer": True,
            "is_supplier": True,
            "is_subcontractor": False,
            "is_brand": False,
        })
        raise AssertionError("同时是客户和供应商时两项都要有")
    except HTTPException as exc:
        assert exc.status_code == 403
    db.close()


def test_finance_gets_order_profit_separately_from_cost_analysis():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="订单利润权限厂")
    db.add(tenant)
    db.commit()
    rbac_service.ensure_system_roles(db, tenant.id)
    finance = set(rbac_service.get_role_permissions(db, tenant.id, "finance"))
    manager = set(rbac_service.get_role_permissions(db, tenant.id, "manager"))
    assert "menu.order_profit" in finance
    assert "menu.profit" in finance
    assert "menu.order_profit" in manager
    assert "menu.order_profit" not in set(rbac_service.get_role_permissions(db, tenant.id, "clerk"))

    kept = [code for code in finance if code != "menu.order_profit"]
    rbac_service.set_role_permissions(db, tenant.id, "finance", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "finance"))
    assert "menu.order_profit" not in after
    assert "menu.profit" in after

    db.add(TenantRole(
        tenant_id=tenant.id,
        code="cost_only",
        name="只有成本分析",
        base_role="manager",
        is_active=True,
    ))
    db.flush()
    db.add(RolePermission(tenant_id=tenant.id, role="cost_only", perm_code="menu.profit"))
    db.execute(delete(RolePermission).where(
        RolePermission.tenant_id == tenant.id,
        RolePermission.perm_code == _ORDER_PROFIT_MARKER,
    ))
    db.commit()
    rbac_service.ensure_system_roles(db, tenant.id)
    assert "menu.order_profit" in set(rbac_service.get_role_permissions(db, tenant.id, "cost_only"))
    db.close()
