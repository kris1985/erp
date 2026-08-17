"""干掉生产单 K1：禁止手建/导入生产单。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Tenant, Employee
from app.services import rbac_service


def test_http_create_and_import_order_blocked():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    tenant = Tenant(name="杀单厂")
    db.add(tenant)
    db.flush()
    user = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    db.add(user)
    db.flush()
    rbac_service.set_employee_roles(db, user, ["admin"])
    db.commit()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", json={"identifier": "admin", "password": "admin123"})
            assert login.status_code == 200
            token = login.json()["data"]["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            r = client.post(
                "/api/v1/orders",
                headers=headers,
                json={
                    "customer_name": "x",
                    "own_product_id": 1,
                    "items": [{"color_id": 1, "size_id": 1, "qty": 1}],
                },
            )
            assert r.status_code == 400
            assert "停用" in (r.json().get("detail") or "")
            r2 = client.get("/api/v1/orders/import-template", headers=headers)
            assert r2.status_code == 400
            assert "停用" in (r2.json().get("detail") or "")
    finally:
        app.dependency_overrides.clear()
        db.close()
