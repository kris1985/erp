"""干掉生产单 K4-D：经典排产 pool/draft/confirm 认无壳执行单头。"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
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
    Employee,
)
from app.services.execution_service import create_execution
from app.services import schedule_service


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
    tenant = Tenant(name="K4D厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    early = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        per_worker_capacity=Decimal("50"),
        standard_workers=1,
        sort_order=1,
    )
    late = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        per_worker_capacity=Decimal("50"),
        standard_workers=1,
        sort_order=2,
    )
    session.add_all([early, late])
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="K4D-A", is_active=True, trace_enabled=True
    )
    session.add(product)
    session.flush()
    session.add_all(
        [
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=early.id,
                process_name=early.name,
                unit_price=Decimal("1"),
                sort_order=0,
            ),
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=late.id,
                process_name=late.name,
                unit_price=Decimal("1"),
                sort_order=1,
            ),
        ]
    )
    session.add(Employee(tenant_id=tenant.id, name="报工员", mobile="13900005555"))
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
    return so, line, item


def _header_only_exe(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    _so, _line, item = _so_item(
        db,
        order_no="SO-K4D",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    order_count_before = db.scalar(select(func.count()).select_from(Order)) or 0
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": 20}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    assert header.shop_order_id is None
    assert exe.shop_order_id is None
    order_count_after = db.scalar(select(func.count()).select_from(Order)) or 0
    assert order_count_after == order_count_before
    return tenant, header, exe


def test_pool_includes_header_only(db):
    tenant, header, _exe = _header_only_exe(db)
    pool = schedule_service.list_schedule_pool(db, tenant.id, hide_scheduled=False)
    row = next((r for r in pool if r.get("header_id") == header.id), None)
    assert row is not None
    assert row["order_id"] is None
    assert row["header_no"] == header.header_no
    assert row["order_no"] == header.header_no
    assert row["process_count"] >= 1


def test_create_and_confirm_draft_header_only(db):
    tenant, header, _exe = _header_only_exe(db)
    order_count_before = db.scalar(select(func.count()).select_from(Order)) or 0

    procs = list(
        db.scalars(
            select(OrderProcess).where(
                OrderProcess.tenant_id == tenant.id,
                OrderProcess.header_id == header.id,
            )
        ).all()
    )
    assert procs
    assert all(p.order_id is None for p in procs)
    assert all(p.start_date is None and p.end_date is None for p in procs)

    draft = schedule_service.create_draft(
        db,
        tenant.id,
        order_ids=[],
        header_ids=[header.id],
        auto_assign=False,
    )
    assert draft["lines"]
    for ln in draft["lines"]:
        assert ln["header_id"] == header.id
        assert ln["order_id"] is None
        assert ln["order_no"] == header.header_no
        assert ln["start_date"] and ln["end_date"]

    confirmed = schedule_service.confirm_draft(
        db,
        tenant.id,
        draft["id"],
        require_first_kit=False,
        apply_assignments=False,
    )
    assert confirmed["status"] == "confirmed"

    procs = list(
        db.scalars(
            select(OrderProcess).where(
                OrderProcess.tenant_id == tenant.id,
                OrderProcess.header_id == header.id,
            )
        ).all()
    )
    assert all(p.start_date is not None and p.end_date is not None for p in procs)

    order_count_after = db.scalar(select(func.count()).select_from(Order)) or 0
    assert order_count_after == order_count_before


def test_keyword_matches_header_no(db):
    tenant, header, _exe = _header_only_exe(db)
    pool = schedule_service.list_schedule_pool(
        db, tenant.id, keyword=header.header_no[:6], hide_scheduled=False
    )
    assert any(r.get("header_id") == header.id for r in pool)
