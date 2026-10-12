"""底模不送货，直接录入供应商待结算。"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Employee, Partner, SoleMold, SupplierProduct, Tenant
from app.services import rbac_service


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _client(db):
    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    client = TestClient(app)
    token = client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin", "password": "admin123"},
    ).json()["data"]["access_token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_sole_mold_entry_lands_on_supplier_pending():
    db = _session()
    tenant = Tenant(name="底模厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    supplier = Partner(tenant_id=tenant.id, name="底模供应商", short_name="底厂", is_supplier=True, is_active=True)
    db.add_all([admin, supplier])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    db.commit()

    try:
        client, headers = _client(db)
        created = client.post(
            "/api/v1/sole-molds/entries",
            json={
                "code": "DM-18",
                "name": "女鞋底模",
                "supplier_id": supplier.id,
                "unit_price": "80",
                "qty": 2,
                "ordered_at": "2026-10-08 09:30:00",
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        body = created.json()["data"]
        assert body["amount"] == 160
        assert body["code"] == "DM-18"

        pending = client.get(
            "/api/v1/payables/pending-lines",
            params={"supplier_id": supplier.id},
            headers=headers,
        )
        assert pending.status_code == 200, pending.text
        rows = pending.json()["data"]["items"]
        assert len(rows) == 1
        row = rows[0]
        assert row["source_type"] == "sole_mold"
        assert row["item_code"] == "DM-18"
        assert row["item_name"] == "女鞋底模"
        assert row["supplier_name"] == "底厂"
        assert row["unit_name"] == "套"
        assert float(row["unit_price"]) == 80
        assert float(row["order_qty"]) == 2
        assert row["qty"] is None
        assert row["received_at"] is None
        assert row["delivery_note_no"] is None
        assert row["po_no"] is None
        assert row["ordered_at"].startswith("2026-10-08")
        assert float(row["amount"]) == 160
        assert pending.json()["data"]["balance"]["pending_amount"] in (160, "160", "160.0000")

        again = client.post(
            "/api/v1/sole-molds/entries",
            json={
                "code": "DM-18",
                "name": "女鞋底模改",
                "supplier_id": supplier.id,
                "unit_price": "10",
                "qty": 1,
                "ordered_at": "2026-10-08 10:00:00",
            },
            headers=headers,
        )
        assert again.status_code == 200, again.text
        assert db.scalar(select(func.count()).select_from(SoleMold).where(SoleMold.tenant_id == tenant.id)) == 1
        assert db.get(SoleMold, body["sole_mold_id"]).name == "女鞋底模改"

        catalog = client.get("/api/v1/sole-molds", headers=headers)
        assert catalog.status_code == 200
        assert catalog.json()["data"]["items"][0]["code"] == "DM-18"

        pending2 = client.get(
            "/api/v1/payables/pending-lines",
            params={"supplier_id": supplier.id},
            headers=headers,
        )
        items = pending2.json()["data"]["items"]
        assert len(items) == 2
        first = next(item for item in items if item["item_name"] == "女鞋底模")
        assert first["item_name"] == "女鞋底模"

        statement = client.post(
            "/api/v1/payables/purchase-statements",
            json={
                "supplier_id": supplier.id,
                "line_ids": [row["line_id"]],
                "remainder_payable_ids": [],
                "statement_no": "DM-STMT-1",
                "statement_date": date.today().isoformat(),
            },
            headers=headers,
        )
        assert statement.status_code == 200, statement.text
        assert float(statement.json()["data"]["current_amount"]) == 160

        leftover = client.get(
            "/api/v1/payables/pending-lines",
            params={"supplier_id": supplier.id},
            headers=headers,
        )
        left = leftover.json()["data"]["items"]
        assert len(left) == 1
        assert float(left[0]["amount"]) == 10
        assert db.scalar(select(func.count()).select_from(SupplierProduct)) == 0
    finally:
        app.dependency_overrides.clear()
