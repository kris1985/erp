"""干掉生产单 K4-G：出货毛利认销售单、智能排产/计件认无壳执行单。"""

from datetime import date, datetime, timedelta
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
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessSegment,
    ProcessType,
    ReportType,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    ShipmentLine,
    Size,
    Tenant,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
    Employee,
)
from app.services import finance_service, salary_service, schedule_engine, schedule_service, shipment_service
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
    tenant = Tenant(name="K4G厂")
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
        tenant_id=tenant.id, product_code="K4G-A", is_active=True, trace_enabled=True
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
    session.add(Employee(tenant_id=tenant.id, name="报工员", mobile="13900006666"))
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
        unit_price=Decimal("80"),
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
        produced_qty=qty,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return so, line, item


def _header_only(db, *, qty: int = 12, order_no: str = "SO-K4G"):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    so, line, item = _so_item(
        db,
        order_no=order_no,
        qty=qty,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    exe = create_execution(
        db,
        tenant_id=tenant.id,
        items=[{"sales_order_line_item_id": item.id, "qty": qty}],
    )
    header = db.get(ExecutionHeader, exe.header_id)
    assert header is not None
    assert header.shop_order_id is None
    return tenant, header, exe, so, item


def test_shipment_and_profit_without_shop_order(db):
    tenant, header, _exe, so, item = _header_only(db, qty=10, order_no="SO-K4G-SHIP")
    out = shipment_service.create_shipment(
        db,
        tenant.id,
        sales_order_id=so.id,
        lines=[{"sales_order_line_item_id": item.id, "qty": 6}],
        confirm=True,
    )
    assert out["order_id"] is None
    assert out["sales_order_id"] == so.id
    assert out["status"] == "shipped"
    lines = list(
        db.scalars(select(ShipmentLine).where(ShipmentLine.shipment_id == out["id"])).all()
    )
    assert lines
    assert all(ln.order_item_id is None for ln in lines)
    db.refresh(item)
    assert int(item.shipped_qty) == 6

    report = finance_service.profit_report(db, tenant.id)
    row = next((r for r in report["orders"] if r.get("sales_order_id") == so.id), None)
    assert row is not None
    assert row["order_id"] is None
    assert row["order_no"] == so.order_no
    assert int(row["shipped_qty"]) == 6
    assert row["revenue"] == Decimal("480.0000")


def test_schedule_engine_header_only(db):
    tenant, header, _exe, _so, _item = _header_only(db, qty=8, order_no="SO-K4G-SCH")
    pack = schedule_engine.generate_proposals(
        db, tenant.id, header_ids=[header.id], hide_scheduled=False
    )
    assert pack["items"]
    first = pack["items"][0]
    plans = first["orders"]
    assert any(p.get("header_id") == header.id and p.get("order_id") is None for p in plans)
    assert any(p.get("order_no") == header.header_no for p in plans)
    assert any(p.get("windows") for p in plans)

    draft = schedule_service.create_draft_from_proposal(
        db, tenant.id, first, auto_assign=False
    )
    assert draft["lines"]
    for ln in draft["lines"]:
        assert ln["header_id"] == header.id
        assert ln["order_id"] is None
        assert ln["start_date"] and ln["end_date"]


def test_work_logs_filter_by_header_no(db):
    tenant, header, _exe, _so, _item = _header_only(db, qty=6, order_no="SO-K4G-WL")
    worker = db.scalar(select(Employee).limit(1))
    proc = db.scalar(
        select(OrderProcess).where(
            OrderProcess.tenant_id == tenant.id,
            OrderProcess.header_id == header.id,
        )
    )
    assert worker is not None and proc is not None
    segment = ProcessSegment(
        tenant_id=tenant.id,
        name="针车段",
        code="stitch-k4g",
        sort_order=1,
    )
    db.add(segment)
    db.flush()
    created_at = datetime.utcnow()
    db.add_all(
        [
            WorkLog(
                tenant_id=tenant.id,
                worker_id=worker.id,
                order_id=None,
                header_id=header.id,
                order_process_id=proc.id,
                own_product_id=header.own_product_id,
                process_id=proc.process_id,
                segment_id=segment.id,
                qualified_qty=4,
                unit_price=Decimal("1"),
                report_type=ReportType.normal,
                status=WorkLogStatus.valid,
                source=WorkLogSource.manual,
                created_at=created_at,
            ),
            WorkLog(
                tenant_id=tenant.id,
                worker_id=worker.id,
                order_id=None,
                header_id=header.id,
                order_process_id=proc.id,
                own_product_id=header.own_product_id,
                process_id=proc.process_id,
                segment_id=segment.id,
                qualified_qty=3,
                defect_qty=1,
                unit_price=Decimal("1"),
                report_type=ReportType.normal,
                status=WorkLogStatus.valid,
                source=WorkLogSource.manual,
                created_at=created_at,
            ),
        ]
    )
    db.commit()

    listed = salary_service.list_work_logs(
        db, tenant.id, order_no=header.header_no
    )
    assert listed["total"] >= 1
    assert any(r["order_no"] == header.header_no for r in listed["items"])

    by_segment = salary_service.list_work_logs(
        db, tenant.id, segment_id=segment.id, page_size=1
    )
    assert by_segment["total"] == 2
    assert len(by_segment["items"]) == 1
    assert by_segment["items"][0]["segment_id"] == segment.id
    assert by_segment["items"][0]["segment_name"] == segment.name
    assert by_segment["summary"] == {
        "unit_price_total": 2.0,
        "estimated_wage_total": 7.0,
        "qualified_qty_total": 7,
        "defect_qty_total": 1.0,
        "loss_amount_total": 0.0,
        "wage_deduction_total": 0.0,
    }
    assert salary_service.list_work_logs(db, tenant.id, segment_id=segment.id + 999)["total"] == 0

    local_report_date = (created_at + timedelta(hours=8)).date()
    by_date = salary_service.list_work_logs(
        db,
        tenant.id,
        date_from=local_report_date,
        date_to=local_report_date,
    )
    assert by_date["total"] == 2
    previous_date = local_report_date - timedelta(days=1)
    assert salary_service.list_work_logs(
        db,
        tenant.id,
        date_from=previous_date,
        date_to=previous_date,
    )["total"] == 0

    month = salary_service.month_salary(db, tenant.id, worker.id)
    assert any(d.get("order_no") == header.header_no for d in month.get("details") or [])
