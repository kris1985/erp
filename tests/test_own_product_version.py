"""产品完整档案版本：每次创建/保存落快照，可只读查看。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Color, OwnProductVersion, Tenant, Employee
from app.services import rbac_service


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_own_product_version_on_create_and_every_save():
    db = _session()
    tenant = Tenant(name="版本厂")
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

        create_body = {
            "product_code": "VER-001",
            "product_year": 2026,
            "season": "SS",
            "color_ids": [color.id],
            "materials": [],
            "labors": [],
            "quotes": [],
            "brand_quotes": [],
            "other_costs": [],
            "quote_price": 100,
        }
        created = client.post("/api/v1/own-products", json=create_body, headers=headers)
        assert created.status_code == 200, created.text
        product_id = created.json()["data"]["id"]

        versions = list(
            db.scalars(
                select(OwnProductVersion).where(
                    OwnProductVersion.own_product_id == product_id
                )
            ).all()
        )
        assert len(versions) == 1
        assert versions[0].version_no == 1
        assert versions[0].source == "product_create"
        assert versions[0].changed_by == admin.id
        assert versions[0].snapshot.get("product_code") == "VER-001"
        assert versions[0].changed_sections == ["create"]

        # 相同内容连续保存两次，也应各记一条，且变更板块为空
        patch_body = {
            "product_code": "VER-001",
            "product_year": 2026,
            "season": "SS",
            "color_ids": [color.id],
            "materials": [],
            "labors": [],
            "quotes": [],
            "brand_quotes": [],
            "other_costs": [],
            "quote_price": 100,
        }
        for _ in range(2):
            updated = client.patch(
                f"/api/v1/own-products/{product_id}",
                json=patch_body,
                headers=headers,
            )
            assert updated.status_code == 200, updated.text

        # 改统一报价 → 应标记产品信息
        changed = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={**patch_body, "quote_price": 120},
            headers=headers,
        )
        assert changed.status_code == 200, changed.text

        listed = client.get(
            f"/api/v1/own-products/{product_id}/versions",
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        items = listed.json()["data"]["items"]
        assert len(items) == 4
        assert [i["version_no"] for i in items] == [4, 3, 2, 1]
        assert items[0]["changed_by"] == admin.id
        assert items[0]["changed_by_name"] == "管理员"
        assert items[0]["source"] == "product_save"
        assert items[0]["changed_sections"] == ["info"]
        assert items[0]["changed_section_labels"] == ["产品信息"]
        assert items[1]["changed_sections"] == []
        assert items[2]["changed_sections"] == []
        assert items[3]["source"] == "product_create"
        assert items[3]["changed_sections"] == ["create"]
        assert items[3]["changed_section_labels"] == ["新建"]

        detail = client.get(
            f"/api/v1/own-products/{product_id}/versions/{items[0]['id']}",
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        body = detail.json()["data"]
        snap = body["snapshot"]
        assert snap["product_code"] == "VER-001"
        assert snap["quote_price"] == "120.0000" or float(snap["quote_price"]) == 120
        assert body["changed_sections"] == ["info"]
        assert "labors" in snap
        assert "materials" in snap
        assert "quotes" in snap

        # 跨产品不可读
        other = client.post(
            "/api/v1/own-products",
            json={**create_body, "product_code": "VER-002"},
            headers=headers,
        )
        assert other.status_code == 200, other.text
        other_id = other.json()["data"]["id"]
        cross = client.get(
            f"/api/v1/own-products/{other_id}/versions/{items[0]['id']}",
            headers=headers,
        )
        assert cross.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
