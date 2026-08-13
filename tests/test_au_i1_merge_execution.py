"""AU-I1 M1：有分配合单。"""

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
from app.services.execution_service import (
    ExecutionError,
    cancel_execution,
    create_execution,
    list_producible,
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
    tenant = Tenant(name="合单厂")
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
        tenant_id=tenant.id, product_code="MERGE-A", is_active=True, trace_enabled=True
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


def _so_with_item(db, *, order_no: str, qty: int, product_id: int, color_id: int, size_id: int, tenant_id: int):
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name=f"客户{order_no}",
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
        allocated_qty=0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return so, line, item


def test_merge_two_sources_ratios(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    _, _, a = _so_with_item(
        db,
        order_no="SO-A",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    _, _, b = _so_with_item(
        db,
        order_no="SO-B",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )

    prod = list_producible(db, tenant_id=tenant.id)
    assert len(prod) == 1
    assert prod[0]["remaining_qty"] == 50
    assert len(prod[0]["sources"]) == 2

    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    assert exe.total_qty == 50
    assert exe.shop_order_id is not None
    assert exe.status == SpecExecutionStatus.confirmed

    allocs = list(
        db.scalars(select(ExecutionAllocation).where(ExecutionAllocation.execution_id == exe.id)).all()
    )
    assert len(allocs) == 2
    by_item = {x.sales_order_line_item_id: x for x in allocs}
    assert by_item[a.id].qty == 30
    assert by_item[b.id].qty == 20
    assert abs(float(by_item[a.id].ratio) - 0.6) < 1e-6
    assert abs(float(by_item[b.id].ratio) - 0.4) < 1e-6
    assert abs(sum(float(x.ratio) for x in allocs) - 1.0) < 1e-8

    db.refresh(a)
    db.refresh(b)
    assert a.allocated_qty == 30
    assert b.allocated_qty == 20
    assert list_producible(db, tenant_id=tenant.id) == []


def test_reject_over_remaining_and_spec_mismatch(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    size2 = Size(tenant_id=tenant.id, size_value="41", sort_order=1)
    db.add(size2)
    db.flush()
    _, _, a = _so_with_item(
        db,
        order_no="SO-C",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    _, _, b = _so_with_item(
        db,
        order_no="SO-D",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size2.id,
        tenant_id=tenant.id,
    )

    with pytest.raises(ExecutionError) as e1:
        create_execution(
            db,
            tenant_id=tenant.id,
            items=[{"sales_order_line_item_id": a.id, "qty": 11}],
        )
    assert e1.value.code == "over_remaining"

    with pytest.raises(ExecutionError) as e2:
        create_execution(
            db,
            tenant_id=tenant.id,
            items=[
                {"sales_order_line_item_id": a.id, "qty": 5},
                {"sales_order_line_item_id": b.id, "qty": 5},
            ],
        )
    assert e2.value.code == "spec_mismatch"


def test_cancel_releases_allocated(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    _, _, a = _so_with_item(
        db,
        order_no="SO-E",
        qty=40,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": a.id, "qty": 40}],
    )
    db.refresh(a)
    assert a.allocated_qty == 40
    cancel_execution(db, tenant_id=tenant.id, execution_id=exe.id)
    db.refresh(a)
    db.refresh(exe)
    assert a.allocated_qty == 0
    assert exe.status == SpecExecutionStatus.cancelled
