"""AU-I3 M3：未开工改量；已开工禁改码/改量；补码新单。"""

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
    SpecExecutionStatus,
    Tenant,
    TraceUnit,
    TraceUnitStatus,
    TraceUnitType,
)
from app.services.execution_service import (
    ExecutionError,
    change_execution_qty,
    change_execution_size,
    create_execution,
    create_supplement_execution,
    execution_is_started,
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
    tenant = Tenant(name="变更厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    session.add(Size(tenant_id=tenant.id, size_value="41", sort_order=1))
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
        tenant_id=tenant.id, product_code="CHG-A", is_active=True, trace_enabled=True
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


def _so_item(db, *, order_no: str, qty: int, product_id: int, color_id: int, size_id: int, tenant_id: int):
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
    return item


def test_unstarted_change_qty_updates_alloc_and_pool(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).where(Size.size_value == "40").limit(1))
    a = _so_item(
        db,
        order_no="SO-A",
        qty=50,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-B",
        qty=50,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    assert exe.total_qty == 50
    db.refresh(a)
    db.refresh(b)
    assert a.allocated_qty == 30
    assert b.allocated_qty == 20

    out = change_execution_qty(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        items=[
            {"sales_order_line_item_id": a.id, "qty": 20},
            {"sales_order_line_item_id": b.id, "qty": 10},
        ],
    )
    assert out["new_total_qty"] == 30
    db.refresh(exe)
    db.refresh(a)
    db.refresh(b)
    assert exe.total_qty == 30
    assert a.allocated_qty == 20
    assert b.allocated_qty == 10
    pool = list_producible(db, tenant_id=tenant.id)
    rem = {s["sales_order_line_item_id"]: s["remaining_qty"] for bucket in pool for s in bucket["sources"]}
    assert rem[a.id] == 30
    assert rem[b.id] == 40
    ratios = sorted(
        [
            float(x.ratio)
            for x in db.scalars(
                select(ExecutionAllocation).where(ExecutionAllocation.execution_id == exe.id)
            )
        ]
    )
    assert abs(sum(ratios) - 1.0) < 1e-8


def test_started_blocks_qty_and_size_change(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size40 = db.scalar(select(Size).where(Size.size_value == "40").limit(1))
    size41 = db.scalar(select(Size).where(Size.size_value == "41").limit(1))
    item = _so_item(
        db,
        order_no="SO-S",
        qty=40,
        product_id=product.id,
        color_id=color.id,
        size_id=size40.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    exe.status = SpecExecutionStatus.in_progress
    db.commit()
    assert execution_is_started(db, exe) is True

    with pytest.raises(ExecutionError) as e1:
        change_execution_qty(
            db,
            tenant_id=tenant.id,
            execution_id=exe.id,
            items=[{"sales_order_line_item_id": item.id, "qty": 25}],
        )
    assert e1.value.code == "started_block"

    with pytest.raises(ExecutionError) as e2:
        change_execution_size(
            db,
            tenant_id=tenant.id,
            execution_id=exe.id,
            size_id=size41.id,
        )
    assert e2.value.code == "size_change_blocked"


def test_supplement_creates_second_execution_on_remaining(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).where(Size.size_value == "40").limit(1))
    item = _so_item(
        db,
        order_no="SO-SUP",
        qty=100,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    first = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 60}],
    )
    first.status = SpecExecutionStatus.in_progress
    db.add(
        TraceUnit(
            tenant_id=tenant.id,
            order_id=first.shop_order_id,
            execution_id=first.id,
            code=f"BK-{first.id}",
            unit_type=TraceUnitType.basket,
            own_product_id=product.id,
            color_id=color.id,
            size_id=size.id,
            qty=10,
            status=TraceUnitStatus.open,
        )
    )
    db.commit()

    second = create_supplement_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 40}],
        notes="客户补码",
    )
    assert second.id != first.id
    assert second.total_qty == 40
    assert second.notes and "补码" in second.notes
    db.refresh(item)
    assert item.allocated_qty == 100
    assert list_producible(db, tenant_id=tenant.id) == []


def test_change_qty_dry_run_no_write(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).where(Size.size_value == "40").limit(1))
    item = _so_item(
        db,
        order_no="SO-DRY",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    preview = change_execution_qty(
        db,
        tenant_id=tenant.id,
        execution_id=exe.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 10}],
        dry_run=True,
    )
    assert preview["dry_run"] is True
    assert preview["new_total_qty"] == 10
    db.refresh(exe)
    db.refresh(item)
    assert exe.total_qty == 20
    assert item.allocated_qty == 20
