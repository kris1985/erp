"""工序计薪方式切换应同步工艺路线价格。"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Employee, OwnProduct, OwnProductLabor, ProcessDefinition, ProcessPriceHistory, Tenant
from app.services import rbac_service


def test_hourly_process_clears_and_restores_route_price_from_history():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenant = Tenant(name="计薪方式厂")
    db.add(tenant)
    db.flush()
    admin = Employee(
        tenant_id=tenant.id, username="admin", name="管理员", password_hash=hash_password("admin123")
    )
    process = ProcessDefinition(tenant_id=tenant.id, name="针车", code="STITCH")
    product = OwnProduct(tenant_id=tenant.id, product_code="PM-01", product_year=2026, season="SS")
    db.add_all([admin, process, product])
    db.flush()
    rbac_service.set_employee_roles(db, admin, ["admin"])
    db.add(OwnProductLabor(
        tenant_id=tenant.id, own_product_id=product.id, process_id=process.id,
        process_name=process.name, unit_price=Decimal("1.25"),
    ))
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        token = client.post("/api/v1/auth/login", json={"identifier": "admin", "password": "admin123"}).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        hourly = client.patch(f"/api/v1/processes/{process.id}", json={"pay_mode": "hourly"}, headers=headers)
        assert hourly.status_code == 200, hourly.text
        assert hourly.json()["data"]["pay_mode"] == "hourly"
        assert Decimal(db.scalar(select(OwnProductLabor.unit_price))) == Decimal("0")
        assert db.scalar(select(ProcessPriceHistory).where(ProcessPriceHistory.new_price == 0)) is not None

        piecework = client.patch(f"/api/v1/processes/{process.id}", json={"pay_mode": "piecework"}, headers=headers)
        assert piecework.status_code == 200, piecework.text
        assert Decimal(db.scalar(select(OwnProductLabor.unit_price))) == Decimal("1.25")
        restore_hist = db.scalars(
            select(ProcessPriceHistory)
            .where(
                ProcessPriceHistory.process_id == process.id,
                ProcessPriceHistory.new_price == Decimal("1.2500"),
            )
            .order_by(ProcessPriceHistory.id.desc())
        ).first()
        assert restore_hist is not None
        assert Decimal(restore_hist.old_price or 0) == Decimal("0")
        assert restore_hist.source == "process_pay_mode_change"
        assert restore_hist.changed_by == admin.id
    finally:
        app.dependency_overrides.clear()
        db.close()
