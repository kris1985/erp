"""不跟生产单的领料：一张单可含多种物料，确认时扣公用库存。"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_worker_token
from app.db import Base, get_db
from app.main import app
from app.models import (
    Employee,
    EmployeeRoleAssignment,
    Partner,
    PricingUnit,
    SharedMaterialLedger,
    SharedMaterialStock,
    SupplierProduct,
    Tenant,
)
from app.services import misc_material_pickup_service
from app.services.material_service import _shared_qty
from app.services.misc_material_pickup_service import PickupError


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _world():
    session = _session()
    tenant = Tenant(name="领料厂")
    session.add(tenant)
    session.flush()
    partner = Partner(tenant_id=tenant.id, name="供应商甲", is_supplier=True, is_active=True)
    unit = PricingUnit(tenant_id=tenant.id, name="米", is_active=True)
    session.add_all([partner, unit])
    session.flush()
    sole = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-1",
        name="大底",
        partner_id=partner.id,
        pricing_unit_id=unit.id,
        is_active=True,
    )
    nail = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-2",
        name="钉子",
        partner_id=partner.id,
        is_active=True,
    )
    worker = Employee(tenant_id=tenant.id, name="车间工", mobile="13800003001", is_active=True)
    other = Employee(tenant_id=tenant.id, name="另一人", mobile="13800003002", is_active=True)
    session.add_all([sole, nail, worker, other])
    session.flush()
    session.add(
        SharedMaterialStock(
            tenant_id=tenant.id,
            supplier_product_id=sole.id,
            qty=Decimal("5"),
            avg_unit_cost=Decimal("1"),
        )
    )
    session.add(
        SharedMaterialStock(
            tenant_id=tenant.id,
            supplier_product_id=nail.id,
            qty=Decimal("20"),
            avg_unit_cost=Decimal("0.1"),
        )
    )
    session.commit()
    return session, tenant, sole, nail, worker, other


def test_one_doc_can_hold_several_materials_and_receive_deducts_stock():
    session, tenant, sole, nail, worker, _other = _world()
    created = misc_material_pickup_service.create_pickup(
        session,
        tenant.id,
        worker.id,
        lines=[
            {"supplier_product_id": sole.id, "qty": Decimal("2")},
            {"supplier_product_id": nail.id, "qty": Decimal("4")},
        ],
        notes="车间耗材",
    )
    assert created["line_count"] == 2
    assert created["lines"][0]["material_name"] == "大底"
    assert created["lines"][0]["unit_name"] == "米"
    assert created["lines"][1]["supplier_product_id"] == nail.id

    received = misc_material_pickup_service.receive_pickup(session, tenant.id, created["id"], worker.id)
    assert received["status"] == "received"
    assert _shared_qty(session, tenant.id, sole.id, None) == Decimal("3")
    assert _shared_qty(session, tenant.id, nail.id, None) == Decimal("16")
    ledgers = session.scalars(select(SharedMaterialLedger)).all()
    assert len(ledgers) == 2
    assert {row.ledger_type.value for row in ledgers} == {"misc_issue"}


def test_insufficient_stock_rolls_back_the_whole_doc():
    session, tenant, sole, nail, worker, _other = _world()
    nail_stock = session.scalar(
        select(SharedMaterialStock).where(SharedMaterialStock.supplier_product_id == nail.id)
    )
    nail_stock.qty = Decimal("1")
    session.commit()
    created = misc_material_pickup_service.create_pickup(
        session,
        tenant.id,
        worker.id,
        lines=[
            {"supplier_product_id": sole.id, "qty": Decimal("2")},
            {"supplier_product_id": nail.id, "qty": Decimal("4")},
        ],
    )
    with pytest.raises(PickupError) as exc:
        misc_material_pickup_service.receive_pickup(session, tenant.id, created["id"], worker.id)
    assert "钉子" in exc.value.message
    listed = misc_material_pickup_service.list_pickups(session, tenant.id, worker.id)
    assert listed["items"][0]["status"] == "pending"
    assert listed["pending_count"] == 1
    assert _shared_qty(session, tenant.id, sole.id, None) == Decimal("5")
    assert session.scalar(select(func.count()).select_from(SharedMaterialLedger)) == 0


def test_duplicate_material_rejected_and_only_owner_can_receive():
    session, tenant, sole, _nail, worker, other = _world()
    with pytest.raises(PickupError) as exc:
        misc_material_pickup_service.create_pickup(
            session,
            tenant.id,
            worker.id,
            lines=[
                {"supplier_product_id": sole.id, "qty": Decimal("1")},
                {"supplier_product_id": sole.id, "qty": Decimal("1")},
            ],
        )
    assert exc.value.code == "duplicate_material"
    with pytest.raises(PickupError) as missing:
        misc_material_pickup_service.create_pickup(
            session,
            tenant.id,
            worker.id,
            lines=[{"material_name": "临时胶水", "qty": Decimal("1")}],
        )
    assert missing.value.code == "product_required"
    created = misc_material_pickup_service.create_pickup(
        session,
        tenant.id,
        worker.id,
        lines=[{"supplier_product_id": sole.id, "qty": Decimal("1")}],
    )
    with pytest.raises(PickupError) as denied:
        misc_material_pickup_service.receive_pickup(session, tenant.id, created["id"], other.id)
    assert denied.value.code == "forbidden"
    received = misc_material_pickup_service.receive_pickup(session, tenant.id, created["id"], worker.id)
    assert received["status"] == "received"


def test_api_creates_multi_line_pickup():
    session, tenant, sole, nail, worker, _other = _world()
    finance = Employee(tenant_id=tenant.id, name="财务", mobile="13800003003", is_active=True)
    session.add(finance)
    session.flush()
    session.add(EmployeeRoleAssignment(tenant_id=tenant.id, employee_id=finance.id, role_code="finance"))
    session.commit()

    def _get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    client = TestClient(app)
    try:
        denied = client.post(
            "/api/v1/misc-material-pickups",
            json={"lines": [{"material_name": "胶水", "qty": 1}]},
            headers={"Authorization": f"Bearer {create_worker_token(finance)}"},
        )
        assert denied.status_code == 403
        created = client.post(
            "/api/v1/misc-material-pickups",
            json={
                "notes": "一次两种",
                "lines": [
                    {"supplier_product_id": sole.id, "qty": 1},
                    {"supplier_product_id": nail.id, "qty": 3},
                ],
            },
            headers={"Authorization": f"Bearer {create_worker_token(worker)}"},
        )
        assert created.status_code == 200
        data = created.json()["data"]
        assert data["line_count"] == 2
        listed = client.get(
            "/api/v1/misc-material-pickups",
            headers={"Authorization": f"Bearer {create_worker_token(worker)}"},
        )
        assert listed.json()["data"]["pending_count"] == 1
    finally:
        app.dependency_overrides.clear()
