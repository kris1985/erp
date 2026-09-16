"""产品信息：楦头绑定模具楦头分类物料 + 占用小时。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Color, MaterialCategory, Partner, SupplierProduct, Tenant, Employee
from app.services import rbac_service


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_own_product_shoe_last_fields():
    db = _session()
    tenant = Tenant(name="楦头厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    db.add(admin)
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    db.add(color)
    cat = MaterialCategory(tenant_id=tenant.id, name="模具楦头", sort_order=1)
    other_cat = MaterialCategory(tenant_id=tenant.id, name="皮料", sort_order=2)
    db.add_all([cat, other_cat])
    db.flush()
    supplier = Partner(tenant_id=tenant.id, name="模具厂", is_supplier=True, is_active=True)
    db.add(supplier)
    db.flush()
    last = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LAST-36",
        name="36楦",
        category_id=cat.id,
        partner_id=supplier.id,
        is_active=True,
    )
    leather = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEATHER-1",
        name="牛皮",
        category_id=other_cat.id,
        partner_id=supplier.id,
        is_active=True,
    )
    db.add_all([last, leather])
    db.commit()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        token = client.post(
            "/api/v1/auth/login",
            json={"identifier": "admin", "password": "admin123"},
        ).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        bad = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SL-BAD",
                "product_year": 2026,
                "season": "SS",
                "color_ids": [color.id],
                "shoe_last_id": leather.id,
                "shoe_last_hours": 1.5,
            },
            headers=headers,
        )
        assert bad.status_code == 400

        ok = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SL-01",
                "product_year": 2026,
                "season": "SS",
                "color_ids": [color.id],
                "shoe_last_id": last.id,
                "shoe_last_hours": 2.5,
            },
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        data = ok.json()["data"]
        assert data["shoe_last_id"] == last.id
        assert data["shoe_last_code"] == "LAST-36"
        assert data["shoe_last_name"] == "36楦"
        assert float(data["shoe_last_hours"]) == 2.5

        patched = client.patch(
            f"/api/v1/own-products/{data['id']}",
            json={"shoe_last_hours": 3.0, "shoe_last_id": None},
            headers=headers,
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()["data"]
        assert body["shoe_last_id"] is None
        assert float(body["shoe_last_hours"]) == 3.0
    finally:
        app.dependency_overrides.clear()
