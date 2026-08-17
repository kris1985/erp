"""B1b：不良 → 个人返修任务；集体返修仍禁。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    DefectEvent,
    DefectEventStatus,
    Order,
    OrderItem,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessType,
    ReworkTaskStatus,
    Size,
    Tenant,
    Employee,
)
from app.services import rework_task_service, report_service, trace_service
from app.services.report_service import ReportError
from app.services.rework_task_service import ReworkTaskError


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


def _seed(db):
    tenant = Tenant(name="返修厂")
    db.add(tenant)
    db.flush()
    color = Color(tenant_id=tenant.id, name="黑", code="BK")
    size = Size(tenant_id=tenant.id, size_value="40", sort_order=0)
    worker = Employee(tenant_id=tenant.id, name="张三", mobile="13900000001", is_active=True)
    product = OwnProduct(tenant_id=tenant.id, product_code="RW-01", quote_price=Decimal("80"))
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
    db.add_all([color, size, worker, product, zc, cx])
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
    order = Order(
        tenant_id=tenant.id,
        order_no="RW-001",
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
            qty=100,
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
            completed_qty=0,
            status=OrderProcessStatus.pending,
        )
    )
    db.add(
        OrderProcess(
            tenant_id=tenant.id,
            order_id=order.id,
            process_id=cx.id,
            process_name="成型",
            process_type=ProcessType.group,
            plan_qty=100,
            completed_qty=0,
            status=OrderProcessStatus.pending,
        )
    )
    db.commit()
    return {
        "tenant": tenant,
        "color": color,
        "size": size,
        "worker": worker,
        "product": product,
        "zc": zc,
        "cx": cx,
        "order": order,
    }


def test_dispatch_complete_and_filter(db):
    ctx = _seed(db)
    defect = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="open_seam",
        qty=5,
        order_id=ctx["order"].id,
        responsible_process_id=ctx["zc"].id,
        responsible_worker_id=ctx["worker"].id,
        disposition="rework",
        auto_suggest_worker=False,
    )
    task = rework_task_service.create_rework_task(
        db,
        ctx["tenant"].id,
        defect.id,
        worker_id=ctx["worker"].id,
        process_id=ctx["zc"].id,
        qty=5,
    )
    assert task["status"] == "pending"
    assert task["defect_event_id"] == defect.id

    listed = trace_service.list_defects(
        db, tenant_id=ctx["tenant"].id, pending_rework=True
    )
    assert listed["total"] == 1
    assert listed["items"][0]["pending_rework_task_id"] == task["id"]

    done = rework_task_service.complete_rework_task(
        db, ctx["tenant"].id, task["id"], close_defect=True
    )
    assert done["status"] == "done"
    db.refresh(defect)
    assert defect.status == DefectEventStatus.closed

    listed2 = trace_service.list_defects(
        db, tenant_id=ctx["tenant"].id, pending_rework=True
    )
    assert listed2["total"] == 0


def test_rework_report_auto_completes_task(db):
    ctx = _seed(db)
    defect = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="dirty",
        qty=3,
        order_id=ctx["order"].id,
        responsible_process_id=ctx["zc"].id,
        disposition="rework",
        auto_suggest_worker=False,
    )
    task = rework_task_service.create_rework_task(
        db,
        ctx["tenant"].id,
        defect.id,
        worker_id=ctx["worker"].id,
        process_id=ctx["zc"].id,
        qty=3,
    )
    result = report_service.submit_report(
        db,
        tenant_id=ctx["tenant"].id,
        worker_id=ctx["worker"].id,
        order_no=ctx["order"].order_no,
        process_name="针车",
        qualified_qty=3,
        report_type="rework",
    )
    assert result["rework_qty"] == 3
    assert result["rework_task_id"] == task["id"]

    from app.models import ReworkTask

    row = db.get(ReworkTask, task["id"])
    assert row.status == ReworkTaskStatus.done
    db.refresh(defect)
    assert defect.status == DefectEventStatus.closed


def test_group_process_cannot_dispatch_or_report_rework(db):
    ctx = _seed(db)
    defect = trace_service.create_defect_event(
        db,
        tenant_id=ctx["tenant"].id,
        defect_type="other",
        qty=2,
        order_id=ctx["order"].id,
        responsible_process_id=ctx["cx"].id,
        disposition="rework",
        auto_suggest_worker=False,
    )
    with pytest.raises(ReworkTaskError) as ei:
        rework_task_service.create_rework_task(
            db,
            ctx["tenant"].id,
            defect.id,
            worker_id=ctx["worker"].id,
            process_id=ctx["cx"].id,
            qty=2,
        )
    assert ei.value.code == "group_rework_forbidden"

    with pytest.raises(ReportError) as ei2:
        report_service.submit_report(
            db,
            tenant_id=ctx["tenant"].id,
            worker_id=ctx["worker"].id,
            order_no=ctx["order"].order_no,
            process_name="成型",
            qualified_qty=2,
            report_type="rework",
        )
    assert ei2.value.code == "group_rework_forbidden"
