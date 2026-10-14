"""产品开发：楦型 / 鞋底型号 / 鞋跟型号只能从对应物料分类选择。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Color, Employee, MaterialCategory, Partner, SupplierProduct, Tenant
from app.services import rbac_service


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_own_product_last_sole_heel_from_color_cards():
    db = _session()
    tenant = Tenant(name="楦型厂")
    other = Tenant(name="别厂")
    db.add_all([tenant, other])
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
    partner = Partner(tenant_id=tenant.id, name="鞋跟厂", is_supplier=True, is_active=True)
    other_partner = Partner(tenant_id=other.id, name="外厂", is_supplier=True, is_active=True)
    last_cat = MaterialCategory(tenant_id=tenant.id, name="楦头", is_active=True, suggest_usage_by_size=True)
    sole_cat = MaterialCategory(tenant_id=tenant.id, name="鞋底", is_active=True, suggest_usage_by_size=True)
    heel_cat = MaterialCategory(tenant_id=tenant.id, name="鞋跟", is_active=True, suggest_usage_by_size=True)
    leather_cat = MaterialCategory(tenant_id=tenant.id, name="皮料", is_active=True)
    db.add_all([color, partner, other_partner, last_cat, sole_cat, heel_cat, leather_cat])
    db.flush()
    last_card = SupplierProduct(
        tenant_id=tenant.id,
        product_code="XT-36",
        name="36女楦",
        partner_id=partner.id,
        category_id=last_cat.id,
        is_active=True,
    )
    sole_card = SupplierProduct(
        tenant_id=tenant.id,
        product_code="DD-01",
        name="大底A",
        partner_id=partner.id,
        category_id=sole_cat.id,
        is_active=True,
    )
    heel = SupplierProduct(
        tenant_id=tenant.id,
        product_code="XG-01",
        name="中跟",
        partner_id=partner.id,
        category_id=heel_cat.id,
        is_active=True,
    )
    heel2 = SupplierProduct(
        tenant_id=tenant.id,
        product_code="XG-02",
        name="坡跟",
        partner_id=partner.id,
        category_id=heel_cat.id,
        is_active=True,
    )
    leather = SupplierProduct(
        tenant_id=tenant.id,
        product_code="PL-01",
        name="黑皮",
        partner_id=partner.id,
        category_id=leather_cat.id,
        is_active=True,
    )
    foreign = SupplierProduct(
        tenant_id=other.id,
        product_code="XG-X",
        name="外厂鞋跟",
        partner_id=other_partner.id,
        is_active=True,
    )
    db.add_all([last_card, sole_card, heel, heel2, leather, foreign])
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

        free_text = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SL-00",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [color.id],
                "shoe_last": "手填楦型",
            },
            headers=headers,
        )
        assert free_text.status_code == 400
        assert "物料色卡" in free_text.json()["detail"]

        created = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SL-01",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [color.id],
                "shoe_last_product_id": last_card.id,
                "sole_mold_product_id": sole_card.id,
                "heel_model_id": heel.id,
                "heel_model_2_id": heel2.id,
                "shoe_last_hours": 2.5,
                "fabric": "羊皮",
                "lining": "猪皮",
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        data = created.json()["data"]
        assert data["shoe_last"] == "XT-36"
        assert data["shoe_last_product_id"] == last_card.id
        assert data["shoe_last_code"] == "XT-36"
        assert data["sole_mold"] == "DD-01"
        assert data["sole_mold_product_id"] == sole_card.id
        assert data["sole_mold_code"] == "DD-01"
        assert data["heel_model_id"] == heel.id
        assert data["heel_model_code"] == "XG-01"
        assert data["heel_model_name"] == "中跟"
        assert data["heel_model_2_id"] == heel2.id
        assert data["heel_model_2_code"] == "XG-02"
        assert float(data["shoe_last_hours"]) == 2.5
        assert data["fabric"] == "羊皮"
        assert data["lining"] == "猪皮"

        history = client.get("/api/v1/own-products/field-history", headers=headers)
        assert history.status_code == 200, history.text
        assert history.json()["data"]["fabrics"] == ["羊皮"]
        assert history.json()["data"]["linings"] == ["猪皮"]

        wrong_category = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SL-02",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [color.id],
                "shoe_last_product_id": leather.id,
            },
            headers=headers,
        )
        assert wrong_category.status_code == 400
        assert "楦头" in wrong_category.json()["detail"]

        wrong_sole = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "SL-03",
                "product_year": 2026,
                "season": "SP",
                "color_ids": [color.id],
                "sole_mold_product_id": last_card.id,
            },
            headers=headers,
        )
        assert wrong_sole.status_code == 400
        assert "鞋底" in wrong_sole.json()["detail"]

        listed = client.get(
            "/api/v1/own-products",
            params={"shoe_last": "XT-36"},
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["data"]["total"] == 1

        rejected = client.patch(
            f"/api/v1/own-products/{data['id']}",
            json={"heel_model_2_id": foreign.id},
            headers=headers,
        )
        assert rejected.status_code == 400
        assert "物料色卡" in rejected.json()["detail"]

        missing = client.patch(
            f"/api/v1/own-products/{data['id']}",
            json={"shoe_last_product_id": 999999},
            headers=headers,
        )
        assert missing.status_code == 400

        patched = client.patch(
            f"/api/v1/own-products/{data['id']}",
            json={
                "shoe_last_product_id": None,
                "sole_mold_product_id": None,
                "heel_model_id": None,
                "heel_model_2_id": None,
                "shoe_last_hours": 3.0,
            },
            headers=headers,
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()["data"]
        assert body["shoe_last"] is None
        assert body["shoe_last_product_id"] is None
        assert body["sole_mold"] is None
        assert body["sole_mold_product_id"] is None
        assert body["heel_model_id"] is None
        assert body["heel_model_code"] is None
        assert body["heel_model_2_id"] is None
        assert float(body["shoe_last_hours"]) == 3.0
    finally:
        app.dependency_overrides.clear()
