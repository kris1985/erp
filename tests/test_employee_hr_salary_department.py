from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.db import Base, get_db
from app.main import app
from app.models import (
    DefectDisposition,
    DefectEvent,
    DefectEventStatus,
    DefectResponsibility,
    Department,
    Employee,
    ReportType,
    SalaryModel,
    Tenant,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
)


def test_employee_hr_fields_and_salary_department_filter():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="人事测试厂")
    db.add(tenant)
    db.flush()
    parent = Department(tenant_id=tenant.id, name="生产部", sort_order=1)
    other = Department(tenant_id=tenant.id, name="行政部", sort_order=2)
    db.add_all([parent, other])
    db.flush()
    child = Department(tenant_id=tenant.id, name="针车部", parent_id=parent.id, sort_order=1)
    db.add(child)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        name="管理员",
        username="admin",
        password_hash=hash_password("123456"),
        department_id=other.id,
        salary_model=SalaryModel.fixed,
        base_salary=Decimal("5000"),
        is_active=True,
    )
    db.add(admin)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {create_access_token(admin)}"}
        created = client.post(
            "/api/v1/employees",
            json={
                "name": "张三",
                "username": "zhangsan",
                "department_id": child.id,
                "hire_date": "2026-08-18",
                "identity_card_no": "350123199001011234",
                "emergency_contact": "李四",
                "emergency_phone": "13900001111",
                "salary_model": "fixed",
                "base_salary": 6000,
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        employee = created.json()["data"]
        assert employee["hire_date"] == "2026-08-18"
        assert employee["identity_card_no"] == "350123199001011234"
        assert employee["emergency_contact"] == "李四"
        assert employee["emergency_phone"] == "13900001111"

        salary = client.get(
            "/api/v1/salary",
            params={"year_month": "2026-08", "department_id": parent.id},
            headers=headers,
        )
        assert salary.status_code == 200, salary.text
        data = salary.json()["data"]
        assert data["summary"]["count"] == 1
        assert data["summary"]["total_wage"] == 6000.0
        assert data["items"][0]["department_id"] == child.id
        assert data["items"][0]["department_name"] == "针车部"

        default_date = client.post(
            "/api/v1/employees",
            json={"name": "王五", "username": "wangwu"},
            headers=headers,
        )
        assert default_date.status_code == 200, default_date.text
        assert default_date.json()["data"]["hire_date"] == date.today().isoformat()

        left = client.patch(
            f"/api/v1/employees/{employee['id']}",
            json={"is_active": False},
            headers=headers,
        )
        assert left.status_code == 200, left.text
        assert left.json()["data"]["is_active"] is False
        assert left.json()["data"]["leave_date"] == date.today().isoformat()

        back = client.patch(
            f"/api/v1/employees/{employee['id']}",
            json={"is_active": True},
            headers=headers,
        )
        assert back.status_code == 200, back.text
        assert back.json()["data"]["is_active"] is True
        assert back.json()["data"]["leave_date"] is None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_employee_list_cumulative_wage_loss_ratio():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="计件厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        name="管理员",
        username="admin",
        password_hash=hash_password("123456"),
        is_active=True,
    )
    worker = Employee(tenant_id=tenant.id, name="计件员", username="piece", is_active=True)
    db.add_all([admin, worker])
    db.flush()
    db.add_all(
        [
            WorkLog(
                tenant_id=tenant.id,
                worker_id=worker.id,
                order_process_id=1,
                own_product_id=1,
                process_id=1,
                report_type=ReportType.normal,
                qualified_qty=Decimal("10"),
                defect_qty=Decimal("1"),
                unit_price=Decimal("2.50"),
                loss_amount=Decimal("10"),
                loss_borne_percent=50,
                source=WorkLogSource.manual,
                status=WorkLogStatus.valid,
            ),
            WorkLog(
                tenant_id=tenant.id,
                worker_id=worker.id,
                order_process_id=1,
                own_product_id=1,
                process_id=1,
                report_type=ReportType.normal,
                qualified_qty=Decimal("100"),
                unit_price=Decimal("9"),
                source=WorkLogSource.cut_basket,
                status=WorkLogStatus.valid,
            ),
            WorkLog(
                tenant_id=tenant.id,
                worker_id=worker.id,
                order_process_id=1,
                own_product_id=1,
                process_id=1,
                report_type=ReportType.normal,
                qualified_qty=Decimal("8"),
                unit_price=Decimal("3"),
                source=WorkLogSource.manual,
                status=WorkLogStatus.void,
            ),
        ]
    )
    event = DefectEvent(
        tenant_id=tenant.id,
        defect_type="开胶",
        qty=1,
        disposition=DefectDisposition.scrap,
        status=DefectEventStatus.closed,
        wage_deduction_from_event=True,
        loss_amount=Decimal("40"),
        responsible_worker_id=worker.id,
    )
    db.add(event)
    db.flush()
    db.add(
        DefectResponsibility(
            tenant_id=tenant.id,
            defect_event_id=event.id,
            worker_id=worker.id,
            share_percent=25,
        )
    )
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {create_access_token(admin)}"}
        listed = client.get("/api/v1/employees", params={"keyword": "计件员"}, headers=headers)
        assert listed.status_code == 200, listed.text
        row = listed.json()["data"]["items"][0]
        assert Decimal(str(row["cumulative_wage"])) == Decimal("25.00")
        assert Decimal(str(row["cumulative_loss"])) == Decimal("15.00")
        assert Decimal(str(row["loss_wage_ratio"])) == Decimal("60.00")
    finally:
        app.dependency_overrides.clear()
        db.close()
