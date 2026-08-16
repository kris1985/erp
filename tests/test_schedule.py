"""排产草稿：倒排 → 确认写时间窗；首道缺料阻断。"""

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
    OrderMaterialRequirement,
    OrderProcess,
    OrderProcessStatus,
    OrderStatus,
    OwnProduct,
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    ProcessType,
    ScheduleDraftStatus,
    ScheduleStatus,
    Size,
    SupplierProduct,
    Tenant,
)
from app.services import material_service, schedule_service


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
    tenant = Tenant(name="排产厂")
    session.add(tenant)
    session.flush()
    session.add(Size(tenant_id=tenant.id, size_value="38", sort_order=1))
    partner = Partner(tenant_id=tenant.id, name="供A", is_supplier=True, is_active=True)
    session.add(partner)
    ct = ProcessDefinition(
        tenant_id=tenant.id, name="裁断", code="CT", default_price=Decimal("0.3"), sort_order=1
    )
    cx = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        type=ProcessType.group,
        default_price=Decimal("0.5"),
        sort_order=2,
    )
    session.add_all([ct, cx])
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="S1", is_active=True)
    session.add(product)
    session.flush()
    sp = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT",
        name="面布",
        partner_id=partner.id,
        unit_price=Decimal("1"),
        is_active=True,
    )
    session.add(sp)
    session.flush()
    session.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=sp.id,
            qty=Decimal("1"),
            unit_price=Decimal("1"),
            line_total=Decimal("1"),
            consume_process_id=ct.id,
        )
    )
    session.commit()
    yield session, tenant.id, product.id, sp.id, ct.id, cx.id
    session.close()


def _order(session, tenant_id, product_id, ct_id, cx_id, *, order_no: str, qty: int, delivery: date):
    size = session.scalar(select(Size).where(Size.tenant_id == tenant_id))
    order = Order(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客",
        own_product_id=product_id,
        total_qty=qty,
        delivery_date=delivery,
        status=OrderStatus.confirmed,
        schedule_status=ScheduleStatus.none,
    )
    session.add(order)
    session.flush()
    session.add(
        OrderItem(
            tenant_id=tenant_id,
            order_id=order.id,
            size_id=size.id,
            qty=qty,
            completed_qty=0,
        )
    )
    session.add(
        OrderProcess(
            tenant_id=tenant_id,
            order_id=order.id,
            process_id=ct_id,
            process_name="裁断",
            process_type=ProcessType.personal,
            plan_qty=qty,
            status=OrderProcessStatus.pending,
        )
    )
    session.add(
        OrderProcess(
            tenant_id=tenant_id,
            order_id=order.id,
            process_id=cx_id,
            process_name="成型",
            process_type=ProcessType.group,
            plan_qty=qty,
            status=OrderProcessStatus.pending,
        )
    )
    session.flush()
    material_service.ensure_material_snapshot(session, tenant_id, order)
    session.commit()
    return order


def test_backward_draft_and_confirm(db):
    session, tenant_id, product_id, sp_id, ct_id, cx_id = db
    delivery = date(2026, 8, 20)
    order = _order(
        session, tenant_id, product_id, ct_id, cx_id, order_no="MO1", qty=10, delivery=delivery
    )
    # 首道料齐
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("10")
    session.commit()

    pool = schedule_service.list_schedule_pool(session, tenant_id)
    assert len(pool) == 1
    assert pool[0]["first_kit_ok"] is True

    draft = schedule_service.create_draft(
        session, tenant_id, [order.id], days_per_process=1, auto_assign=False
    )
    assert draft["status"] == "draft"
    assert len(draft["lines"]) == 2
    # 倒排：成型完工=交期，裁断在前
    by_name = {x["process_name"]: x for x in draft["lines"]}
    assert by_name["成型"]["end_date"] == delivery
    assert by_name["裁断"]["end_date"] == delivery - timedelta(days=1)

    drafts = schedule_service.list_drafts(session, tenant_id, status="draft")
    assert any(d["id"] == draft["id"] and d["order_count"] == 1 for d in drafts)

    session.refresh(order)
    assert order.schedule_status == ScheduleStatus.drafted

    confirmed = schedule_service.confirm_draft(session, tenant_id, draft["id"])
    assert confirmed["status"] == "confirmed"
    procs = list(
        session.scalars(select(OrderProcess).where(OrderProcess.order_id == order.id).order_by(OrderProcess.id))
    )
    assert procs[0].start_date == by_name["裁断"]["start_date"]
    assert procs[1].end_date == delivery
    session.refresh(order)
    assert order.schedule_status == ScheduleStatus.scheduled
    assert schedule_service.list_drafts(session, tenant_id, status="draft") == []
    # 已排默认不进待排池；显式打开才可见
    assert schedule_service.list_schedule_pool(session, tenant_id) == []
    shown = schedule_service.list_schedule_pool(session, tenant_id, hide_scheduled=False)
    assert len(shown) == 1
    assert shown[0]["order_no"] == "MO1"

