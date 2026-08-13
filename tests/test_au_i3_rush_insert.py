"""AU-I3 M2：急单冲击仅延后未开工执行单交期。"""

from datetime import date, timedelta
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
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    Size,
    SpecExecutionOrder,
    SpecExecutionStatus,
    Tenant,
    TraceUnit,
    TraceUnitStatus,
    TraceUnitType,
)
from app.services.execution_schedule_service import (
    ExecutionScheduleError,
    confirm_rush_insert,
    execution_is_started,
    simulate_rush_insert,
)
from app.services.execution_service import create_execution


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
    tenant = Tenant(name="急单厂")
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
        tenant_id=tenant.id, product_code="RUSH-A", is_active=True, trace_enabled=True
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


def _item(db, *, order_no, qty, product_id, color_id, size_id, tenant_id):
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客户",
        status=SalesOrderStatus.confirmed,
        ordered_at=date.today(),
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


def _exe(db, *, order_no, qty, delivery, tenant_id, product_id, color_id, size_id):
    item = _item(
        db,
        order_no=order_no,
        qty=qty,
        product_id=product_id,
        color_id=color_id,
        size_id=size_id,
        tenant_id=tenant_id,
    )
    return create_execution(
        db,
        tenant_id=tenant_id,
        items=[{"sales_order_line_item_id": item.id, "qty": qty}],
        delivery_date=delivery,
    )


def test_rush_pushes_unstarted_freezes_started(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    d0 = date.today() + timedelta(days=7)
    d1 = date.today() + timedelta(days=10)
    d2 = date.today() + timedelta(days=14)

    rush = _exe(
        db,
        order_no="SO-R0",
        qty=10,
        delivery=d0,
        tenant_id=tenant.id,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
    )
    peer_open = _exe(
        db,
        order_no="SO-R1",
        qty=10,
        delivery=d1,
        tenant_id=tenant.id,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
    )
    peer_started = _exe(
        db,
        order_no="SO-R2",
        qty=10,
        delivery=d2,
        tenant_id=tenant.id,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
    )
    # 已开工：挂筐
    db.add(
        TraceUnit(
            tenant_id=tenant.id,
            order_id=peer_started.shop_order_id,
            execution_id=peer_started.id,
            unit_type=TraceUnitType.basket,
            code="B-RUSH-1",
            own_product_id=product.id,
            color_id=color.id,
            size_id=size.id,
            qty=10,
            status=TraceUnitStatus.open,
        )
    )
    db.commit()
    assert execution_is_started(db, peer_started) is True
    assert execution_is_started(db, peer_open) is False

    sim = simulate_rush_insert(db, tenant_id=tenant.id, execution_id=rush.id, push_days=3)
    assert sim["insert"]["will_mark_rush"] is True
    assert {x["execution_id"] for x in sim["impacts"]} == {peer_open.id}
    assert {x["execution_id"] for x in sim["frozen"]} == {peer_started.id}
    assert sim["impacts"][0]["new_delivery_date"] == (d1 + timedelta(days=3)).isoformat()

    old_started = peer_started.delivery_date
    result = confirm_rush_insert(
        db, tenant_id=tenant.id, execution_id=rush.id, push_days=3, reason="客户插单"
    )
    assert result["confirmed"] is True
    db.refresh(rush)
    db.refresh(peer_open)
    db.refresh(peer_started)
    assert rush.is_rush is True
    assert peer_open.delivery_date == d1 + timedelta(days=3)
    assert peer_started.delivery_date == old_started


def test_rush_does_not_move_earlier_delivery(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    later = date.today() + timedelta(days=20)
    earlier = date.today() + timedelta(days=5)
    rush = _exe(
        db,
        order_no="SO-E0",
        qty=5,
        delivery=later,
        tenant_id=tenant.id,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
    )
    peer = _exe(
        db,
        order_no="SO-E1",
        qty=5,
        delivery=earlier,
        tenant_id=tenant.id,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
    )
    sim = simulate_rush_insert(db, tenant_id=tenant.id, execution_id=rush.id, push_days=2)
    assert sim["impacts"] == []
    assert any(x["execution_id"] == peer.id for x in sim["unaffected"])


def test_in_progress_peer_is_frozen_not_impacted(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    d0 = date.today() + timedelta(days=7)
    d1 = date.today() + timedelta(days=10)
    rush = _exe(
        db,
        order_no="SO-C0",
        qty=5,
        delivery=d0,
        tenant_id=tenant.id,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
    )
    peer = _exe(
        db,
        order_no="SO-C1",
        qty=5,
        delivery=d1,
        tenant_id=tenant.id,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
    )
    peer.status = SpecExecutionStatus.in_progress
    db.commit()
    sim = simulate_rush_insert(db, tenant_id=tenant.id, execution_id=rush.id, push_days=2)
    assert peer.id in {x["execution_id"] for x in sim["frozen"]}
    assert peer.id not in {x["execution_id"] for x in sim["impacts"]}
    confirm_rush_insert(db, tenant_id=tenant.id, execution_id=rush.id, push_days=2)
    db.refresh(peer)
    assert peer.delivery_date == d1
