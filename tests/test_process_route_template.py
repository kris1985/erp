"""工艺要求历史选用 + 工艺路线模版。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import (
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessRouteTemplate,
    ProcessSegment,
    ProcessType,
    Tenant,
    Employee,
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


def _bootstrap(db):
    tenant = Tenant(name="路线模版厂")
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
    stitch = ProcessSegment(
        tenant_id=tenant.id,
        name="针车",
        code="stitch",
        sort_order=20,
        is_active=True,
    )
    db.add(stitch)
    db.flush()
    process = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="STITCH",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        segment_id=stitch.id,
        is_active=True,
    )
    db.add(process)
    db.commit()
    return tenant, admin, stitch, process


def test_requirement_note_history_and_route_template():
    db = _session()
    tenant, _admin, stitch, process = _bootstrap(db)

    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="RT-01",
        product_year=2026,
        season="SS",
        is_active=True,
    )
    db.add(product)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=process.id,
            process_name="针车",
            requirement_note="线距均匀，不得跳针",
            unit_price=Decimal("1.2"),
            segment_id=stitch.id,
            sort_order=0,
        )
    )
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=process.id,
            process_name="针车",
            requirement_note="线距均匀，不得跳针",
            unit_price=Decimal("1.3"),
            segment_id=stitch.id,
            sort_order=1,
        )
    )
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=process.id,
            process_name="针车",
            requirement_note="后跟加固双线",
            unit_price=Decimal("1.4"),
            segment_id=stitch.id,
            sort_order=2,
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
            "/api/v1/auth/login",
            json={"identifier": "admin", "password": "admin123"},
        ).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        hist = client.get(
            "/api/v1/own-products/requirement-notes",
            params={"process_id": process.id},
            headers=headers,
        )
        assert hist.status_code == 200
        notes = hist.json()["data"]["items"]
        assert notes[0]["note"] == "线距均匀，不得跳针"
        assert notes[0]["use_count"] == 2
        assert any(n["note"] == "后跟加固双线" for n in notes)

        created = client.post(
            "/api/v1/own-products/route-templates",
            json={
                "name": "常规针车",
                "segment_ref_prices": {str(stitch.id): 8.5},
                "items": [
                    {
                        "process_name": "针车",
                        "requirement_note": "线距均匀，不得跳针",
                        "unit_price": 1.2,
                        "segment_id": stitch.id,
                        "sort_order": 0,
                    }
                ],
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        tpl = created.json()["data"]
        assert tpl["name"] == "常规针车"
        assert len(tpl["items"]) == 1
        assert tpl["items"][0]["process_name"] == "针车"
        assert float(tpl["segment_ref_prices"][str(stitch.id)]) == 8.5

        listed = client.get("/api/v1/own-products/route-templates", headers=headers)
        assert listed.status_code == 200
        assert any(x["id"] == tpl["id"] for x in listed.json()["data"]["items"])

        got = client.get(f"/api/v1/own-products/route-templates/{tpl['id']}", headers=headers)
        assert got.status_code == 200
        assert got.json()["data"]["items"][0]["requirement_note"] == "线距均匀，不得跳针"

        deleted = client.delete(
            f"/api/v1/own-products/route-templates/{tpl['id']}",
            headers=headers,
        )
        assert deleted.status_code == 200
        row = db.scalar(select(ProcessRouteTemplate).where(ProcessRouteTemplate.id == tpl["id"]))
        assert row is not None
        assert row.is_active is False

        listed2 = client.get("/api/v1/own-products/route-templates", headers=headers)
        assert all(x["id"] != tpl["id"] for x in listed2.json()["data"]["items"])
    finally:
        app.dependency_overrides.clear()