def test_confirm_writes_equal_split_assignments(db):
    session, tenant_id, product_id, sp_id, ct_id, cx_id = db
    from app.models import OrderProcessAssignment, Worker

    order = _order(
        session,
        tenant_id,
        product_id,
        ct_id,
        cx_id,
        order_no="MO-ASSIGN",
        qty=10,
        delivery=date(2026, 8, 20),
    )
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("10")
    w1 = Worker(tenant_id=tenant_id, name="甲", mobile="13900000001", is_active=True)
    w2 = Worker(tenant_id=tenant_id, name="乙", mobile="13900000002", is_active=True)
    session.add_all([w1, w2])
    session.commit()

    draft = schedule_service.create_draft(
        session, tenant_id, [order.id], days_per_process=1, auto_assign=False
    )
    cut = next(ln for ln in draft["lines"] if ln["process_name"] == "裁断")
    draft = schedule_service.set_line_assignments(
        session,
        tenant_id,
        draft["id"],
        cut["id"],
        [{"worker_id": w1.id}, {"worker_id": w2.id}],
        equal_split=True,
    )
    cut = next(ln for ln in draft["lines"] if ln["process_name"] == "裁断")
    quotas = sorted(a["quota_qty"] for a in cut["assignments"])
    assert quotas == [5, 5]

    schedule_service.confirm_draft(session, tenant_id, draft["id"], apply_assignments=True)
    cut_op = session.scalar(
        select(OrderProcess).where(
            OrderProcess.order_id == order.id, OrderProcess.process_name == "裁断"
        )
    )
    assigns = list(
        session.scalars(
            select(OrderProcessAssignment).where(
                OrderProcessAssignment.order_process_id == cut_op.id
            )
        ).all()
    )
    assert len(assigns) == 2
    assert sorted(int(a.quota_qty) for a in assigns) == [5, 5]


def test_set_assignments_by_team_expands_members(db):
    session, tenant_id, product_id, sp_id, ct_id, cx_id = db
    from app.models import Worker
    from app.services import team_service

    order = _order(
        session,
        tenant_id,
        product_id,
        ct_id,
        cx_id,
        order_no="MO-TEAM",
        qty=9,
        delivery=date(2026, 8, 20),
    )
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("9")
    leader = Worker(tenant_id=tenant_id, name="组长", mobile="13900000011", is_active=True)
    w2 = Worker(tenant_id=tenant_id, name="组员甲", mobile="13900000012", is_active=True)
    w3 = Worker(tenant_id=tenant_id, name="组员乙", mobile="13900000013", is_active=True)
    session.add_all([leader, w2, w3])
    session.commit()
    team = team_service.create_team(
        session,
        tenant_id,
        name="针车一组",
        leader_worker_id=leader.id,
        worker_ids=[leader.id, w2.id, w3.id],
    )

    draft = schedule_service.create_draft(
        session, tenant_id, [order.id], days_per_process=1, auto_assign=False
    )
    cut = next(ln for ln in draft["lines"] if ln["process_name"] == "裁断")
    draft = schedule_service.set_line_assignments(
        session,
        tenant_id,
        draft["id"],
        cut["id"],
        None,
        team_id=team["id"],
        team_mode="members",
    )
    cut = next(ln for ln in draft["lines"] if ln["process_name"] == "裁断")
    assert cut["team_name"] == "针车一组"
    assert cut["team_assign_mode"] == "members"
    assert len(cut["assignments"]) == 3
    assert sorted(a["quota_qty"] for a in cut["assignments"]) == [3, 3, 3]

    draft = schedule_service.set_line_assignments(
        session,
        tenant_id,
        draft["id"],
        cut["id"],
        None,
        team_id=team["id"],
        team_mode="leader",
    )
    cut = next(ln for ln in draft["lines"] if ln["process_name"] == "裁断")
    assert cut["team_assign_mode"] == "leader"
    assert len(cut["assignments"]) == 1
    assert cut["assignments"][0]["worker_id"] == leader.id
    assert cut["assignments"][0]["quota_qty"] == 9


