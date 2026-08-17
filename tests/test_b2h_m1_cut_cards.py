"""B2h-M1：开裁打主码 / 作废 / 自动起捆互斥。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessType,
    Size,
    Tenant,
    TraceUnit,
    TraceUnitAction,
    TraceUnitLog,
    TraceUnitStatus,
    Employee,
)
from app.services import report_service, trace_service
from app.services.report_service import ReportError
from app.services.trace_service import TraceError


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed(db, *, trace_enabled=True, sizes_qty=None):
    """sizes_qty: list[(size_value, qty)] default 40/120 + 41/50."""
    tenant = Tenant(name="开裁厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    worker = Employee(tenant_id=tenant.id, name="张三", mobile="13900000011", is_active=True)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="CUT-01",
        quote_price=Decimal("80"),
        trace_enabled=trace_enabled,
    )
    zc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1.5"),
        per_worker_capacity=Decimal("50"),
        standard_workers=1,
        sort_order=1,
        type=ProcessType.personal,
    )
    db.add_all([color, worker, product, zc])
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id,
            own_product_id=product.id,
            process_id=zc.id,
            process_name="针车",
            unit_price=Decimal("1.5"),
            sort_order=1,
        )
    )

    specs = sizes_qty or [("40", 120), ("41", 50)]
    sizes = []
    for i, (sv, _) in enumerate(specs):
        s = Size(tenant_id=tenant.id, size_value=sv, sort_order=i)
        db.add(s)
        sizes.append(s)
    db.flush()

    order = Order(
        tenant_id=tenant.id,
        order_no="CUT-ORD-1",
        customer_name="客A",
        own_product_id=product.id,
        total_qty=0,
        delivery_date=date.today() + timedelta(days=14),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    total = 0
    for s, (_, qty) in zip(sizes, specs):
        db.add(
            OrderItem(
                tenant_id=tenant.id,
                order_id=order.id,
                color_id=color.id,
                size_id=s.id,
                qty=qty,
            )
        )
        total += qty
    order.total_qty = total
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=zc.id,
            process_name="针车",
            process_type=ProcessType.personal,
            plan_qty=total,
            completed_qty=0,
            status=OrderProcessStatus.pending,
        )
    )
    db.commit()
    return {
        "tenant": tenant,
        "order": order,
        "color": color,
        "sizes": sizes,
        "worker": worker,
        "product": product,
        "process": zc,
    }


def test_cut_cards_dry_run_no_write(db):
    ctx = _seed(db)
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=True,
    )
    # 默认按筐量(40)拆：120 → 40×3；50 → 40+10
    assert data["mode"] == "basket"
    assert data["to_create"] == 5
    assert all(line["action"] == "create" for line in data["lines"])
    assert db.scalar(select(func.count()).select_from(TraceUnit)) == 0


def test_cut_cards_create_and_skip_exists(db):
    ctx = _seed(db)
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
    )
    assert data["to_create"] == 5
    assert len(data["created"]) == 5
    assert all(c["code"].startswith("TU") for c in data["created"])
    assert db.scalar(select(func.count()).select_from(TraceUnit)) == 5

    again = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
        only_missing=True,
    )
    assert again["to_create"] == 0
    assert all(line["action"] == "skip_exists" for line in again["lines"])
    assert db.scalar(select(func.count()).select_from(TraceUnit)) == 5


def test_cut_cards_bundle_size(db):
    ctx = _seed(db, sizes_qty=[("40", 120)])
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
        bundle_size=50,
    )
    assert data["to_create"] == 3
    assert sorted(c["qty"] for c in data["created"]) == [20, 50, 50]
    assert db.scalar(select(func.count()).select_from(TraceUnit)) == 3


def test_cut_cards_without_trace_enabled(db):
    ctx = _seed(db, trace_enabled=False)
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=True,
    )
    assert data["to_create"] >= 1
    assert data["print_path"]


def test_void_and_report_blocked(db):
    ctx = _seed(db, sizes_qty=[("40", 10)])
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
    )
    unit_id = data["created"][0]["id"]
    unit = trace_service.void_trace_unit(
        db, tenant_id=ctx["tenant"].id, unit_id=unit_id
    )
    assert unit.status == TraceUnitStatus.scrapped
    log = db.scalar(
        select(TraceUnitLog).where(
            TraceUnitLog.trace_unit_id == unit_id,
            TraceUnitLog.action == TraceUnitAction.void,
        )
    )
    assert log is not None

    with pytest.raises(ReportError) as ei:
        report_service.submit_report(
            db,
            tenant_id=ctx["tenant"].id,
            worker_id=ctx["worker"].id,
            order_no=ctx["order"].order_no,
            process_name="针车",
            qualified_qty=1,
            color_name="黑",
            size_value="40",
            confirm_over_plan=True,
            trace_unit_id=unit_id,
            create_trace_bundle=False,
        )
    assert ei.value.code == "trace_unit_inactive"


def test_void_blocked_after_report(db):
    ctx = _seed(db, sizes_qty=[("40", 10)])
    data = trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
    )
    unit_id = data["created"][0]["id"]
    report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=ctx["worker"].id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=2,
        color_name="黑",
        size_value="40",
        confirm_over_plan=True,
        trace_unit_id=unit_id,
        create_trace_bundle=False,
    )
    with pytest.raises(TraceError) as ei:
        trace_service.void_trace_unit(
            db, tenant_id=ctx["tenant"].id, unit_id=unit_id
        )
    assert ei.value.code == "has_reports"


def test_no_auto_bundle_after_cut_cards(db):
    ctx = _seed(db, sizes_qty=[("40", 10)])
    trace_service.preview_or_create_cut_cards(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        dry_run=False,
    )
    before = db.scalar(select(func.count()).select_from(TraceUnit))
    # 不传 create_trace_bundle：默认应因已开裁而不再静默起捆
    result = report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=ctx["worker"].id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=3,
        color_name="黑",
        size_value="40",
        confirm_over_plan=True,
    )
    assert result.get("trace_code") in (None, "")
    after = db.scalar(select(func.count()).select_from(TraceUnit))
    assert after == before
