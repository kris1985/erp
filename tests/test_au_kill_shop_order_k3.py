"""干掉生产单 K3：开裁/报工双写 header_id；报工可认 header_id。"""

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
    OrderProcess,
    OrderProcessAssignment,
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
    TraceUnit,
    WorkLog,
    Worker,
)
from app.services.execution_service import create_execution, cut_cards_for_header
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
    tenant = Tenant(name="K3厂")
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
        sort_order=1,
    )
    late = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.personal,
        default_price=Decimal("1"),
        sort_order=2,
    )
    session.add_all([early, late])
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="K3-A", is_active=True, trace_enabled=True
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
    session.add(Worker(tenant_id=tenant.id, name="报工员", mobile="13900002222"))
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


def test_cut_and_report_stamp_header_id(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    worker = db.scalar(select(Worker).limit(1))
    item = _so_item(
        db,
        order_no="SO-K3",
        qty=20,
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
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    assert header.shop_order_id is None
    assert exe.shop_order_id is None

    cut = cut_cards_for_header(
        db,
        tenant_id=tenant.id,
        header_id=header.id,
        dry_run=False,
        bundle_size=20,
        only_missing=True,
        mode="bundles",
    )
    assert cut["created"]
    units = list(
        db.scalars(select(TraceUnit).where(TraceUnit.header_id == header.id)).all()
    )
    assert units
    assert all(u.header_id == header.id for u in units)
    assert all(u.order_id is None for u in units)

    procs = list(
        db.scalars(select(OrderProcess).where(OrderProcess.header_id == header.id)).all()
    )
    for p in procs:
        db.add(
            OrderProcessAssignment(
                tenant_id=tenant.id,
                order_id=None,
                header_id=header.id,
                order_process_id=p.id,
                worker_id=worker.id,
            )
        )
    db.commit()

    # 用 header_id 报工（不传 order_no）
    result = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        header_id=header.id,
        process_name="针车",
        qualified_qty=5,
        color_name=color.name,
        size_value=size.size_value,
        create_trace_bundle=False,
    )
    assert result["header_id"] == header.id
    logs = list(db.scalars(select(WorkLog).where(WorkLog.header_id == header.id)).all())
    assert len(logs) == 1
    assert logs[0].order_id is None

    # 用执行单号字符串也能解析
    result2 = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        order_no=header.header_no,
        process_name="成型",
        qualified_qty=3,
        color_name=color.name,
        size_value=size.size_value,
        create_trace_bundle=False,
    )
    assert result2["header_id"] == header.id
    assert db.scalar(select(WorkLog).where(WorkLog.process_id == procs[-1].process_id)) is not None
