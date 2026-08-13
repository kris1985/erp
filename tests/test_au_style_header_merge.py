"""同款同色紧急合单：多码一头、交期窗、补码新单。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    ExecutionAllocation,
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
from app.services.execution_service import (
    ExecutionError,
    create_style_header,
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
    tenant = Tenant(name="多码合单厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Color(tenant_id=tenant.id, name="白", code="WH"))
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
        tenant_id=tenant.id, product_code="STYLE-A", is_active=True, trace_enabled=True
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


def _so_item(
    db,
    *,
    order_no: str,
    qty: int,
    product_id: int,
    color_id: int,
    size_id: int,
    tenant_id: int,
    delivery_date: date | None = None,
):
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
        delivery_date=delivery_date,
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


def test_create_style_header_two_sizes_one_header(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).where(Color.name == "黑").limit(1))
    size40 = db.scalar(select(Size).where(Size.size_value == "40").limit(1))
    size41 = db.scalar(select(Size).where(Size.size_value == "41").limit(1))
    _, _, a = _so_item(
        db,
        order_no="SO-40",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size40.id,
        tenant_id=tenant.id,
        delivery_date=date.today(),
    )
    _, _, b = _so_item(
        db,
        order_no="SO-41",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size41.id,
        tenant_id=tenant.id,
        delivery_date=date.today() + timedelta(days=2),
    )

    header = create_style_header(
        db,
        tenant_id=tenant.id,
        items=[
            {"sales_order_line_item_id": a.id, "qty": 10},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
        max_delivery_gap_days=7,
    )
    assert isinstance(header, ExecutionHeader)
    assert header.total_qty == 30
    lines = list(
        db.scalars(
            select(SpecExecutionOrder)
            .where(SpecExecutionOrder.header_id == header.id)
            .order_by(SpecExecutionOrder.id)
        ).all()
    )
    assert len(lines) == 2
    assert {x.total_qty for x in lines} == {10, 20}
    db.refresh(a)
    db.refresh(b)
    assert a.allocated_qty == 10
    assert b.allocated_qty == 20
    assert list_producible(db, tenant_id=tenant.id) == []


def test_same_size_two_customers_ratios(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).where(Color.name == "黑").limit(1))
    size = db.scalar(select(Size).where(Size.size_value == "40").limit(1))
    _, _, a = _so_item(
        db,
        order_no="SO-A",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    _, _, b = _so_item(
        db,
        order_no="SO-B",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    header = create_style_header(
        db,
        tenant_id=tenant.id,
        items=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    exe = db.scalar(select(SpecExecutionOrder).where(SpecExecutionOrder.header_id == header.id))
    allocs = list(
        db.scalars(select(ExecutionAllocation).where(ExecutionAllocation.execution_id == exe.id)).all()
    )
    assert len(allocs) == 2
    by_item = {x.sales_order_line_item_id: x for x in allocs}
    assert abs(float(by_item[a.id].ratio) - 0.6) < 1e-6
    assert abs(float(by_item[b.id].ratio) - 0.4) < 1e-6


def test_reject_different_color_and_delivery_window(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    black = db.scalar(select(Color).where(Color.name == "黑").limit(1))
    white = db.scalar(select(Color).where(Color.name == "白").limit(1))
    size = db.scalar(select(Size).where(Size.size_value == "40").limit(1))
    _, _, a = _so_item(
        db,
        order_no="SO-BK",
        qty=10,
        product_id=product.id,
        color_id=black.id,
        size_id=size.id,
        tenant_id=tenant.id,
        delivery_date=date.today(),
    )
    _, _, b = _so_item(
        db,
        order_no="SO-WH",
        qty=10,
        product_id=product.id,
        color_id=white.id,
        size_id=size.id,
        tenant_id=tenant.id,
        delivery_date=date.today(),
    )
    with pytest.raises(ExecutionError) as e1:
        create_style_header(
            db,
            tenant_id=tenant.id,
            items=[
                {"sales_order_line_item_id": a.id, "qty": 10},
                {"sales_order_line_item_id": b.id, "qty": 10},
            ],
        )
    assert e1.value.code == "style_mismatch"

    size41 = db.scalar(select(Size).where(Size.size_value == "41").limit(1))
    _, _, c = _so_item(
        db,
        order_no="SO-FAR",
        qty=8,
        product_id=product.id,
        color_id=black.id,
        size_id=size41.id,
        tenant_id=tenant.id,
        delivery_date=date.today() + timedelta(days=10),
    )
    with pytest.raises(ExecutionError) as e2:
        create_style_header(
            db,
            tenant_id=tenant.id,
            items=[
                {"sales_order_line_item_id": a.id, "qty": 10},
                {"sales_order_line_item_id": c.id, "qty": 8},
            ],
            max_delivery_gap_days=7,
        )
    assert e2.value.code == "delivery_window"


def test_supplement_notes_forced(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).where(Color.name == "黑").limit(1))
    size = db.scalar(select(Size).where(Size.size_value == "40").limit(1))
    _, _, a = _so_item(
        db,
        order_no="SO-SUP",
        qty=12,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    header = create_style_header(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": a.id, "qty": 12}],
        notes="客户加量",
        supplement=True,
    )
    assert header.notes and "补码" in header.notes
    exe = db.scalar(select(SpecExecutionOrder).where(SpecExecutionOrder.header_id == header.id))
    assert exe is not None
    assert exe.notes and "补码" in exe.notes
