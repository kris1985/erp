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
