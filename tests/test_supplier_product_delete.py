"""删除物料：被业务引用时给出原因，不依赖数据库外键。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import (
    Employee,
    MaterialUsageHistory,
    OwnProduct,
    Partner,
    SupplierProduct,
    Tenant,
)
from app.services import rbac_service


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_supplier_product_code_can_repeat():
    db = _session()
    tenant = Tenant(name="色卡厂")
    db.add(tenant)
    db.flush()
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True)
    db.add(partner)
    db.flush()
    db.add_all(
        [
            SupplierProduct(
                tenant_id=tenant.id,
                product_code="LEA-1",
                name="黑色牛皮",
                partner_id=partner.id,
            ),
            SupplierProduct(
                tenant_id=tenant.id,
                product_code="LEA-1",
                name="白色牛皮",
                partner_id=partner.id,
            ),
        ]
    )
    db.commit()
    codes = list(
        db.scalars(
            select(SupplierProduct.product_code).where(SupplierProduct.tenant_id == tenant.id)
        ).all()
    )
    assert codes == ["LEA-1", "LEA-1"]
    db.close()


def test_duplicate_supplier_product_code_needs_confirm():
    db = _session()
    tenant = Tenant(name="色卡确认厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin2",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True)
    db.add_all([admin, partner])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
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
            "/api/v1/auth/login", json={"identifier": "admin2", "password": "admin123"}
        ).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        body = {"product_code": "LEA-1", "partner_id": partner.id, "name": "黑色"}
        first = client.post("/api/v1/supplier-products", json=body, headers=headers)
        assert first.status_code == 200, first.text
        second = client.post(
            "/api/v1/supplier-products",
            json={**body, "name": "白色"},
            headers=headers,
        )
        assert second.status_code == 409
        assert "已存在" in second.json()["detail"]
        confirmed = client.post(
            "/api/v1/supplier-products",
            json={**body, "name": "白色", "confirm_duplicate": True},
            headers=headers,
        )
        assert confirmed.status_code == 200, confirmed.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def test_supplier_product_has_no_database_foreign_keys():
    pointed = [
        fk
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name == "supplier_products"
    ]
    assert pointed == []


def test_delete_supplier_product_blocked_by_usage_history():
    db = _session()
    tenant = Tenant(name="物料删除厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        username="admin",
        name="管理员",
        password_hash=hash_password("admin123"),
        is_active=True,
    )
    partner = Partner(tenant_id=tenant.id, name="皮料厂", is_supplier=True)
    db.add_all([admin, partner])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    product = OwnProduct(tenant_id=tenant.id, product_code="SHOE-1")
    material = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-1",
        name="黑色牛皮",
        partner_id=partner.id,
    )
    spare = SupplierProduct(
        tenant_id=tenant.id,
        product_code="LEA-2",
        name="未使用皮",
        partner_id=partner.id,
    )
    db.add_all([product, material, spare])
    db.flush()
    db.add(
        MaterialUsageHistory(
            tenant_id=tenant.id,
            own_product_id=product.id,
            product_code=product.product_code,
            supplier_product_id=material.id,
            material_code=material.product_code,
            material_name=material.name,
            new_qty=1,
        )
    )
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
            "/api/v1/auth/login", json={"identifier": "admin", "password": "admin123"}
        ).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        blocked = client.delete(f"/api/v1/supplier-products/{material.id}", headers=headers)
        assert blocked.status_code == 400
        assert blocked.json()["detail"] == "该物料已有用量变更记录，不能删除"
        assert db.get(SupplierProduct, material.id) is not None

        removed = client.delete(f"/api/v1/supplier-products/{spare.id}", headers=headers)
        assert removed.status_code == 200, removed.text
        assert db.get(SupplierProduct, spare.id) is None
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
