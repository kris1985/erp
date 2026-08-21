"""方案 C：接单后显式建执行单头 + 多码明细。"""

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
    OrderProcess,
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
    create_execution,
    create_execution_from_sales_line,
    header_out,
    header_processes_out,
    list_execution_headers,
)
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
    tenant = Tenant(name="执行单头厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="39", sort_order=0))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=1))
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
        tenant_id=tenant.id, product_code="HDR-A", is_active=True, trace_enabled=True
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


def test_confirm_production_creates_header_and_size_lines(db):
    tenant_id = db.scalar(select(Tenant.id))
    color_id = db.scalar(select(Color.id))
    sizes = list(db.scalars(select(Size).order_by(Size.sort_order)).all())
    product_id = db.scalar(select(OwnProduct.id))

    so = SalesOrder(
        tenant_id=tenant_id,
        order_no="SO-HDR-1",
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

    confirm_sales_order_line(db, tenant_id, so.id, line.id, created_by=None)
    db.refresh(so)
    db.refresh(line)
    assert so.status == SalesOrderStatus.confirmed
    assert line.execution_header_id is None

    create_execution_from_sales_line(
        db, tenant_id=tenant_id, sales_order=so, line=line, created_by=None, commit=True
    )
    db.refresh(line)

    assert line.production_order_id is None
    assert line.execution_header_id
    header = db.get(ExecutionHeader, line.execution_header_id)
    assert header is not None
    assert header.header_no.startswith("XE-")
    assert header.shop_order_id is None
    assert header.total_qty == 30

    size_lines = list(
        db.scalars(
            select(SpecExecutionOrder)
            .where(SpecExecutionOrder.header_id == header.id)
            .order_by(SpecExecutionOrder.id)
        ).all()
    )
    assert len(size_lines) == 2
    assert {x.total_qty for x in size_lines} == {10, 20}
    assert all(x.shop_order_id is None for x in size_lines)
    assert all(x.execution_no.startswith(header.header_no + "-") for x in size_lines)

    items = list(
        db.scalars(
            select(SalesOrderLineItem).where(SalesOrderLineItem.sales_order_line_id == line.id)
        ).all()
    )
    assert all(int(it.allocated_qty) == int(it.qty) for it in items)

    headers = list_execution_headers(db, tenant_id=tenant_id)
    assert len(headers) == 1
    assert headers[0].id == header.id
    assert list_execution_headers(db, tenant_id=tenant_id, q="客户甲")
    assert list_execution_headers(db, tenant_id=tenant_id, q="HDR-A")
    assert list_execution_headers(db, tenant_id=tenant_id, q="SO-HDR-1")
    assert list_execution_headers(db, tenant_id=tenant_id, q=header.header_no)
    assert list_execution_headers(db, tenant_id=tenant_id, q="NO-SUCH") == []
    assert list_execution_headers(db, tenant_id=tenant_id, status="confirmed")
    assert list_execution_headers(db, tenant_id=tenant_id, status="active")
    assert list_execution_headers(db, tenant_id=tenant_id, status="production") == []
    assert list_execution_headers(db, tenant_id=tenant_id, status="completed") == []
    assert list_execution_headers(db, tenant_id=tenant_id, is_rush=True) == []
    assert list_execution_headers(db, tenant_id=tenant_id, is_rush=False)
    out = header_out(db, headers[0])
    assert out["customers"] == ["客户甲"]
    assert out["sales_order_nos"] == ["SO-HDR-1"]
    assert "product_image_url" in out
    assert "kit" in out
    assert out["risk"]["level"] in {"normal", "attention", "high", "late"}
    assert out["risk"]["label"] in {"正常", "关注", "高风险", "必延期"}
    assert out["risk"]["reasons"]
    assert out["risk"]["recommendation"]
    assert (out["allocations"] or [])[0]["customer_name"] == "客户甲"


def test_merge_create_execution_also_creates_header(db):
    tenant_id = db.scalar(select(Tenant.id))
    color_id = db.scalar(select(Color.id))
    size_id = db.scalar(select(Size.id).where(Size.size_value == "40"))
    product_id = db.scalar(select(OwnProduct.id))

    so = SalesOrder(
        tenant_id=tenant_id,
        order_no="SO-MERGE-H",
        customer_name="客户乙",
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
        total_qty=15,
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
        qty=15,
    )
    db.add(item)
    db.commit()

    exe = create_execution(
        db,
        tenant_id=tenant_id,
        items=[{"sales_order_line_item_id": item.id, "qty": 15}],
    )
    assert exe.header_id
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    assert header.total_qty == 15
    assert exe.shop_order_id is None
    assert header.shop_order_id is None
    alloc = db.scalar(
        select(ExecutionAllocation).where(ExecutionAllocation.execution_id == exe.id)
    )
    assert alloc and alloc.qty == 15


def test_list_headers_sort_rush_then_delivery(db):
    tenant_id = db.scalar(select(Tenant.id))
    product_id = db.scalar(select(OwnProduct.id))
    size_id = db.scalar(select(Size.id))
    today = date.today()

    late = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-LATE",
        own_product_id=product_id,
        total_qty=8,
        completed_qty=8,
        delivery_date=today + timedelta(days=10),
        status=SpecExecutionStatus.confirmed,
    )
    soon = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-SOON",
        own_product_id=product_id,
        total_qty=3,
        completed_qty=1,
        delivery_date=today + timedelta(days=2),
        status=SpecExecutionStatus.confirmed,
    )
    rush = ExecutionHeader(
        tenant_id=tenant_id,
        header_no="XE-RUSH",
        own_product_id=product_id,
        total_qty=1,
        delivery_date=today + timedelta(days=20),
        status=SpecExecutionStatus.confirmed,
    )
    db.add_all([late, soon, rush])
    db.flush()
    db.add(
        SpecExecutionOrder(
            tenant_id=tenant_id,
            execution_no="XE-RUSH-40",
            header_id=rush.id,
            own_product_id=product_id,
            size_id=size_id,
            total_qty=1,
            status=SpecExecutionStatus.confirmed,
            is_rush=True,
        )
    )
    db.commit()

    nos = [r.header_no for r in list_execution_headers(db, tenant_id=tenant_id)]
    assert nos[:3] == ["XE-RUSH", "XE-SOON", "XE-LATE"]

    by_progress = [
        r.header_no
        for r in list_execution_headers(db, tenant_id=tenant_id, sort_by="progress", sort_order="desc")
    ]
    assert by_progress[0] == "XE-RUSH"
    assert by_progress[1:] == ["XE-LATE", "XE-SOON"]

    by_rush_asc = [
        r.header_no
        for r in list_execution_headers(db, tenant_id=tenant_id, sort_by="is_rush", sort_order="asc")
    ]
    assert by_rush_asc[-1] == "XE-RUSH"

    with pytest.raises(ExecutionError) as ei:
        list_execution_headers(db, tenant_id=tenant_id, sort_by="priority")
    assert ei.value.code == "invalid_sort"


