"""B2b：配码装箱 — 单码/混码合计一致 + 验箱错码拦。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Color, Order, OrderItem, OrderStatus, OwnProduct, Size, Tenant
from app.services import packing_service
from app.services.packing_service import PackingError


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
    tenant = Tenant(name="装箱厂")
    db.add(tenant)
    db.flush()
    c1 = Color(tenant_id=tenant.id, name="红", code="R")
    c2 = Color(tenant_id=tenant.id, name="黑", code="BK")
    s37 = Size(tenant_id=tenant.id, size_value="37", sort_order=0)
    s38 = Size(tenant_id=tenant.id, size_value="38", sort_order=1)
    product = OwnProduct(tenant_id=tenant.id, product_code="箱唛款", quote_price=Decimal("68"))
    db.add_all([c1, c2, s37, s38, product])
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="PK-001",
        customer_name="箱唛客户",
        own_product_id=product.id,
        style_id=product.id,
        total_qty=30,
        delivery_date=date.today() + timedelta(days=7),
        status=OrderStatus.confirmed,
    )
    db.add(order)
    db.flush()
    db.add_all(
        [
            OrderItem(
                tenant_id=tenant.id, order_id=order.id, color_id=c1.id, size_id=s37.id, qty=10
            ),
            OrderItem(
                tenant_id=tenant.id, order_id=order.id, color_id=c1.id, size_id=s38.id, qty=8
            ),
            OrderItem(
                tenant_id=tenant.id, order_id=order.id, color_id=c2.id, size_id=s37.id, qty=12
            ),
        ]
    )
    db.commit()
    return {
        "tenant": tenant,
        "order": order,
        "c1": c1,
        "c2": c2,
        "s37": s37,
        "s38": s38,
    }


def test_single_size_pack_totals(db):
    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="single_size",
        pairs_per_carton=12,
    )
    assert plan["total_qty"] == 30
    assert plan["mode"] == "single_size"
    assert plan["carton_count"] == 3
    assert sum(c["total_qty"] for c in plan["cartons"]) == 30
    for c in plan["cartons"]:
        assert len(c["lines"]) == 1


def test_mixed_pack_and_label_fields(db):
    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="mixed",
        pairs_per_carton=12,
    )
    assert plan["total_qty"] == 30
    assert plan["carton_count"] == 3
    assert plan["cartons"][0]["order_no"] == "PK-001"
    assert plan["cartons"][0]["product_code"] == "箱唛款"
    assert plan["cartons"][0]["customer_name"] == "箱唛客户"
    assert plan["cartons"][0]["code"].startswith("CTN-PK-001-")


def test_verify_blocks_wrong_and_accepts_match(db):
    ctx = _seed(db)
    plan = packing_service.create_packing_plan(
        db,
        ctx["tenant"].id,
        ctx["order"].id,
        mode="single_size",
        pairs_per_carton=12,
    )
    carton = plan["cartons"][0]
    line = carton["lines"][0]
    with pytest.raises(PackingError) as ei:
        packing_service.verify_packing_carton(
            db,
            ctx["tenant"].id,
            carton["id"],
            lines=[{"color_id": line["color_id"], "size_id": line["size_id"], "qty": line["qty"] + 1}],
        )
    assert ei.value.code in ("over_pack", "wrong_size")

    with pytest.raises(PackingError) as ei2:
        packing_service.verify_packing_carton(
            db,
            ctx["tenant"].id,
            carton["id"],
            lines=[
                {
                    "color_id": ctx["c2"].id,
                    "size_id": ctx["s38"].id,
                    "qty": line["qty"],
                }
            ],
        )
    assert ei2.value.code in ("wrong_size", "mismatch")

    ok = packing_service.verify_packing_carton(
        db,
        ctx["tenant"].id,
        carton["id"],
        lines=[{"color_id": line["color_id"], "size_id": line["size_id"], "qty": line["qty"]}],
    )
    assert ok["verified_at"]


def test_carton_report_creates_work_log_and_dedups(db):
    """扫箱唛报工：装一箱报一箱，报工量=箱内双数，一箱只报一次。"""
    from decimal import Decimal as D

    from app.models import (
        Employee,
        ExecutionHeader,
        OrderProcess,
        OwnProductLabor,
        PackingCarton,
        PackingMode,
        PackingPlan,
        PackingPlanStatus,
        ProcessDefinition,
        ProcessSegment,
        ProcessType,
        WorkLog,
    )
    from app.services import report_service
    from app.services.segment_service import ensure_default_segments

    tenant = Tenant(name="扫箱报工厂")
    db.add(tenant)
    db.flush()
    ensure_default_segments(db, tenant.id)
    packing_seg = db.scalar(
        select(ProcessSegment).where(
            ProcessSegment.tenant_id == tenant.id, ProcessSegment.code == "packing"
        )
    )
    box = ProcessDefinition(
        tenant_id=tenant.id, name="装箱", code="BX1", segment_id=packing_seg.id, type=ProcessType.personal
    )
    db.add(box)
    db.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="SP-BOX")
    db.add(product)
    db.flush()
    db.add(
        OwnProductLabor(
            tenant_id=tenant.id, own_product_id=product.id, process_id=box.id,
            process_name="装箱", unit_price=D("0.20"), sort_order=0,
        )
    )
    db.flush()
    worker = Employee(tenant_id=tenant.id, name="装箱工", is_active=True)
    db.add(worker)
    db.flush()
    header = ExecutionHeader(
        tenant_id=tenant.id, header_no="EH-BOX", own_product_id=product.id, total_qty=100,
    )
    db.add(header)
    db.flush()
    op = OrderProcess(
        tenant_id=tenant.id, header_id=header.id, process_id=box.id, process_name="装箱",
        process_type=ProcessType.personal, segment_id=packing_seg.id, plan_qty=100,
    )
    db.add(op)
    db.flush()
    plan = PackingPlan(
        tenant_id=tenant.id, header_id=header.id, mode=PackingMode.single_size,
        pairs_per_carton=12, status=PackingPlanStatus.draft,
    )
    db.add(plan)
    db.flush()
    carton = PackingCarton(
        tenant_id=tenant.id, plan_id=plan.id, seq=1, code="CTN-EH-BOX-0001", total_qty=12,
    )
    db.add(carton)
    db.commit()

    res = report_service.submit_carton_report(
        db, tenant_id=tenant.id, worker_id=worker.id, carton_code="CTN-EH-BOX-0001",
    )
    assert res["ok"] is True
    assert res["qualified_qty"] == 12
    assert res["work_log_id"]

    log = db.get(WorkLog, res["work_log_id"])
    assert log is not None
    assert log.worker_id == worker.id
    assert log.header_id == header.id
    assert log.qualified_qty == 12
    assert log.process_id == box.id

    carton = db.get(PackingCarton, carton.id)
    assert carton.reported_work_log_id == log.id
    op = db.get(OrderProcess, op.id)
    assert op.completed_qty == 12

    # 重复扫同一箱 → 拦截
    from app.services.report_service import ReportError

    with pytest.raises(ReportError) as ei:
        report_service.submit_carton_report(
            db, tenant_id=tenant.id, worker_id=worker.id, carton_code="CTN-EH-BOX-0001",
        )
    assert ei.value.code == "carton_reported"
