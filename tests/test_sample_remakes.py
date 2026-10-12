from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Employee, OwnProduct, Partner, Tenant


def test_sample_remake_header_lines_roundtrip():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="复版测试厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id,
        name="管理员",
        username="admin",
        password_hash=hash_password("123456"),
        is_active=True,
    )
    customer = Partner(tenant_id=tenant.id, name="华东客户", is_customer=True, is_active=True)
    product = OwnProduct(tenant_id=tenant.id, product_code="TYL-1001", image_url="/uploads/a.png")
    db.add_all([admin, customer, product])
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {create_access_token(admin)}"}
        created = client.post(
            "/api/v1/sample-remakes",
            headers=headers,
            json={
                "remake_date": "2026-09-28",
                "courier_company": "顺丰",
                "tracking_no": "SF001",
                "customer_id": customer.id,
                "lines": [
                    {
                        "brand": "甲牌",
                        "own_product_id": product.id,
                        "factory_model": "TYL-1001",
                        "image_url": "/uploads/a.png",
                        "color": "黑",
                        "qty": 2,
                        "unit_price": 12.5,
                    },
                    {
                        "brand": "乙牌",
                        "factory_model": "手填型号",
                        "color": "白",
                        "qty": 1,
                        "unit_price": 8,
                    },
                ],
            },
        )
        assert created.status_code == 200, created.text
        body = created.json()["data"]
        assert body["delivery_no"].startswith("FB20260928")
        assert body["customer_name"] == "华东客户"
        assert len(body["lines"]) == 2
        assert body["lines"][0]["total_price"] == 25
        assert body["total_qty"] == 3

        listed = client.get(
            "/api/v1/sample-remakes",
            headers=headers,
            params={"keyword": "手填型号"},
        )
        assert listed.status_code == 200
        assert listed.json()["data"]["total"] == 1

        updated = client.put(
            f"/api/v1/sample-remakes/{body['id']}",
            headers=headers,
            json={
                "remake_date": "2026-09-28",
                "delivery_no": body["delivery_no"],
                "courier_company": "中通",
                "tracking_no": "ZT9",
                "customer_id": customer.id,
                "lines": [
                    {
                        "brand": "甲牌",
                        "factory_model": "TYL-1001",
                        "color": "黑",
                        "qty": 3,
                        "unit_price": 10,
                    }
                ],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["courier_company"] == "中通"
        assert len(updated.json()["data"]["lines"]) == 1
        assert updated.json()["data"]["lines"][0]["total_price"] == 30

        missing = client.post(
            "/api/v1/sample-remakes",
            headers=headers,
            json={
                "remake_date": "2026-09-28",
                "customer_id": 99999,
                "lines": [{"factory_model": "X", "qty": 1, "unit_price": 1}],
            },
        )
        assert missing.status_code == 400

        deleted = client.delete(f"/api/v1/sample-remakes/{body['id']}", headers=headers)
        assert deleted.status_code == 200
        gone = client.get(f"/api/v1/sample-remakes/{body['id']}", headers=headers)
        assert gone.status_code == 404
    finally:
        app.dependency_overrides.clear()
        db.close()
