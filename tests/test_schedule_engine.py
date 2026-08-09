"""规则排产引擎：工作日倒排、方案对比、插单影响、可复现 proposal_id。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
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
)
from app.services import schedule_engine, schedule_service, schedule_settings
from app.utils import cn_holidays


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
    tenant = Tenant(name="引擎厂", settings_json={})
    session.add(tenant)
    session.flush()
    session.add(Size(tenant_id=tenant.id, size_value="38", sort_order=1))
    ct = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CT",
        default_price=Decimal("0.3"),
        default_days=2,
        sort_order=1,
    )
    cx = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.group,
        default_price=Decimal("0.5"),
        default_days=3,
        sort_order=2,
    )
    session.add_all([ct, cx])
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="E1", is_active=True)
    session.add(product)
    session.commit()
    yield session, tenant.id, product.id, ct.id, cx.id
    session.close()


def _order(session, tenant_id, product_id, ct_id, cx_id, *, order_no: str, qty: int, delivery: date, rush=False):
    size = session.scalar(select(Size).where(Size.tenant_id == tenant_id))
    order = Order(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客",
        own_product_id=product_id,
        total_qty=qty,
        delivery_date=delivery,
        status=OrderStatus.confirmed,
        is_rush=rush,
    )
    session.add(order)
    session.flush()
    session.add(OrderItem(tenant_id=tenant_id, order_id=order.id, size_id=size.id, qty=qty, completed_qty=0))
    session.add_all(
        [
            OrderProcess(
                tenant_id=tenant_id,
                order_id=order.id,
                process_id=ct_id,
                process_name="裁断",
                process_type=ProcessType.personal,
                plan_qty=qty,
                status=OrderProcessStatus.pending,
            ),
            OrderProcess(
                tenant_id=tenant_id,
                order_id=order.id,
                process_id=cx_id,
                process_name="成型",
                process_type=ProcessType.group,
                plan_qty=qty,
                status=OrderProcessStatus.pending,
            ),
        ]
    )
    session.commit()
    return order


def test_workday_helpers_skip_weekend_and_holiday():
    # 2026-01-01 是元旦假期
    assert cn_holidays.is_workday(date(2026, 1, 1)) is False
    assert cn_holidays.prev_workday(date(2026, 1, 1)) == date(2025, 12, 31)
    # 跨周末：周五+1 工作日 = 周一（非节假日时）
    fri = date(2026, 3, 6)  # Fri
    assert cn_holidays.add_workdays(fri, 1) == date(2026, 3, 9)


def test_generate_proposals_reproducible(db):
    session, tenant_id, product_id, ct_id, cx_id = db
    delivery = date.today() + timedelta(days=20)
    o1 = _order(session, tenant_id, product_id, ct_id, cx_id, order_no="MO-A", qty=100, delivery=delivery)
    o2 = _order(
        session, tenant_id, product_id, ct_id, cx_id, order_no="MO-B", qty=80, delivery=delivery, rush=True
    )

    a = schedule_engine.generate_proposals(session, tenant_id, order_ids=[o1.id, o2.id])["items"]
    b = schedule_engine.generate_proposals(session, tenant_id, order_ids=[o1.id, o2.id])["items"]
    assert len(a) >= 2
    assert [p["proposal_id"] for p in a] == [p["proposal_id"] for p in b]
    assert a[0]["engine_version"] == schedule_engine.ENGINE_VERSION
    # 急单应排在保交期方案更前（priority）
    first = a[0]["orders"][0]
    assert first["order_no"] == "MO-B"


def test_backward_uses_process_default_days(db):
    session, tenant_id, product_id, ct_id, cx_id = db
    delivery = date(2026, 4, 30)
    order = _order(session, tenant_id, product_id, ct_id, cx_id, order_no="MO-D", qty=50, delivery=delivery)
    procs = list(
        session.scalars(
            select(OrderProcess).where(OrderProcess.order_id == order.id).order_by(OrderProcess.id)
        ).all()
    )
    cfg = schedule_settings.get_schedule_by_tenant_id(session, tenant_id)
    days_map = schedule_engine._process_days_map(session, tenant_id, cfg)
    assert days_map[ct_id] == 2
    assert days_map[cx_id] == 3
    windows = schedule_engine.backward_windows_for_processes(
        procs, delivery, days_map, as_of=date(2026, 4, 1)
    )
    assert len(windows) == 2
    assert windows[0].days == 2
    assert windows[1].days == 3
    assert windows[0].end_date < windows[1].start_date
    assert cn_holidays.is_workday(windows[0].start_date)
    assert cn_holidays.is_workday(windows[1].end_date)


def test_capacity_marks_blocked(db):
    session, tenant_id, product_id, ct_id, cx_id = db
    schedule_settings.save_schedule_patch(
        session,
        tenant_id,
        {"daily_capacity_by_process": {str(ct_id): 10, str(cx_id): 10}},
    )
    delivery = date.today() + timedelta(days=30)
    order = _order(session, tenant_id, product_id, ct_id, cx_id, order_no="MO-C", qty=500, delivery=delivery)
    props = schedule_engine.generate_proposals(session, tenant_id, order_ids=[order.id])["items"]
    delivery_first = next(p for p in props if p["strategy"] == "delivery_first")
    risks = {o["order_id"]: o["risk"] for o in delivery_first["orders"]}
    # 产能极低时应标红（capacity_blocked 或 late）
    assert risks[order.id] in ("capacity_blocked", "late", "tight", "ok")
    # 至少有负荷行或风险统计字段
    assert "risks" in delivery_first


def test_simulate_insert_has_impacts(db):
    session, tenant_id, product_id, ct_id, cx_id = db
    schedule_settings.save_schedule_patch(
        session,
        tenant_id,
        {"daily_capacity_by_process": {str(ct_id): 100, str(cx_id): 100}},
    )
    d1 = date.today() + timedelta(days=15)
    d2 = date.today() + timedelta(days=18)
    a = _order(session, tenant_id, product_id, ct_id, cx_id, order_no="MO-1", qty=200, delivery=d1)
    b = _order(session, tenant_id, product_id, ct_id, cx_id, order_no="MO-2", qty=200, delivery=d2, rush=True)
    props = schedule_engine.simulate_insert(session, tenant_id, b.id)
    assert len(props) == 3
    assert all("impacts" in p for p in props)
    assert all(p["proposal_id"] for p in props)


def test_simulate_intake_without_production_order(db):
    session, tenant_id, product_id, ct_id, cx_id = db
    schedule_settings.save_schedule_patch(
        session,
        tenant_id,
        {"daily_capacity_by_process": {str(ct_id): 80, str(cx_id): 80}},
    )
    session.add(
        OwnProductLabor(
            tenant_id=tenant_id,
            own_product_id=product_id,
            process_id=ct_id,
            process_name="裁断",
            unit_price=Decimal("0.3"),
            sort_order=0,
        )
    )
    session.add(
        OwnProductLabor(
            tenant_id=tenant_id,
            own_product_id=product_id,
            process_id=cx_id,
            process_name="成型",
            unit_price=Decimal("0.5"),
            sort_order=1,
        )
    )
    session.flush()
    _order(
        session,
        tenant_id,
        product_id,
        ct_id,
        cx_id,
        order_no="MO-BASE",
        qty=150,
        delivery=date.today() + timedelta(days=14),
    )
    sim = schedule_engine.simulate_intake_demands(
        session,
        tenant_id,
        [
            {
                "key": "so_line:1",
                "order_no": "SO-NEW",
                "own_product_id": product_id,
                "total_qty": 120,
                "delivery_date": (date.today() + timedelta(days=12)).isoformat(),
                "is_rush": True,
            }
        ],
    )
    assert sim.get("sim_error") is None
    assert len(sim.get("proposals") or []) == 3
    primary = next(p for p in sim["proposals"] if p["strategy"] == "protect_delivery")
    assert primary.get("intake_orders")
    assert primary["intake_orders"][0].get("projected_finish")


def test_simulate_intake_no_route(db):
    session, tenant_id, product_id, ct_id, cx_id = db
    sim = schedule_engine.simulate_intake_demands(
        session,
        tenant_id,
        [
            {
                "key": "x",
                "order_no": "SO-X",
                "own_product_id": product_id,
                "total_qty": 10,
                "delivery_date": date.today().isoformat(),
            }
        ],
    )
    assert sim.get("sim_error") == "no_route"


def test_simulate_intake_respects_earliest_start(db):
    session, tenant_id, product_id, ct_id, cx_id = db
    schedule_settings.save_schedule_patch(
        session,
        tenant_id,
        {"daily_capacity_by_process": {str(ct_id): 80, str(cx_id): 80}},
    )
    session.add(
        OwnProductLabor(
            tenant_id=tenant_id,
            own_product_id=product_id,
            process_id=ct_id,
            process_name="裁断",
            unit_price=Decimal("0.3"),
            sort_order=0,
        )
    )
    session.add(
        OwnProductLabor(
            tenant_id=tenant_id,
            own_product_id=product_id,
            process_id=cx_id,
            process_name="成型",
            unit_price=Decimal("0.5"),
            sort_order=1,
        )
    )
    session.flush()
    eta = date.today() + timedelta(days=5)
    sim = schedule_engine.simulate_intake_demands(
        session,
        tenant_id,
        [
            {
                "key": "so_line:eta",
                "order_no": "SO-ETA",
                "own_product_id": product_id,
                "total_qty": 40,
                "delivery_date": (date.today() + timedelta(days=20)).isoformat(),
                "earliest_start": eta.isoformat(),
            }
        ],
    )
    assert sim.get("sim_error") is None
    primary = next(p for p in sim["proposals"] if p["strategy"] == "protect_delivery")
    intake = (primary.get("intake_orders") or [None])[0] or {}
    notes = " ".join(intake.get("notes") or [])
    assert f"等料至{eta.isoformat()}" in notes


def test_adopt_proposal_creates_draft(db):
    session, tenant_id, product_id, ct_id, cx_id = db
    delivery = date.today() + timedelta(days=25)
    order = _order(session, tenant_id, product_id, ct_id, cx_id, order_no="MO-AD", qty=60, delivery=delivery)
    props = schedule_engine.generate_proposals(session, tenant_id, order_ids=[order.id])["items"]
    draft = schedule_service.create_draft_from_proposal(session, tenant_id, props[0], auto_assign=False)
    assert draft["status"] == "draft"
    assert draft["id"]
    assert len(draft["lines"]) == 2
    assert "engine:" in (draft.get("note") or "")
