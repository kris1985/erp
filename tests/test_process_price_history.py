"""工序价格真历史：产品保存改价落流水，可按工序查询选用。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import (
    Color,
    OwnProduct,
    ProcessDefinition,
    ProcessPriceHistory,
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


def test_process_price_history_on_save_and_list():
    db = _session()
    tenant = Tenant(name="工价流水厂")
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

        created = client.post(
            "/api/v1/own-products",
            json={
                "product_code": "PH-01",
                "product_year": 2026,
                "season": "SS",
                "color_ids": [color.id],
                "labors": [
                    {
                        "process_name": "针车",
                        "unit_price": 1.2,
                        "segment_id": stitch.id,
                        "sort_order": 0,
                    }
                ],
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        product_id = created.json()["data"]["id"]

        rows = db.scalars(
            select(ProcessPriceHistory).where(ProcessPriceHistory.tenant_id == tenant.id)
        ).all()
        assert len(rows) == 1
        assert rows[0].old_price is None
        assert Decimal(rows[0].new_price) == Decimal("1.2000")
        assert rows[0].source == "product_create"
        assert rows[0].changed_by == admin.id

        updated = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={
                "labors": [
                    {
                        "process_name": "针车",
                        "unit_price": 1.5,
                        "segment_id": stitch.id,
                        "sort_order": 0,
                    }
                ]
            },
            headers=headers,
        )
        assert updated.status_code == 200, updated.text

        rows = list(
            db.scalars(
                select(ProcessPriceHistory)
                .where(ProcessPriceHistory.tenant_id == tenant.id)
                .order_by(ProcessPriceHistory.id.asc())
            ).all()
        )
        assert len(rows) == 2
        assert Decimal(rows[1].old_price) == Decimal("1.2000")
        assert Decimal(rows[1].new_price) == Decimal("1.5000")
        assert rows[1].source == "product_save"
        assert rows[1].product_code == "PH-01"

        # 同价再保存不落流水
        before_cnt = len(
            list(db.scalars(select(ProcessPriceHistory).where(ProcessPriceHistory.tenant_id == tenant.id)).all())
        )
        same = client.patch(
            f"/api/v1/own-products/{product_id}",
            json={
                "labors": [
                    {
                        "process_name": "针车",
                        "unit_price": 1.5,
                        "segment_id": stitch.id,
                        "sort_order": 0,
                    }
                ]
            },
            headers=headers,
        )
        assert same.status_code == 200
        after_cnt = len(
            list(db.scalars(select(ProcessPriceHistory).where(ProcessPriceHistory.tenant_id == tenant.id)).all())
        )
        assert after_cnt == before_cnt

        hist = client.get(
            "/api/v1/own-products/process-price-history",
            params={"process_id": process.id},
            headers=headers,
        )
        assert hist.status_code == 200
        items = hist.json()["data"]["items"]
        assert len(items) >= 2
        assert float(items[0]["new_price"]) == 1.5
        assert items[0]["changed_by_name"] == "管理员"
    finally:
        app.dependency_overrides.clear()
