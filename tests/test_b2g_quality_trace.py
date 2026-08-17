"""B2g：品质追溯 — 硬拦 / suggest 扩展 / trace_quality / 门面反查。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
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
    ProcessDefinition,
    ProcessType,
    Size,
    Tenant,
    TraceUnitAction,
    TraceUnitLog,
    TraceUnitStatus,
    Employee,
)
from app.services import trace_service
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


def _seed(db, *, trace_enabled=True):
    tenant = Tenant(name="追溯厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    w1 = Employee(tenant_id=tenant.id, name="张三", mobile="13900000001", is_active=True)
    w2 = Employee(tenant_id=tenant.id, name="李四", mobile="13900000002", is_active=True)
    product = OwnProduct(
        tenant_id=tenant.id,
        product_code="QT-01",
        quote_price=Decimal("80"),
        trace_enabled=trace_enabled,
    )
    zc = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        default_price=Decimal("1.5"),
        sort_order=1,
        type=ProcessType.personal,
    )
    cx = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("2.0"),
        sort_order=2,
        type=ProcessType.group,
    )
    db.add_all([color, size, w1, w2, product, zc, cx])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="QT-001",
        customer_name="测试",
        own_product_id=product.id,
        style_id=product.id,
        total_qty=100,
        delivery_date=date.today() + timedelta(days=10),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItem(
            tenant_id=tenant.id,
            order_id=order.id,
            color_id=color.id,
            size_id=size.id,
            qty=50,
        )
    )
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=zc.id,
            process_name="针车",
            process_type=ProcessType.personal,
            plan_qty=100,
            status=OrderProcessStatus.pending,
        )
    )
    db.commit()
    return {
        "tenant": tenant,
        "order": order,
        "product": product,
        "color": color,
        "size": size,
        "w1": w1,
        "w2": w2,
        "zc": zc,
        "cx": cx,
    }


def _bundle_with_reports(db, ctx, workers):
    unit = trace_service.create_bundle(
        db,
        tenant_id=ctx["tenant"].id,
        order_id=ctx["order"].id,
        qty=10,
        color_id=ctx["color"].id,
        size_id=ctx["size"].id,
        worker_id=ctx["w1"].id,
        process_id=ctx["zc"].id,
    )
    for w in workers:
        db.add(
            TraceUnitLog(
                tenant_id=ctx["tenant"].id,
                trace_unit_id=unit.id,
                action=TraceUnitAction.report,
                worker_id=w.id,
                process_id=ctx["zc"].id,
                qty=5,
                note="报工",
            )
        )
    unit.status = TraceUnitStatus.in_process
    db.commit()
    db.refresh(unit)
    return unit


def test_suggest_high_and_medium_and_group(db):
    ctx = _seed(db)
    unit = _bundle_with_reports(db, ctx, [ctx["w1"]])
    d = trace_service.suggest_responsible_detail(
        db,
        tenant_id=ctx["tenant"].id,
        trace_unit_id=unit.id,
        responsible_process_id=ctx["zc"].id,
    )
    assert d["worker_id"] == ctx["w1"].id
    assert d["confidence"] == "high"
    assert "张三" in (d["basis"] or "")
    assert len(d["candidates"]) == 1

    unit2 = _bundle_with_reports(db, ctx, [ctx["w1"], ctx["w2"]])
    d2 = trace_service.suggest_responsible_detail(
        db,
        tenant_id=ctx["tenant"].id,
        trace_unit_id=unit2.id,
        responsible_process_id=ctx["zc"].id,
    )
    assert d2["confidence"] == "medium"
    assert len(d2["candidates"]) == 2

    dg = trace_service.suggest_responsible_detail(
        db,
        tenant_id=ctx["tenant"].id,
        trace_unit_id=unit.id,
        responsible_process_id=ctx["cx"].id,
    )
    assert dg["confidence"] == "none"
    assert dg["worker_id"] is None
    assert "集体" in (dg["basis"] or "")


def test_create_defect_requires_bundle_when_active(db):
    ctx = _seed(db)
    _bundle_with_reports(db, ctx, [ctx["w1"]])
    with pytest.raises(TraceError) as ei:
        trace_service.create_defect_event(
            db,
            tenant_id=ctx["tenant"].id,
            defect_type="dirty",
            qty=1,
            order_id=ctx["order"].id,
            auto_suggest_worker=False,
        )
    assert ei.value.code == "trace_unit_required"


def test_create_defect_allow_weak_without_active_bundle(db):
    ctx = _seed(db)
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        auto_suggest_worker=False,
    )
    assert event.trace_unit_id is None
    out = trace_service.defect_out(db, event)
    assert out["trace_quality"] == "weak"


def test_trace_quality_strong_partial(db):
    ctx = _seed(db)
    unit = _bundle_with_reports(db, ctx, [ctx["w1"]])
    strong = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="open_seam",
        qty=1,
        order_id=ctx["order"].id,
        trace_unit_id=unit.id,
        responsible_process_id=ctx["zc"].id,
        responsible_worker_id=ctx["w1"].id,
        auto_suggest_worker=False,
    )
    assert trace_service.defect_out(db, strong)["trace_quality"] == "strong"

    partial = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        trace_unit_id=unit.id,
        responsible_process_id=ctx["zc"].id,
        auto_suggest_worker=False,
    )
    assert trace_service.defect_out(db, partial)["trace_quality"] == "partial"

    listed = trace_service.list_defects(
        db, tenant_id=ctx["tenant"].id, trace_quality="weak", page=1, page_size=20
    )
    assert listed["total"] == 0
    listed_p = trace_service.list_defects(
        db, tenant_id=ctx["tenant"].id, trace_quality="partial", page=1, page_size=20
    )
    assert listed_p["total"] == 1
    listed_s = trace_service.list_defects(
        db, tenant_id=ctx["tenant"].id, trace_quality="strong", page=1, page_size=20
    )
    assert listed_s["total"] == 1


def test_quality_trace_lookup_by_code_and_order(db):
    ctx = _seed(db)
    unit = _bundle_with_reports(db, ctx, [ctx["w1"]])
    by_code = trace_service.quality_trace_lookup(
        db, tenant_id=ctx["tenant"].id, q=unit.code
    )
    assert by_code["order"]["order_no"] == "QT-001"
    assert by_code["focus_unit"]["code"] == unit.code
    assert len(by_code["focus_unit"]["logs"]) >= 1

    by_order = trace_service.quality_trace_lookup(
        db, tenant_id=ctx["tenant"].id, q="QT-001"
    )
    assert by_order["units_summary"]["total"] >= 1
    assert by_order["focus_unit"] is None


def test_update_defect_writes_responsibility_note(db):
    ctx = _seed(db)
    event = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=1,
        order_id=ctx["order"].id,
        responsible_worker_id=ctx["w1"].id,
        auto_suggest_worker=False,
    )
    updated = trace_service.update_defect(
        db,
        tenant_id=ctx["tenant"].id,
        defect_id=event.id,
        responsible_worker_id=ctx["w2"].id,
        updated_by_user_id=99,
    )
    assert "[改责]" in (updated.note or "")
    assert "张三" in (updated.note or "")
    assert "李四" in (updated.note or "")
    assert "user#99" in (updated.note or "")
