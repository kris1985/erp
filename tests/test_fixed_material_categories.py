"""鞋底、鞋跟是系统分类：自动补齐，名称和按码不可改，也不能停用。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import Employee, MaterialCategory, Partner, SupplierProduct, Tenant


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


def test_material_category_auxiliary_defaults_off():
    session = _session()
    tenant = Tenant(name="辅料分类厂")
    session.add(tenant)
    session.flush()
    user = Employee(tenant_id=tenant.id, name="资料员", username="admin", is_active=True)
    session.add(user)
    session.commit()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    try:
        created = client.post(
            "/api/v1/material-categories",
            json={"name": "拉链"},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        assert created.json()["data"]["is_auxiliary"] is False
        marked = client.post(
            "/api/v1/material-categories",
            json={"name": "包装辅料", "is_auxiliary": True},
            headers=headers,
        )
        assert marked.status_code == 200, marked.text
        assert marked.json()["data"]["is_auxiliary"] is True
    finally:
        app.dependency_overrides.clear()


def test_sole_and_heel_categories_are_fixed():
    session = _session()
    tenant = Tenant(name="分类厂")
    session.add(tenant)
    session.flush()
    user = Employee(tenant_id=tenant.id, name="资料员", username="admin", is_active=True)
    session.add(user)
    session.commit()
    client = _client(session)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    try:
        listed = client.get("/api/v1/material-categories", headers=headers)
        assert listed.status_code == 200, listed.text
        by_name = {row["name"]: row for row in listed.json()["data"]["items"]}
        assert set(by_name) >= {"鞋底", "鞋跟"}
        for name in ("鞋底", "鞋跟"):
            row = by_name[name]
            assert row["name_locked"] is True
            assert row["suggest_usage_by_size_locked"] is True
            assert row["suggest_usage_by_size"] is True
            assert row["is_active"] is True

        sole = by_name["鞋底"]
        renamed = client.patch(
            f"/api/v1/material-categories/{sole['id']}",
            headers=headers,
            json={"name": "大底外"},
        )
        assert renamed.status_code == 400
        assert "鞋底" in renamed.json()["detail"]

        unsized = client.patch(
            f"/api/v1/material-categories/{sole['id']}",
            headers=headers,
            json={"suggest_usage_by_size": False},
        )
        assert unsized.status_code == 400
        assert "按码" in unsized.json()["detail"]

        removed = client.patch(
            f"/api/v1/material-categories/{sole['id']}",
            headers=headers,
            json={"is_active": False},
        )
        assert removed.status_code == 400
        assert "删除" in removed.json()["detail"]

        kept = session.scalar(select(MaterialCategory).where(MaterialCategory.name == "鞋底"))
        assert kept.is_active is True
        assert kept.suggest_usage_by_size is True
        assert kept.name == "鞋底"

        blocked = client.delete(f"/api/v1/material-categories/{sole['id']}", headers=headers)
        assert blocked.status_code == 400
        assert "删除" in blocked.json()["detail"]

        created = client.post(
            "/api/v1/material-categories",
            headers=headers,
            json={"name": "试删分类", "sort_order": 9},
        )
        assert created.status_code == 200, created.text
        custom_id = created.json()["data"]["id"]
        removed_custom = client.delete(
            f"/api/v1/material-categories/{custom_id}",
            headers=headers,
        )
        assert removed_custom.status_code == 200, removed_custom.text
        assert removed_custom.json()["data"]["deleted"] is True
        session.expire_all()
        assert session.get(MaterialCategory, custom_id) is None

        legacy = client.post(
            "/api/v1/material-categories",
            headers=headers,
            json={"name": "模具楦头", "sort_order": 11, "suggest_usage_by_size": False},
        )
        assert legacy.status_code == 200, legacy.text
        legacy_body = legacy.json()["data"]
        assert legacy_body["name_locked"] is False
        removed_legacy = client.delete(
            f"/api/v1/material-categories/{legacy_body['id']}",
            headers=headers,
        )
        assert removed_legacy.status_code == 200, removed_legacy.text

        again = client.post(
            "/api/v1/material-categories",
            headers=headers,
            json={"name": "在用分类", "sort_order": 10},
        )
        assert again.status_code == 200, again.text
        used_id = again.json()["data"]["id"]
        partner = Partner(tenant_id=tenant.id, name="分类供应商", is_supplier=True)
        session.add(partner)
        session.flush()
        session.add(
            SupplierProduct(
                tenant_id=tenant.id,
                product_code="CAT-1",
                name="在用物料",
                category_id=used_id,
                partner_id=partner.id,
            )
        )
        session.commit()
        in_use = client.delete(f"/api/v1/material-categories/{used_id}", headers=headers)
        assert in_use.status_code == 400
        assert "物料" in in_use.json()["detail"]
        assert session.get(MaterialCategory, used_id) is not None
    finally:
        app.dependency_overrides.clear()
