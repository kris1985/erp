"""物料色卡更换供应商时留下历史。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import Employee, Partner, SupplierProduct, SupplierProductSupplierHistory, Tenant


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _client(session):
    def _get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def test_changing_supplier_keeps_history():
    session = _session()
    tenant = Tenant(name="色卡厂")
    session.add(tenant)
    session.flush()
    first = Partner(tenant_id=tenant.id, name="甲商", is_supplier=True, is_active=True)
    second = Partner(tenant_id=tenant.id, name="乙商", is_supplier=True, is_active=True)
    user = Employee(tenant_id=tenant.id, name="管理员", username="admin", is_active=True)
    session.add_all([first, second, user])
    session.commit()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    try:
        created = client.post(
            "/api/v1/supplier-products",
            headers=headers,
            json={"product_code": "ML-S", "name": "皮", "partner_id": first.id},
        )
        assert created.status_code == 200, created.text
        product_id = created.json()["data"]["id"]
        assert session.scalar(select(func.count()).select_from(SupplierProductSupplierHistory)) == 0

        changed = client.patch(
            f"/api/v1/supplier-products/{product_id}",
            headers=headers,
            json={"partner_id": second.id},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["data"]["partner_name"] == "乙商"

        listed = client.get("/api/v1/supplier-products", headers=headers)
        assert listed.status_code == 200, listed.text
        row = listed.json()["data"]["items"][0]
        assert row["has_supplier_history"] is True
        history = row["supplier_histories"][0]
        assert history["old_partner_name"] == "甲商"
        assert history["new_partner_name"] == "乙商"
        assert history["changed_by_name"] == "管理员"

        again = client.patch(
            f"/api/v1/supplier-products/{product_id}",
            headers=headers,
            json={"partner_id": second.id},
        )
        assert again.status_code == 200, again.text
        session.expire_all()
        product = session.get(SupplierProduct, product_id)
        assert product.partner_id == second.id
        assert session.scalar(select(func.count()).select_from(SupplierProductSupplierHistory)) == 1
    finally:
        app.dependency_overrides.clear()
