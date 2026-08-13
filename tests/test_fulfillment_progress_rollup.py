"""销售色码四轨汇总：需求 / 已排 / 已产 / 已出 + 约在制。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    ExecutionAllocation,
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
    SpecExecutionStatus,
    Tenant,
)
from app.services.sales_order_service import _serialize_line, serialize_sales_order


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
    tenant = Tenant(name="履约进度厂")
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
        tenant_id=tenant.id, product_code="OP-PROG", is_active=True, trace_enabled=True
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


def _seed_order(db):
    tenant = db.scalars(select(Tenant)).one()
    color = db.scalars(select(Color).where(Color.tenant_id == tenant.id)).one()
    sizes = list(
        db.scalars(
            select(Size).where(Size.tenant_id == tenant.id).order_by(Size.sort_order)
        ).all()
    )
    product = db.scalars(select(OwnProduct).where(OwnProduct.tenant_id == tenant.id)).one()
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-PROG-1",
        customer_name="客户A",
        status=SalesOrderStatus.confirmed,
        ordered_at=date.today(),
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        color_id=color.id,
        total_qty=100,
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    items = []
    for size, qty, allocated, produced, shipped in (
        (sizes[0], 60, 60, 40, 20),
        (sizes[1], 40, 40, 10, 0),
    ):
        it = SalesOrderLineItem(
            tenant_id=tenant.id,
            sales_order_line_id=line.id,
            size_id=size.id,
            qty=qty,
            allocated_qty=allocated,
            produced_qty=produced,
            shipped_qty=shipped,
        )
        db.add(it)
        items.append(it)
    db.flush()
    return tenant.id, so, line, items


def test_line_progress_four_track_rollup(db):
    tenant_id, so, line, items = _seed_order(db)
    db.commit()
    db.refresh(line)

    ser = _serialize_line(db, tenant_id, line)
    assert ser["total_qty"] == 100
    assert ser["allocated_qty"] == 100
    assert ser["produced_qty"] == 50
    assert ser["shipped_qty"] == 20
    assert ser["wip_qty"] == 0
    by_size = {it["size_id"]: it for it in ser["items"]}
    assert by_size[items[0].size_id]["produced_qty"] == 40
    assert by_size[items[0].size_id]["shipped_qty"] == 20
    assert by_size[items[1].size_id]["allocated_qty"] == 40


def test_wip_qty_from_allocation_est(db):
    tenant_id, so, line, items = _seed_order(db)
    seo = SpecExecutionOrder(
        tenant_id=tenant_id,
        execution_no="XE-PROG-1",
        own_product_id=line.own_product_id,
        color_id=line.color_id,
        size_id=items[0].size_id,
        total_qty=100,
        status=SpecExecutionStatus.in_progress,
    )
    db.add(seo)
    db.flush()
    # 在制预估：est 合计 80，已产 50 → wip 30
    for it, est in ((items[0], 55), (items[1], 25)):
        db.add(
            ExecutionAllocation(
                tenant_id=tenant_id,
                execution_id=seo.id,
                sales_order_id=so.id,
                sales_order_line_id=line.id,
                sales_order_line_item_id=it.id,
                qty=it.qty,
                ratio=Decimal("0.5"),
                produced_qty_est=est,
            )
        )
    db.commit()
    db.refresh(line)

    ser = _serialize_line(db, tenant_id, line)
    assert ser["produced_qty"] == 50
    assert ser["wip_qty"] == 30

    order_ser = serialize_sales_order(db, tenant_id, so)
    assert order_ser["lines"][0]["wip_qty"] == 30
    assert order_ser["lines"][0]["shipped_qty"] == 20
