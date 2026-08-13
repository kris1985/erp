"""AU-I1 M3：报工回写执行进度 + ratio 预估勾平。"""

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
    SpecExecutionStatus,
    Tenant,
    Worker,
)
from app.services.execution_service import (
    create_execution,
    split_produced_by_ratio,
)
from app.services.report_service import submit_report, void_work_log


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
    tenant = Tenant(name="进度厂")
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
        tenant_id=tenant.id, product_code="WIP-A", is_active=True, trace_enabled=True
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
    worker = Worker(tenant_id=tenant.id, name="报工员", mobile="13900001111")
    session.add(worker)
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


def test_split_produced_balances():
    qtys = split_produced_by_ratio(10, [Decimal("0.6"), Decimal("0.4")])
    assert qtys == [6, 4]
    qtys2 = split_produced_by_ratio(11, [Decimal("0.6"), Decimal("0.4")])
    assert sum(qtys2) == 11
    assert qtys2[0] == 6  # floor(11*0.6)=6
    assert qtys2[1] == 5


def test_report_updates_execution_progress_and_alloc_est(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    worker = db.scalar(select(Worker).limit(1))
    a = _so_item(
        db,
        order_no="SO-A",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-B",
        qty=20,
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
    from app.models import ExecutionHeader

    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    procs = list(
        db.scalars(select(OrderProcess).where(OrderProcess.header_id == header.id)).all()
    )
    assert len(procs) >= 1
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

    # 先报针车不影响末道进度（仍为 0）
    submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        header_id=header.id,
        process_name="针车",
        qualified_qty=50,
        color_name=color.name,
        size_value=size.size_value,
        create_trace_bundle=False,
    )
    db.refresh(exe)
    assert int(exe.completed_qty or 0) == 0

    # 报末道成型 10 → 6/4
    result = submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        header_id=header.id,
        process_name="成型",
        qualified_qty=10,
        color_name=color.name,
        size_value=size.size_value,
        create_trace_bundle=False,
    )
    db.refresh(exe)
    assert int(exe.completed_qty) == 10
    assert exe.status == SpecExecutionStatus.in_progress
    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == exe.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    assert [a.produced_qty_est for a in allocs] == [6, 4]
    assert sum(a.produced_qty_est for a in allocs) == exe.completed_qty

    # 再报 40 → 满产 30/20
    submit_report(
        db,
        tenant_id=tenant.id,
        worker_id=worker.id,
        header_id=header.id,
        process_name="成型",
        qualified_qty=40,
        color_name=color.name,
        size_value=size.size_value,
        confirm_over_plan=True,
        create_trace_bundle=False,
    )
    db.refresh(exe)
    assert int(exe.completed_qty) == 50
    assert exe.status == SpecExecutionStatus.completed
    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == exe.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    assert [a.produced_qty_est for a in allocs] == [30, 20]

    # 作废一笔末道报工后重算
    void_work_log(db, tenant_id=tenant.id, work_log_id=result["work_log_id"])
    db.refresh(exe)
    # void 只回滚了第一次 10；第二次 40 仍在 → completed=40
    assert int(exe.completed_qty) == 40
    allocs = list(
        db.scalars(
            select(ExecutionAllocation)
            .where(ExecutionAllocation.execution_id == exe.id)
            .order_by(ExecutionAllocation.id)
        ).all()
    )
    assert sum(a.produced_qty_est for a in allocs) == 40
    assert exe.status == SpecExecutionStatus.in_progress
