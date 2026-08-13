"""出货/应收落库销售单号快照，供客户对账。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    Tenant,
    Worker,
)
from app.schemas.api import OrderCreate, OrderItemIn
from app.services import finance_service, shipment_service
from app.services.order_service import create_order
from app.services.report_service import submit_report


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

    tenant = Tenant(name="对账测试厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="红", code="R"))
    session.add(Size(tenant_id=tenant.id, size_value="37", sort_order=0))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("0.8"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="SO-SNAP",
        quote_price=Decimal("68.00"),
        is_active=True,
    )
    session.add(product)
    session.flush()
    session.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=proc.id,
            process_name=proc.name,
            unit_price=proc.default_price,
            sort_order=1,
        )
    )
    session.add(Worker(tenant_id=tenant.id, name="张三", mobile="13900000002"))
    session.commit()
    yield session
    session.close()


def test_shipment_and_receivable_snapshot_sales_order_no(db):
    tenant = db.query(Tenant).first()
    product = db.query(OwnProduct).first()
    worker = db.query(Worker).first()
    color = db.query(Color).first()
    size = db.query(Size).first()

    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="CUST-SO-8899",
        customer_name="对账客户",
        ordered_at=date.today(),
        status=SalesOrderStatus.confirmed,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        color_id=color.id,
        total_qty=5,
        status=SalesOrderLineStatus.in_production,
        unit_price=Decimal("12"),
        sort_order=0,
    )
    db.add(line)
    db.flush()
    db.add(
        SalesOrderLineItem(
            tenant_id=tenant.id,
            sales_order_line_id=line.id,
            color_id=color.id,
            size_id=size.id,
            qty=5,
        )
    )
    db.flush()

    order = create_order(
        db,
        tenant.id,
        OrderCreate(
            order_no="PROD-SNAP-1",
            customer_name="对账客户",
            own_product_id=product.id,
            items=[OrderItemIn(color_id=color.id, size_id=size.id, qty=5)],
            unit_price=Decimal("12"),
        ),
        created_by=None,
        sales_order_id=so.id,
        sales_order_line_id=line.id,
    )
    line.production_order_id = order.id
    db.commit()

    submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=order.order_no,
        process_name="成型",
        qualified_qty=5,
        color_name="红",
        size_value="37",
    )

    out = shipment_service.create_shipment(
        db,
        tenant.id,
        order_id=order.id,
        lines=[{"order_item_id": order.items[0].id, "qty": 5}],
        confirm=True,
    )
    assert out["sales_order_id"] == so.id
    assert out["sales_order_no"] == "CUST-SO-8899"
    assert out["order_no"] == "PROD-SNAP-1"

    ar_rows = finance_service.list_receivables(db, tenant.id)
    assert len(ar_rows) == 1
    assert ar_rows[0]["sales_order_id"] == so.id
    assert ar_rows[0]["sales_order_no"] == "CUST-SO-8899"
    assert ar_rows[0]["order_no"] == "PROD-SNAP-1"

    filtered = finance_service.list_receivables(db, tenant.id, keyword="CUST-SO")
    assert len(filtered) == 1
