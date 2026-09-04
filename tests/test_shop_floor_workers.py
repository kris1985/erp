from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import (
    Department,
    Employee,
    EmployeeProcessAssignment,
    ProcessDefinition,
    ProcessSegment,
    Tenant,
)


def test_workers_can_be_filtered_by_process_segment_without_legacy_role_field():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="测试工厂")
    db.add(tenant)
    db.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="截断", code="cut", sort_order=1)
    stitch = ProcessSegment(tenant_id=tenant.id, name="针车", code="stitch", sort_order=2)
    db.add_all([cut, stitch])
    db.flush()
    cut_department = Department(tenant_id=tenant.id, name="裁断部", process_segment_id=cut.id)
    stitch_department = Department(tenant_id=tenant.id, name="针车部", process_segment_id=stitch.id)
    db.add_all([cut_department, stitch_department])
    db.flush()
    operator = Employee(
        tenant_id=tenant.id,
        name="陈美丽",
        mobile="13800138005",
        department_id=cut_department.id,
        is_active=True,
    )
    colleague = Employee(
        tenant_id=tenant.id,
        name="史珍香",
        mobile="13800138011",
        department_id=cut_department.id,
        is_active=True,
    )
    other_segment = Employee(
        tenant_id=tenant.id,
        name="针车员工",
        department_id=stitch_department.id,
        is_active=True,
    )
    db.add_all([operator, colleague, other_segment])
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/shop-floor-settings/workers",
            params={"segment_code": "cut"},
            headers={"Authorization": f"Bearer {create_access_token(operator)}"},
        )
        assert response.status_code == 200, response.text
        workers = response.json()["data"]
        assert [(row["name"], row["mobile"]) for row in workers] == [
            ("陈美丽", "13800138005"),
            ("史珍香", "13800138011"),
        ]
        assert all(row["role"] == "员工" for row in workers)
        assert all(row["department_name"] == "裁断部" for row in workers)
        assert all(row["process_names"] == [] for row in workers)
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_workers_can_be_filtered_by_process_assignment():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="测试工厂")
    db.add(tenant)
    db.flush()
    cut = ProcessSegment(tenant_id=tenant.id, name="截断", code="cut", sort_order=1)
    stitch = ProcessSegment(tenant_id=tenant.id, name="针车", code="stitch", sort_order=2)
    db.add_all([cut, stitch])
    db.flush()
    cut_proc = ProcessDefinition(
        tenant_id=tenant.id, name="下料", code="cut-blank", segment_id=cut.id, sort_order=1
    )
    stitch_proc = ProcessDefinition(
        tenant_id=tenant.id, name="车帮", code="stitch-upper", segment_id=stitch.id, sort_order=1
    )
    db.add_all([cut_proc, stitch_proc])
    db.flush()
    cut_department = Department(tenant_id=tenant.id, name="裁断部", process_segment_id=cut.id)
    stitch_department = Department(tenant_id=tenant.id, name="针车部", process_segment_id=stitch.id)
    db.add_all([cut_department, stitch_department])
    db.flush()
    cutter = Employee(
        tenant_id=tenant.id,
        name="裁断工",
        mobile="13800138005",
        department_id=cut_department.id,
        is_active=True,
    )
    stitcher = Employee(
        tenant_id=tenant.id,
        name="针车工",
        mobile="13800138011",
        department_id=stitch_department.id,
        is_active=True,
    )
    db.add_all([cutter, stitcher])
    db.flush()
    db.add_all([
        EmployeeProcessAssignment(tenant_id=tenant.id, employee_id=cutter.id, process_id=cut_proc.id),
        EmployeeProcessAssignment(tenant_id=tenant.id, employee_id=stitcher.id, process_id=stitch_proc.id),
    ])
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/shop-floor-settings/workers",
            params={"process_id": cut_proc.id},
            headers={"Authorization": f"Bearer {create_access_token(cutter)}"},
        )
        assert response.status_code == 200, response.text
        workers = response.json()["data"]
        assert [row["name"] for row in workers] == ["裁断工"]
        assert workers[0]["department_name"] == "裁断部"
        assert workers[0]["process_names"] == ["下料"]
    finally:
        app.dependency_overrides.clear()
        db.close()
