"""确认接单不建执行单；排产/显式建单才有 XE。"""

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
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    SpecExecutionOrder,
    Tenant,
)
from app.services.execution_service import create_execution_from_sales_line, list_producible
from app.services.sales_order_service import (
    confirm_sales_order,
    confirm_sales_order_line,
    line_display_status,
    order_display_status,
)


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
    tenant = Tenant(name="接单待排厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=1))
    session.add(Size(tenant_id=tenant.id, size_value="41", sort_order=2))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CUT",
        default_price=Decimal("1"),
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="OP-ACC", is_active=True, trace_enabled=True
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


def _seed_draft_so(db, *, order_no="SO-ACC-1"):
    tenant_id = db.scalar(select(Tenant.id))
    color_id = db.scalar(select(Color.id))
    sizes = list(db.scalars(select(Size).order_by(Size.sort_order)).all())
    product_id = db.scalar(select(OwnProduct.id))
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客户甲",
        ordered_at=date.today(),
        status=SalesOrderStatus.draft,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        own_product_id=product_id,
        color_id=color_id,
        total_qty=30,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    for size, qty in ((sizes[0], 10), (sizes[1], 20)):
        db.add(
            SalesOrderLineItem(
                tenant_id=tenant_id,
                sales_order_line_id=line.id,
                color_id=color_id,
                size_id=size.id,
                qty=qty,
            )
        )
    db.commit()
    return so, line


def test_confirm_accept_does_not_create_execution(db):
    tenant_id = db.scalar(select(Tenant.id))
    so, line = _seed_draft_so(db)
    confirm_sales_order_line(db, tenant_id, so.id, line.id, created_by=None)
    db.refresh(so)
    db.refresh(line)
    assert so.status == SalesOrderStatus.confirmed
    assert line.execution_header_id is None
    assert line.production_order_id is None
    items = list(
        db.scalars(
            select(SalesOrderLineItem).where(SalesOrderLineItem.sales_order_line_id == line.id)
        ).all()
    )
    assert all(int(it.allocated_qty or 0) == 0 for it in items)
    assert order_display_status(so, {}) == "pending_schedule"
    assert (
        line_display_status(
            order_status="confirmed",
            line_status="pending",
            production_order_id=None,
            production_order_status=None,
        )
        == "pending_schedule"
    )


def test_after_accept_line_enters_producible_pool(db):
    tenant_id = db.scalar(select(Tenant.id))
    so, line = _seed_draft_so(db, order_no="SO-ACC-POOL")
    confirm_sales_order(db, tenant_id, so.id, created_by=None)
    pool = list_producible(db, tenant_id=tenant_id)
    assert pool
    assert any(
        any(s["sales_order_id"] == so.id for s in b["sources"]) for b in pool
    )


def test_create_execution_after_accept(db):
    tenant_id = db.scalar(select(Tenant.id))
    so, line = _seed_draft_so(db, order_no="SO-ACC-XE")
    confirm_sales_order(db, tenant_id, so.id, created_by=None)
    db.refresh(so)
    db.refresh(line)
    header = create_execution_from_sales_line(
        db,
        tenant_id=tenant_id,
        sales_order=so,
        line=line,
        created_by=None,
        commit=True,
    )
    db.refresh(line)
    assert header.header_no.startswith("XE-")
    assert line.execution_header_id == header.id
    assert db.scalar(select(SpecExecutionOrder).where(SpecExecutionOrder.header_id == header.id))
    assert (
        line_display_status(
            order_status="confirmed",
            line_status="pending",
            production_order_id=None,
            production_order_status=None,
            execution_header_id=header.id,
            allocated_qty=30,
        )
        == "pending_production"
    )
