"""成品仓「已对账」只列出已挂对账单的出货单。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Receivable, ReceivableStatus, Shipment, ShipmentStatus, Tenant
from app.services.shipment_service import list_shipments


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _shipment(session, tenant_id: int, no: str) -> Shipment:
    row = Shipment(
        tenant_id=tenant_id,
        shipment_no=no,
        customer_name="客户",
        status=ShipmentStatus.shipped,
        total_qty=2,
        unit_price=Decimal("10"),
        amount=Decimal("20"),
    )
    session.add(row)
    session.flush()
    return row


def test_list_shipments_statemented_filter():
    db = _db()
    tenant = Tenant(name="出货厂")
    db.add(tenant)
    db.commit()
    open_row = _shipment(db, tenant.id, "SH-OPEN")
    done_row = _shipment(db, tenant.id, "SH-DONE")
    db.add(
        Receivable(
            tenant_id=tenant.id,
            customer_name="客户",
            shipment_id=done_row.id,
            receivable_date=date(2026, 10, 20),
            amount=Decimal("20"),
            statement_id=1,
            status=ReceivableStatus.open,
        )
    )
    db.commit()

    statemented = list_shipments(db, tenant.id, statemented=True)
    assert [row["shipment_no"] for row in statemented] == ["SH-DONE"]

    pending = list_shipments(db, tenant.id, statemented=False)
    assert [row["shipment_no"] for row in pending] == ["SH-OPEN"]
    assert open_row.id != done_row.id
