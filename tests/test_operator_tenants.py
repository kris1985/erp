"""运营入口：租户开通、截止日和停用。"""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import Employee, Tenant


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), db


def _login_ops(client: TestClient) -> dict:
    settings = get_settings()
    res = client.post(
        "/api/v1/operators/login",
        json={"username": settings.operator_username, "password": settings.operator_password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}


def test_operator_tenant_crud_and_expiry():
    client, db = _client()
    try:
        denied = client.get("/api/v1/operators/tenants")
        assert denied.status_code == 401

        headers = _login_ops(client)
        created = client.post(
            "/api/v1/operators/tenants",
            headers=headers,
            json={
                "name": "南湖鞋厂",
                "admin_name": "王厂",
                "admin_mobile": "13900001111",
                "password": "secret1",
                "expires_on": (date.today() + timedelta(days=10)).isoformat(),
                "notes": "试用",
                "is_active": True,
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()["data"]
        assert body["admin_mobile"] == "13900001111"
        assert body["status"] == "active"
        tenant_id = body["id"]

        login = client.post("/api/v1/auth/login", json={"identifier": "13900001111", "password": "secret1"})
        assert login.status_code == 200, login.text

        updated = client.put(
            f"/api/v1/operators/tenants/{tenant_id}",
            headers=headers,
            json={
                "name": "南湖鞋厂",
                "admin_name": "王厂",
                "admin_mobile": "13900001111",
                "expires_on": (date.today() - timedelta(days=1)).isoformat(),
                "is_active": True,
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["status"] == "expired"
        blocked = client.post("/api/v1/auth/login", json={"identifier": "13900001111", "password": "secret1"})
        assert blocked.status_code == 403
        assert "到期" in blocked.json()["detail"]

        listed = client.get("/api/v1/operators/tenants", headers=headers, params={"keyword": "南湖"})
        assert listed.status_code == 200
        assert listed.json()["data"][0]["id"] == tenant_id

        removed = client.delete(f"/api/v1/operators/tenants/{tenant_id}", headers=headers)
        assert removed.status_code == 200, removed.text
        assert db.scalar(select(Tenant).where(Tenant.id == tenant_id)) is None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_same_admin_mobile_allowed_across_tenants():
    client, db = _client()
    try:
        headers = _login_ops(client)
        first = client.post(
            "/api/v1/operators/tenants",
            headers=headers,
            json={
                "name": "甲厂",
                "admin_name": "王总",
                "admin_mobile": "13900003333",
                "password": "secret1",
            },
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/api/v1/operators/tenants",
            headers=headers,
            json={
                "name": "乙厂",
                "admin_name": "王总",
                "admin_mobile": "13900003333",
                "password": "secret1",
            },
        )
        assert second.status_code == 200, second.text
        assert first.json()["data"]["id"] != second.json()["data"]["id"]

        login = client.post(
            "/api/v1/auth/login",
            json={"identifier": "13900003333", "password": "secret1"},
        )
        assert login.status_code == 200, login.text
        payload = login.json()["data"]
        assert payload.get("need_select") is True
        assert {t["tenant_id"] for t in payload["tenants"]} == {
            first.json()["data"]["id"],
            second.json()["data"]["id"],
        }
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_delete_refuses_tenant_with_staff():
    client, db = _client()
    try:
        headers = _login_ops(client)
        created = client.post(
            "/api/v1/operators/tenants",
            headers=headers,
            json={
                "name": "有人的厂",
                "admin_mobile": "13900002222",
                "password": "secret1",
            },
        )
        assert created.status_code == 200, created.text
        tenant_id = created.json()["data"]["id"]
        db.add(Employee(tenant_id=tenant_id, name="工人甲", is_active=True))
        db.commit()
        removed = client.delete(f"/api/v1/operators/tenants/{tenant_id}", headers=headers)
        assert removed.status_code == 400
        assert "停用" in removed.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        db.close()
