"""物料身份标：二维码指向本租户物料，扫码按编号读取。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.supplier_products import material_label_scan_url, request_public_origin
from app.auth import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import Employee, Partner, SupplierProduct, Tenant


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


def test_material_label_scan_url_uses_print_page_origin():
    class _Req:
        headers = {"referer": "http://127.0.0.1:5173/admin/supplier-products/print?ids=1"}

        @property
        def base_url(self):
            return "http://127.0.0.1:8000/"

    origin = request_public_origin(_Req())  # type: ignore[arg-type]
    assert origin == "http://127.0.0.1:5173"
    assert material_label_scan_url(origin, "皮/A 1") == "http://127.0.0.1:5173/material?code=%E7%9A%AE%2FA%201"


def test_material_label_qr_and_lookup_stay_in_tenant():
    session = _session()
    tenant = Tenant(name="标签厂")
    other = Tenant(name="别厂")
    session.add_all([tenant, other])
    session.flush()
    supplier = Partner(tenant_id=tenant.id, name="皮料商", is_supplier=True, is_active=True)
    session.add(supplier)
    session.flush()
    product = SupplierProduct(
        tenant_id=tenant.id,
        partner_id=supplier.id,
        product_code="LEATHER-1",
        name="黑皮",
        is_active=True,
    )
    session.add(product)
    user = Employee(tenant_id=tenant.id, name="仓管", is_active=True)
    outsider = Employee(tenant_id=other.id, name="外人", is_active=True)
    session.add_all([user, outsider])
    session.commit()

    client = _client(session)
    try:
        headers = {"Authorization": f"Bearer {create_access_token(user)}"}
        png = client.get(
            f"/api/v1/supplier-products/{product.id}/qr.png",
            headers={**headers, "Referer": "http://shop.example/admin/supplier-products/print"},
        )
        assert png.status_code == 200
        assert png.headers["content-type"].startswith("image/png")
        assert png.content.startswith(b"\x89PNG")

        found = client.get("/api/v1/supplier-products/by-code", params={"code": "LEATHER-1"}, headers=headers)
        assert found.status_code == 200
        assert found.json()["data"]["name"] == "黑皮"
        assert found.json()["data"]["partner_name"] == "皮料商"

        foreign = client.get(
            f"/api/v1/supplier-products/{product.id}/qr.png",
            headers={"Authorization": f"Bearer {create_access_token(outsider)}"},
        )
        assert foreign.status_code == 404
        missing = client.get(
            "/api/v1/supplier-products/by-code",
            params={"code": "LEATHER-1"},
            headers={"Authorization": f"Bearer {create_access_token(outsider)}"},
        )
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
