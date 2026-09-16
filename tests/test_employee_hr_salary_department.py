from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Department, Employee, SalaryModel, Tenant


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
    finally:
        app.dependency_overrides.clear()
        db.close()
