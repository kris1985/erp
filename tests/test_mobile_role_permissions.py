from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Employee, Tenant
from app.services import employee_feature_service, rbac_service


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
        "claim_task",
        "expense",
        "material_issue",
        "register_defect",
    ]
    assert rbac_service.employee_effective_base_role(db, employee) == ""

    rbac_service.set_role_permissions(
        db,
        tenant.id,
        "worker",
        ["mobile.register_defect"],
    )

    assert employee_feature_service.list_codes(db, employee) == ["register_defect"]
    assert employee_feature_service.has_feature(db, employee, "register_defect") is True
    assert employee_feature_service.has_feature(db, employee, "claim_task") is False
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
    assert "menu.supplier_products" in manager

    rbac_service.set_employee_roles(db, employee, ["warehouse"])
    codes = set(employee_feature_service.list_codes(db, employee))
    assert "supplier_products" in codes
    assert "supplier_products_write" in codes
    assert "supplier_products_approve" not in codes

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "warehouse")
        if not code.startswith("mobile.supplier_products")
    ]
    kept.append("menu.supplier_products")
    rbac_service.set_role_permissions(db, tenant.id, "warehouse", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
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
    assert "mobile.partners.write" in manager
    assert "menu.customers" in manager

    rbac_service.set_employee_roles(db, employee, ["merchandiser"])
    codes = set(employee_feature_service.list_codes(db, employee))
    assert "partners" in codes
    assert "partners_write" in codes

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "merchandiser")
        if not code.startswith("mobile.partners")
    ]
    kept.append("menu.customers")
    rbac_service.set_role_permissions(db, tenant.id, "merchandiser", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "merchandiser"))
    assert "menu.customers" in after
    assert "mobile.partners" not in after
    assert "mobile.partners.write" not in after
    assert employee_feature_service.has_feature(db, employee, "partners") is False
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
    workshop = set(rbac_service.get_role_permissions(db, tenant.id, "workshop"))
    assert "mobile.attendance_rules.write" in workshop

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
    warehouse = set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    merchandiser = set(rbac_service.get_role_permissions(db, tenant.id, "merchandiser"))
    assert "mobile.purchase_orders" in manager
    assert "mobile.purchase_orders.write" in manager
    assert "mobile.purchase_orders" in warehouse
    assert "mobile.purchase_orders.write" in warehouse
    assert "mobile.purchase_orders" in merchandiser
    assert "mobile.purchase_orders.write" not in merchandiser
    assert "menu.purchase_orders" in merchandiser
    assert "mobile.purchase_orders" not in set(rbac_service.get_role_permissions(db, tenant.id, "worker"))

    rbac_service.set_employee_roles(db, employee, ["merchandiser"])
    assert employee_feature_service.has_feature(db, employee, "purchase_orders") is True
    assert employee_feature_service.has_feature(db, employee, "purchase_orders_write") is False

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "warehouse")
        if not code.startswith("mobile.purchase_orders")
    ]
    kept.append("menu.purchase_orders")
    rbac_service.set_role_permissions(db, tenant.id, "warehouse", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    assert "menu.purchase_orders" in after
    assert "mobile.purchase_orders" not in after
    assert "mobile.purchase_orders.write" not in after
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
    workshop = set(rbac_service.get_role_permissions(db, tenant.id, "workshop"))
    merchandiser = set(rbac_service.get_role_permissions(db, tenant.id, "merchandiser"))
    warehouse = set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    finance = set(rbac_service.get_role_permissions(db, tenant.id, "finance"))
    assert "mobile.cut_material_usage" in manager
    assert "mobile.cut_material_usage.write" in manager
    assert "mobile.cut_material_usage" in workshop
    assert "mobile.cut_material_usage.write" in workshop
    assert "mobile.cut_material_usage" in merchandiser
    assert "mobile.cut_material_usage.write" not in merchandiser
    assert "mobile.cut_material_usage" in warehouse
    assert "mobile.cut_material_usage.write" not in warehouse
    assert "mobile.cut_material_usage" in finance
    assert "mobile.cut_material_usage.write" not in finance
    assert "menu.orders" in workshop
    assert "mobile.cut_material_usage" not in set(rbac_service.get_role_permissions(db, tenant.id, "worker"))

    rbac_service.set_employee_roles(db, employee, ["workshop"])
    assert employee_feature_service.has_feature(db, employee, "cut_material_usage") is True
    assert employee_feature_service.has_feature(db, employee, "cut_material_usage_write") is True

    kept = [
        code
        for code in rbac_service.get_role_permissions(db, tenant.id, "workshop")
        if not code.startswith("mobile.cut_material_usage")
    ]
    kept.append("menu.orders")
    rbac_service.set_role_permissions(db, tenant.id, "workshop", kept)
    rbac_service.ensure_system_roles(db, tenant.id)
    after = set(rbac_service.get_role_permissions(db, tenant.id, "workshop"))
    assert "menu.orders" in after
    assert "mobile.cut_material_usage" not in after
    assert "mobile.cut_material_usage.write" not in after
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
    merchandiser = set(rbac_service.get_role_permissions(db, tenant.id, "merchandiser"))
    warehouse = set(rbac_service.get_role_permissions(db, tenant.id, "warehouse"))
    workshop = set(rbac_service.get_role_permissions(db, tenant.id, "workshop"))
    finance = set(rbac_service.get_role_permissions(db, tenant.id, "finance"))
    assert "mobile.own_products" in manager
    assert "mobile.own_products.write" in manager
    assert "mobile.own_products.approve" in manager
    assert "menu.own_products" in manager
    assert "mobile.own_products" in merchandiser
    assert "mobile.own_products.write" not in merchandiser
    assert "mobile.own_products.approve" not in merchandiser
    assert "mobile.own_products" in warehouse
    assert "mobile.own_products.write" not in warehouse
    assert "mobile.own_products" in workshop
    assert "mobile.own_products.write" not in workshop
    assert "mobile.own_products.approve" not in workshop
    assert "mobile.own_products" not in finance
    assert "mobile.own_products" not in set(rbac_service.get_role_permissions(db, tenant.id, "worker"))

    rbac_service.set_employee_roles(db, employee, ["merchandiser"])
    assert employee_feature_service.has_feature(db, employee, "own_products") is True
    assert employee_feature_service.has_feature(db, employee, "own_products_write") is False
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
    assert "mobile.own_products.write" not in after
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
