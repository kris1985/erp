"""干掉生产单 K4：确认生产停写桥接壳；工序挂 header_id。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    ExecutionHeader,
    Order,
    OrderProcess,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessType,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    Tenant,
)
from app.services.execution_service import create_execution_from_sales_line
from app.services.sales_order_service import confirm_sales_order_line


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
    tenant = Tenant(name="K4厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="K4-A", is_active=True, trace_enabled=True
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


def test_confirm_no_bridge_order_stamps_process_header(db):
    tenant_id = db.scalar(select(Tenant.id))
    product_id = db.scalar(select(OwnProduct.id))
    color_id = db.scalar(select(Color.id))
    size_id = db.scalar(select(Size.id))

    so = SalesOrder(
        tenant_id=tenant_id,
        order_no="SO-K4",
        customer_name="客户K4",
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
        total_qty=12,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    db.add(
        SalesOrderLineItem(
            tenant_id=tenant_id,
            sales_order_line_id=line.id,
            color_id=color_id,
            size_id=size_id,
            qty=12,
        )
    )
    db.commit()

    confirm_sales_order_line(db, tenant_id, so.id, line.id, created_by=None)
    db.refresh(so)
    db.refresh(line)
    create_execution_from_sales_line(
        db, tenant_id=tenant_id, sales_order=so, line=line, created_by=None, commit=True
    )
    db.refresh(line)
    assert line.production_order_id is None
    assert line.execution_header_id

    header = db.get(ExecutionHeader, line.execution_header_id)
    assert header is not None
    assert header.shop_order_id is None
    assert db.scalar(select(Order).where(Order.id == line.production_order_id)) is None

    procs = list(
        db.scalars(select(OrderProcess).where(OrderProcess.header_id == header.id)).all()
    )
    assert procs
    assert all(p.header_id == line.execution_header_id for p in procs)
    assert all(p.order_id is None for p in procs)
