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
