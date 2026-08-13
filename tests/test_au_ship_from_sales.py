"""出货改挂销售单：手工出货认销售色码。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    Receivable,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Shipment,
    ShipmentStatus,
    Size,
    Tenant,
)
from app.services import shipment_service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="销售出货厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("1"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="SHIP-SO", is_active=True, quote_price=Decimal("88")
    )
    session.add(product)
    session.flush()
    session.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=proc.id,
            process_name=proc.name,
            unit_price=Decimal("1"),
            sort_order=0,
        )
    )
    session.commit()
    yield session
    session.close()


def _so_with_item(db, *, qty: int, produced: int = 0):
    tenant_id = db.scalar(select(Tenant.id))
    color_id = db.scalar(select(Color.id))
    size_id = db.scalar(select(Size.id))
    product_id = db.scalar(select(OwnProduct.id))
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no="SO-SHIP-1",
        customer_name="客户甲",
        ordered_at=date.today(),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        own_product_id=product_id,
        color_id=color_id,
        total_qty=qty,
        unit_price=Decimal("88"),
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    item = SalesOrderLineItem(
        tenant_id=tenant_id,
        sales_order_line_id=line.id,
        color_id=color_id,
        size_id=size_id,
        qty=qty,
        produced_qty=produced,
    )
    db.add(item)
    db.commit()
    return so, line, item


def test_sales_delivery_and_confirm_shipment(db):
    so, _line, item = _so_with_item(db, qty=20, produced=12)
    tenant_id = so.tenant_id

    summary = shipment_service.sales_delivery_summary(db, tenant_id, so.id)
    assert summary["sales_order_no"] == "SO-SHIP-1"
    assert len(summary["items"]) == 1
    assert summary["items"][0]["shippable_qty"] == 12

    out = shipment_service.create_shipment(
        db,
        tenant_id,
        sales_order_id=so.id,
        lines=[{"sales_order_line_item_id": item.id, "qty": 10}],
        confirm=True,
    )
    assert out["sales_order_id"] == so.id
    assert out["sales_order_no"] == "SO-SHIP-1"
    assert out["status"] == "shipped"
    assert out["total_qty"] == 10
    assert out["lines"][0]["sales_order_line_item_id"] == item.id

    db.refresh(item)
    assert int(item.shipped_qty) == 10

    sh = db.scalar(select(Shipment).where(Shipment.id == out["id"]))
    assert sh is not None
    assert sh.sales_order_id == so.id

    ar = db.scalar(select(Receivable).where(Receivable.shipment_id == sh.id))
    assert ar is not None
    assert ar.sales_order_id == so.id
    assert ar.sales_order_no == "SO-SHIP-1"


def test_sales_ship_without_produced_uses_plan(db):
    so, _line, item = _so_with_item(db, qty=8, produced=0)
    summary = shipment_service.sales_delivery_summary(db, so.tenant_id, so.id)
    assert summary["items"][0]["shippable_qty"] == 8

    out = shipment_service.create_shipment(
        db,
        so.tenant_id,
        sales_order_id=so.id,
        lines=[{"sales_order_line_item_id": item.id, "qty": 5}],
        confirm=True,
    )
    assert out["status"] == ShipmentStatus.shipped.value or out["status"] == "shipped"
    db.refresh(item)
    assert int(item.shipped_qty) == 5
