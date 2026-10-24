"""已出货后可以补记快递公司和运单号。已对账不能再改。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Receivable, ReceivableStatus, Shipment, ShipmentStatus, Tenant
from app.services.shipment_service import ShipmentError, update_shipment_logistics


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _shipment(session, tenant_id: int, status: ShipmentStatus) -> Shipment:
    row = Shipment(
        tenant_id=tenant_id,
        shipment_no=f"SH-{status.value}",
        customer_name="客户",
        status=status,
        total_qty=2,
        unit_price=Decimal("10"),
        amount=Decimal("20"),
    )
    session.add(row)
    session.commit()
    return row


def test_shipped_shipment_can_save_courier_and_tracking():
    db = _db()
    tenant = Tenant(name="出货厂")
    db.add(tenant)
    db.commit()
    row = _shipment(db, tenant.id, ShipmentStatus.shipped)

    out = update_shipment_logistics(
        db,
        tenant.id,
        row.id,
        logistics_company=" 顺丰 ",
        tracking_no=" SF001 ",
    )
    assert out["logistics_company"] == "顺丰"
    assert out["tracking_no"] == "SF001"

    cleared = update_shipment_logistics(
        db,
        tenant.id,
        row.id,
        logistics_company="",
        tracking_no=None,
    )
    assert cleared["logistics_company"] is None
    assert cleared["tracking_no"] is None
    saved = db.scalar(select(Shipment).where(Shipment.id == row.id))
    assert saved.logistics_company is None
    assert saved.tracking_no is None


def test_void_shipment_rejects_logistics():
    db = _db()
    tenant = Tenant(name="出货厂")
    db.add(tenant)
    db.commit()
    row = _shipment(db, tenant.id, ShipmentStatus.void)
    try:
        update_shipment_logistics(
            db,
            tenant.id,
            row.id,
            logistics_company="中通",
            tracking_no="ZT1",
        )
    except ShipmentError as exc:
        assert exc.code == "invalid_status"
    else:
        raise AssertionError("作废单不应写入运单")


def test_statemented_shipment_rejects_logistics():
    db = _db()
    tenant = Tenant(name="出货厂")
    db.add(tenant)
    db.commit()
    row = _shipment(db, tenant.id, ShipmentStatus.shipped)
    db.add(
        Receivable(
            tenant_id=tenant.id,
            customer_name="客户",
            shipment_id=row.id,
            receivable_date=date(2026, 10, 20),
            amount=Decimal("20"),
            statement_id=1,
            status=ReceivableStatus.open,
        )
    )
    db.commit()
    try:
        update_shipment_logistics(
            db,
            tenant.id,
            row.id,
            logistics_company="顺丰",
            tracking_no="SF9",
        )
    except ShipmentError as exc:
        assert exc.code == "already_statemented"
    else:
        raise AssertionError("已对账单不应修改运单")
    saved = db.scalar(select(Shipment).where(Shipment.id == row.id))
    assert saved.logistics_company is None
    assert saved.tracking_no is None