def test_team_leader_only_blocked_on_group_process(db):
    session, tenant_id, product_id, sp_id, ct_id, cx_id = db
    from app.models import Worker
    from app.services import team_service

    order = _order(
        session,
        tenant_id,
        product_id,
        ct_id,
        cx_id,
        order_no="MO-TEAM-G",
        qty=10,
        delivery=date(2026, 8, 20),
    )
    req = session.scalar(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    )
    req.arrived_qty = Decimal("10")
    leader = Worker(tenant_id=tenant_id, name="成型组长", mobile="13900000021", is_active=True)
    session.add(leader)
    session.commit()
    team = team_service.create_team(
        session, tenant_id, name="成型组", leader_worker_id=leader.id, worker_ids=[leader.id]
    )
    draft = schedule_service.create_draft(
        session, tenant_id, [order.id], days_per_process=1, auto_assign=False
    )
    form = next(ln for ln in draft["lines"] if ln["process_name"] == "成型")
    assert form["process_type"] == "group"
    with pytest.raises(schedule_service.ScheduleError) as ei:
        schedule_service.set_line_assignments(
            session,
            tenant_id,
            draft["id"],
            form["id"],
            None,
            team_id=team["id"],
            team_mode="leader",
        )
    assert ei.value.code == "group_need_members"

def test_confirm_blocked_when_first_kit_missing(db):
    session, tenant_id, product_id, sp_id, ct_id, cx_id = db
    order = _order(
        session,
        tenant_id,
        product_id,
        ct_id,
        cx_id,
        order_no="MO2",
        qty=10,
        # 交期须晚于预计齐套日（8-23）：确认门禁要求开工不早于齐套日
        delivery=date(2026, 8, 30),
    )
    # 不分配 → 首道缺料（面布挂裁断）
    draft = schedule_service.create_draft(session, tenant_id, [order.id], auto_assign=False)
    with pytest.raises(schedule_service.ScheduleError) as ei:
        schedule_service.confirm_draft(session, tenant_id, draft["id"])
    assert ei.value.code == "first_kit_blocked"

    # 排除首道只排成型：面布不算成型料 → 成型齐套空行算齐 → 可确认
    for ln in draft["lines"]:
        if ln["is_first"]:
            schedule_service.patch_draft_line(
                session, tenant_id, draft["id"], ln["id"], included=False
            )
    confirmed = schedule_service.confirm_draft(session, tenant_id, draft["id"])
    assert confirmed["status"] == "confirmed"
    session.refresh(order)
    assert order.schedule_status == ScheduleStatus.partial


def test_calendar_includes_day_meta_and_holidays(db):
    session, tenant_id, product_id, sp_id, ct_id, cx_id = db
    order = _order(
        session,
        tenant_id,
        product_id,
        ct_id,
        cx_id,
        order_no="MO3",
        qty=10,
        delivery=date(2026, 10, 1),  # 国庆当天
    )
    req = session.scalars(
        select(OrderMaterialRequirement).where(OrderMaterialRequirement.order_id == order.id)
    ).one()
    req.arrived_qty = req.required_qty
    session.commit()

    draft = schedule_service.create_draft(session, tenant_id, [order.id], auto_assign=False)
    # 工作日倒排：交期国庆假期，末道应落在假前最近工作日
    ends = {ln["end_date"] for ln in draft["lines"]}
    assert "2026-10-01" not in ends
    schedule_service.confirm_draft(session, tenant_id, draft["id"])

    cal = schedule_service.list_calendar(
        session, tenant_id, date_from=date(2026, 9, 28), date_to=date(2026, 10, 10)
    )
    assert cal["day_meta"]["2026-10-01"]["is_holiday"] is True
    assert cal["day_meta"]["2026-10-01"]["label"] == "国庆"
    assert cal["day_meta"]["2026-10-10"]["is_makeup_workday"] is True
    assert cal["day_meta"]["2026-10-10"]["label"] == "班"
    assert any(
        it["order_no"] == "MO3"
        for day_items in cal["by_date"].values()
        for it in day_items
    )
