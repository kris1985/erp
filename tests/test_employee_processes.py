from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Employee, ProcessDefinition, ProcessSegment, Tenant


def test_employee_process_ids_roundtrip():
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
    db.add(cut)
    db.flush()
    proc_a = ProcessDefinition(tenant_id=tenant.id, name="下料", code="cut-a", segment_id=cut.id)
    proc_b = ProcessDefinition(tenant_id=tenant.id, name="画线", code="cut-b", segment_id=cut.id)
    db.add_all([proc_a, proc_b])
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        name="管理员",
        username="admin",
        password_hash=hash_password("123456"),
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
        create = client.post(
            "/api/v1/employees",
            json={"name": "张三", "username": "zhangsan", "process_ids": [proc_a.id, proc_b.id]},
            headers=headers,
        )
        assert create.status_code == 200, create.text
        body = create.json()["data"]
        assert body["process_ids"] == [proc_a.id, proc_b.id]
        assert body["process_names"] == ["下料", "画线"]

        listed = client.get("/api/v1/employees", params={"process_id": proc_a.id}, headers=headers)
        assert listed.status_code == 200
        assert [row["name"] for row in listed.json()["data"]["items"]] == ["张三"]
    finally:
        app.dependency_overrides.clear()
        db.close()