def test_header_processes_out_marks_current_and_done(db):
    tenant_id = db.scalar(select(Tenant.id))
    color_id = db.scalar(select(Color.id))
    size_id = db.scalar(select(Size.id))
    product_id = db.scalar(select(OwnProduct.id))
    stitch = ProcessDefinition(
        tenant_id=tenant_id,
        name="针车",
        code="ZC",
        default_price=Decimal("1"),
        sort_order=2,
    )
    db.add(stitch)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant_id,
            own_product_id=product_id,
            process_id=stitch.id,
            process_name=stitch.name,
            unit_price=Decimal("1"),
            sort_order=1,
        )
    )
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no="SO-PROC",
        customer_name="客户",
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
        total_qty=10,
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
            qty=10,
        )
    )
    db.commit()
    header = create_execution_from_sales_line(
        db, tenant_id=tenant_id, sales_order=so, line=line, created_by=None, commit=True
    )
    out = header_processes_out(db, header)
    names = [x["process_name"] for x in out["items"]]
    assert names == ["成型", "针车"]
    assert out["all_done"] is False
    assert out["items"][0]["is_current"] is True
    assert out["items"][1]["is_current"] is False
    assert out["current_process_name"] == "成型"

    first = db.get(OrderProcess, out["items"][0]["id"])
    first.completed_qty = first.plan_qty
    db.commit()
    db.refresh(header)
    out2 = header_processes_out(db, header)
    assert out2["items"][0]["is_done"] is True
    assert out2["items"][1]["is_current"] is True
    assert out2["current_process_name"] == "针车"

    second = db.get(OrderProcess, out2["items"][1]["id"])
    second.completed_qty = second.plan_qty
    db.commit()
    out3 = header_processes_out(db, header)
    assert out3["all_done"] is True
    assert out3["current_process_name"] is None
    assert all(x["is_current"] is False for x in out3["items"])
    assert all(x["is_done"] is True for x in out3["items"])
