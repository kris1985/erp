"""AU-I3 M1：色码排产池 HITL（草案 → 确认落执行单）。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Color,
    ExecutionHeader,
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
    OrderProcess,
    OrderProcessStatus,
)
from app.services.execution_schedule_service import (
    ExecutionScheduleError,
    confirm_draft,
    confirm_header_rush,
    confirm_production,
    discard_draft,
    list_color_pool,
    list_gantt_board,
    preview_header_rush,
    propose_draft,
    select_draft_strategy,
    shift_draft_job,
    shift_issued_header,
    withdraw_issued_header,
)
from app.services.execution_service import list_producible


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
    tenant = Tenant(name="色码排产厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    proc = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("1"),
        per_worker_capacity=Decimal("50"),
        standard_workers=1,
        sort_order=1,
    )
    session.add(proc)
    session.flush()
    product = OwnProduct(
        tenant_id=tenant.id, product_code="SCH-A", is_active=True, trace_enabled=True
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


def _so_item(db, *, order_no, qty, product_id, color_id, size_id, tenant_id):
    so = SalesOrder(
        tenant_id=tenant_id,
        order_no=order_no,
        customer_name="客户",
        status=SalesOrderStatus.confirmed,
        ordered_at=date.today(),
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant_id,
        sales_order_id=so.id,
        own_product_id=product_id,
        color_id=color_id,
        status=SalesOrderLineStatus.pending,
        total_qty=qty,
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


def test_propose_groups_two_sources_confirm_creates_one_execution(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    a = _so_item(
        db,
        order_no="SO-SCH-A",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-SCH-B",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )

    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    assert draft["status"] == "draft"
    assert draft["group_count"] == 1
    assert draft["total_qty"] == 50
    assert not draft.get("rush_impact")
    # 确认前不占可产
    db.refresh(a)
    db.refresh(b)
    assert (a.allocated_qty, b.allocated_qty) == (0, 0)
    pool = list_color_pool(db, tenant_id=tenant.id)
    assert pool[0]["remaining_qty"] == 50
    assert "product_image_url" in pool[0]

    result = confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    assert result["status"] == "confirmed"
    assert result["execution_count"] == 1
    exe = result["executions"][0]
    assert exe["total_qty"] == 50
    assert len(exe["allocations"]) == 2
    ratios = sorted(round(x["ratio"], 6) for x in exe["allocations"])
    assert ratios == [pytest.approx(0.4), pytest.approx(0.6)]

    db.refresh(a)
    db.refresh(b)
    assert (a.allocated_qty, b.allocated_qty) == (30, 20)
    assert db.scalar(select(SpecExecutionOrder).limit(1)) is not None
    assert list_producible(db, tenant_id=tenant.id) == []


def test_confirm_two_sizes_share_one_header(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size40 = db.scalar(select(Size).limit(1))
    size41 = Size(tenant_id=tenant.id, size_value="41", sort_order=1)
    db.add(size41)
    db.commit()
    a = _so_item(
        db,
        order_no="SO-SCH-40",
        qty=30,
        product_id=product.id,
        color_id=color.id,
        size_id=size40.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-SCH-41",
        qty=20,
        product_id=product.id,
        color_id=color.id,
        size_id=size41.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[
            {"sales_order_line_item_id": a.id, "qty": 30},
            {"sales_order_line_item_id": b.id, "qty": 20},
        ],
    )
    assert draft["group_count"] == 2
    result = confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    assert result["execution_count"] == 2
    assert result["header_count"] == 1
    header_ids = {x["header_id"] for x in result["executions"]}
    assert len(header_ids) == 1
    header = db.get(ExecutionHeader, result["executions"][0]["header_id"])
    assert header is not None
    assert header.total_qty == 50
    lines = list(
        db.scalars(
            select(SpecExecutionOrder).where(SpecExecutionOrder.header_id == header.id)
        ).all()
    )
    assert len(lines) == 2


def test_propose_plan_has_windows_without_execution(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-PLAN",
        qty=12,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 12}],
    )
    assert draft["status"] == "draft"
    assert draft["proposals"]
    assert {p["strategy"] for p in draft["proposals"]} >= {"delivery_first", "capacity_first"}
    assert draft["jobs"]
    assert draft["jobs"][0]["windows"]
    assert all(w.get("start_date") and w.get("end_date") for w in draft["jobs"][0]["windows"])
    assert db.scalar(select(ExecutionHeader.id).limit(1)) is None
    db.refresh(item)
    assert int(item.allocated_qty or 0) == 0


def test_select_strategy_does_not_create_execution(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-STRAT",
        qty=8,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 8}],
    )
    nxt = "capacity_first" if draft["strategy"] != "capacity_first" else "delivery_first"
    out = select_draft_strategy(
        db, tenant_id=tenant.id, draft_id=draft["id"], strategy=nxt
    )
    assert out["strategy"] == nxt
    assert out["status"] == "draft"
    assert db.scalar(select(ExecutionHeader.id).limit(1)) is None


def test_confirm_production_writes_process_dates(db):
    from app.services.material_service import list_header_processes

    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-ONCE",
        qty=12,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    result = confirm_production(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 12}],
    )
    assert result["status"] == "confirmed"
    assert result["header_count"] == 1
    assert result["headers"]
    hid = result["headers"][0]["id"]
    procs = list_header_processes(db, tenant.id, hid)
    assert procs
    assert all(p.start_date and p.end_date for p in procs)


def test_propose_over_remaining_rejected(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-OVR",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    try:
        propose_draft(
            db,
            tenant_id=tenant.id,
            selections=[{"sales_order_line_item_id": item.id, "qty": 11}],
        )
        assert False
    except ExecutionScheduleError as e:
        assert e.code == "over_remaining"


def test_discard_then_confirm_rejected(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-DISC",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    discard_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    try:
        confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
        assert False
    except ExecutionScheduleError as e:
        assert e.code == "invalid_status"


def test_confirm_non_draft_rejected(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-CFM",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    try:
        confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
        assert False
    except ExecutionScheduleError as e:
        assert e.code == "invalid_status"


def test_gantt_excludes_unconfirmed_draft(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-G0",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    board = list_gantt_board(db, tenant.id)
    assert board["workdays"]
    assert board["issued"] == []


def test_gantt_days_follow_calendar_settings(db):
    from app.services import schedule_settings

    tenant = db.scalar(select(Tenant).limit(1))
    saturday = date(2026, 8, 15)
    monday = date(2026, 8, 17)
    board = list_gantt_board(db, tenant.id, date_from=saturday, date_to=monday)
    by = {d["date"]: d for d in board["days"]}
    assert set(by) == {"2026-08-15", "2026-08-16", "2026-08-17"}
    assert by["2026-08-15"]["workday"] is False
    assert by["2026-08-15"]["is_weekend"] is True
    assert by["2026-08-17"]["workday"] is True
    assert [d["date"] for d in board["workdays"]] == ["2026-08-17"]

    schedule_settings.save_schedule_patch(
        db, tenant.id, {"allow_schedule_on_non_workdays": True}
    )
    board = list_gantt_board(db, tenant.id, date_from=saturday, date_to=monday)
    by = {d["date"]: d for d in board["days"]}
    assert by["2026-08-15"]["workday"] is True
    assert len(board["workdays"]) == 3

    schedule_settings.save_schedule_patch(
        db,
        tenant.id,
        {
            "allow_schedule_on_non_workdays": True,
            "schedule_blackout_dates": [{"date": "2026-08-15", "note": "厂休"}],
        },
    )
    board = list_gantt_board(db, tenant.id, date_from=saturday, date_to=monday)
    by = {d["date"]: d for d in board["days"]}
    assert by["2026-08-15"]["workday"] is False
    assert by["2026-08-15"]["is_blackout"] is True
    assert by["2026-08-15"]["label"] == "停工"


def test_gantt_issued_after_confirm(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-G1",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    board = list_gantt_board(db, tenant.id)
    assert len(board["issued"]) == 1
    row = board["issued"][0]
    assert row["kind"] == "issued"
    assert str(row["key"]).startswith("h:")
    assert row["header_id"]
    assert row["windows"]
    assert all(w.get("start_date") and w.get("end_date") for w in row["windows"])
    assert row["status"] == "confirmed"
    assert row["locked"] is False
    assert all("plan_qty" in w and "completed_qty" in w for w in row["windows"])
    assert all(int(w.get("completed_qty") or 0) == 0 for w in row["windows"])


def test_gantt_process_progress_on_issued(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-GPROG",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    hid = list_gantt_board(db, tenant.id)["issued"][0]["header_id"]
    proc = db.scalar(
        select(OrderProcess).where(
            OrderProcess.tenant_id == tenant.id,
            OrderProcess.header_id == hid,
        )
    )
    assert proc is not None
    proc.completed_qty = int(proc.plan_qty or 10)
    proc.status = OrderProcessStatus.completed
    db.flush()
    board = list_gantt_board(db, tenant.id)
    done = [w for w in board["issued"][0]["windows"] if w["process_id"] == proc.process_id]
    assert done
    assert int(done[0]["completed_qty"]) == int(proc.plan_qty)
    assert done[0]["status"] == "completed"


def test_shift_cut_start_does_not_create_execution(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-SH0",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    job = draft["jobs"][0]
    old = job["windows"][0]["start_date"]
    target = date.fromisoformat(str(old)[:10]) + timedelta(days=10)
    out = shift_draft_job(
        db,
        tenant_id=tenant.id,
        draft_id=draft["id"],
        job_key=job["key"],
        cut_start=target,
    )
    nxt = out["jobs"][0]["windows"][0]["start_date"]
    assert nxt > old
    assert out["overrides"][job["key"]]["cut_start"]
    assert db.scalar(select(ExecutionHeader.id).limit(1)) is None
    assert int(item.allocated_qty or 0) == 0


def test_shift_then_confirm_writes_moved_dates(db):
    from app.services.material_service import list_header_processes

    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-SH1",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    job = draft["jobs"][0]
    old = job["windows"][0]["start_date"]
    target = date.fromisoformat(str(old)[:10]) + timedelta(days=10)
    shifted = shift_draft_job(
        db,
        tenant_id=tenant.id,
        draft_id=draft["id"],
        job_key=job["key"],
        cut_start=target,
    )
    want = shifted["jobs"][0]["windows"][0]["start_date"]
    result = confirm_draft(db, tenant_id=tenant.id, draft_id=draft["id"])
    hid = result["headers"][0]["id"]
    procs = list_header_processes(db, tenant.id, hid)
    assert procs
    assert procs[0].start_date.isoformat() == want
    assert want != old


def test_strategy_switch_clears_shift(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SCH-SH2",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    draft = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
    )
    job = draft["jobs"][0]
    old = job["windows"][0]["start_date"]
    target = date.fromisoformat(str(old)[:10]) + timedelta(days=10)
    shift_draft_job(
        db,
        tenant_id=tenant.id,
        draft_id=draft["id"],
        job_key=job["key"],
        cut_start=target,
    )
    nxt = "capacity_first" if draft["strategy"] != "capacity_first" else "delivery_first"
    out = select_draft_strategy(db, tenant_id=tenant.id, draft_id=draft["id"], strategy=nxt)
    assert out["overrides"] == {}
    assert db.scalar(select(ExecutionHeader.id).limit(1)) is None


def test_rush_draft_previews_uncut_and_confirm_shifts(db):
    from app.services.material_service import list_header_processes

    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    black = db.scalar(select(Color).limit(1))
    white = Color(tenant_id=tenant.id, name="白", code="WH")
    db.add(white)
    db.flush()
    size = db.scalar(select(Size).limit(1))
    a = _so_item(
        db,
        order_no="SO-RUSH-A",
        qty=10,
        product_id=product.id,
        color_id=black.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-RUSH-B",
        qty=10,
        product_id=product.id,
        color_id=white.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    first = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": a.id, "qty": 10}],
    )
    confirmed = confirm_draft(db, tenant_id=tenant.id, draft_id=first["id"])
    hid = confirmed["headers"][0]["id"]
    old = list_header_processes(db, tenant.id, hid)[0].start_date
    rush = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": b.id, "qty": 10}],
        is_rush=True,
    )
    assert rush["is_rush"] is True
    impact = rush["rush_impact"]
    assert impact
    assert {x["header_id"] for x in impact["impacts"]} == {hid}
    confirm_draft(db, tenant_id=tenant.id, draft_id=rush["id"])
    nxt = list_header_processes(db, tenant.id, hid)[0].start_date
    assert nxt > old


def test_rush_does_not_move_cut_header(db):
    from app.services.material_service import list_header_processes

    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    black = db.scalar(select(Color).limit(1))
    white = Color(tenant_id=tenant.id, name="米", code="BE")
    db.add(white)
    db.flush()
    size = db.scalar(select(Size).limit(1))
    a = _so_item(
        db,
        order_no="SO-RUSH-C",
        qty=10,
        product_id=product.id,
        color_id=black.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-RUSH-D",
        qty=10,
        product_id=product.id,
        color_id=white.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    first = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": a.id, "qty": 10}],
    )
    confirmed = confirm_draft(db, tenant_id=tenant.id, draft_id=first["id"])
    hid = confirmed["headers"][0]["id"]
    header = db.get(ExecutionHeader, hid)
    header.status = SpecExecutionStatus.cut
    db.commit()
    old = list_header_processes(db, tenant.id, hid)[0].start_date
    rush = propose_draft(
        db,
        tenant_id=tenant.id,
        selections=[{"sales_order_line_item_id": b.id, "qty": 10}],
        is_rush=True,
    )
    assert {x["header_id"] for x in rush["rush_impact"]["frozen"]} == {hid}
    assert rush["rush_impact"]["impacts"] == []
    confirm_draft(db, tenant_id=tenant.id, draft_id=rush["id"])
    nxt = list_header_processes(db, tenant.id, hid)[0].start_date
    assert nxt == old


def test_header_rush_confirm_shifts_uncut_peer(db):
    from app.services.material_service import list_header_processes

    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    black = db.scalar(select(Color).limit(1))
    white = Color(tenant_id=tenant.id, name="红", code="RD")
    db.add(white)
    db.flush()
    size = db.scalar(select(Size).limit(1))
    a = _so_item(
        db,
        order_no="SO-RUSH-E",
        qty=10,
        product_id=product.id,
        color_id=black.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    b = _so_item(
        db,
        order_no="SO-RUSH-F",
        qty=10,
        product_id=product.id,
        color_id=white.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    ha = confirm_draft(
        db,
        tenant_id=tenant.id,
        draft_id=propose_draft(
            db,
            tenant_id=tenant.id,
            selections=[{"sales_order_line_item_id": a.id, "qty": 10}],
        )["id"],
    )["headers"][0]["id"]
    hb = confirm_draft(
        db,
        tenant_id=tenant.id,
        draft_id=propose_draft(
            db,
            tenant_id=tenant.id,
            selections=[{"sales_order_line_item_id": b.id, "qty": 10}],
        )["id"],
    )["headers"][0]["id"]
    old_a = list_header_processes(db, tenant.id, ha)[0].start_date
    old_b = list_header_processes(db, tenant.id, hb)[0].start_date
    sim = preview_header_rush(db, tenant_id=tenant.id, header_id=hb, push_workdays=3)
    assert {x["header_id"] for x in sim["impacts"]} == {ha}
    confirm_header_rush(db, tenant_id=tenant.id, header_id=hb, push_workdays=3)
    nxt = list_header_processes(db, tenant.id, ha)[0].start_date
    assert nxt > old_a
    assert list_header_processes(db, tenant.id, hb)[0].start_date == old_b
    peer = db.scalar(select(SpecExecutionOrder).where(SpecExecutionOrder.header_id == hb))
    assert peer.is_rush is True


def test_header_rush_rejects_cut(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-RUSH-G",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    hid = confirm_draft(
        db,
        tenant_id=tenant.id,
        draft_id=propose_draft(
            db,
            tenant_id=tenant.id,
            selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
        )["id"],
    )["headers"][0]["id"]
    header = db.get(ExecutionHeader, hid)
    header.status = SpecExecutionStatus.cut
    db.commit()
    with pytest.raises(ExecutionScheduleError) as ei:
        preview_header_rush(db, tenant_id=tenant.id, header_id=hid)
    assert ei.value.code == "header_started"


def test_shift_issued_header_moves_windows(db):
    from app.services.material_service import list_header_processes

    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SHIFT-H",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    hid = confirm_draft(
        db,
        tenant_id=tenant.id,
        draft_id=propose_draft(
            db,
            tenant_id=tenant.id,
            selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
        )["id"],
    )["headers"][0]["id"]
    old = list_header_processes(db, tenant.id, hid)[0].start_date
    target = old + timedelta(days=10)
    out = shift_issued_header(db, tenant_id=tenant.id, header_id=hid, cut_start=target)
    nxt = list_header_processes(db, tenant.id, hid)[0].start_date
    assert nxt > old
    assert out["cut_start"] == nxt.isoformat()


def test_shift_issued_header_rejects_cut(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-SHIFT-CUT",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    hid = confirm_draft(
        db,
        tenant_id=tenant.id,
        draft_id=propose_draft(
            db,
            tenant_id=tenant.id,
            selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
        )["id"],
    )["headers"][0]["id"]
    header = db.get(ExecutionHeader, hid)
    header.status = SpecExecutionStatus.cut
    db.commit()
    with pytest.raises(ExecutionScheduleError) as ei:
        shift_issued_header(db, tenant_id=tenant.id, header_id=hid, cut_start=date.today())
    assert ei.value.code == "header_started"


def test_withdraw_issued_header_returns_to_pool(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    item = _so_item(
        db,
        order_no="SO-WD-H",
        qty=10,
        product_id=product.id,
        color_id=color.id,
        size_id=size.id,
        tenant_id=tenant.id,
    )
    hid = confirm_draft(
        db,
        tenant_id=tenant.id,
        draft_id=propose_draft(
            db,
            tenant_id=tenant.id,
            selections=[{"sales_order_line_item_id": item.id, "qty": 10}],
        )["id"],
    )["headers"][0]["id"]
    db.refresh(item)
    assert int(item.allocated_qty or 0) == 10
    withdraw_issued_header(db, tenant_id=tenant.id, header_id=hid)
    db.refresh(item)
    assert int(item.allocated_qty or 0) == 0
    header = db.get(ExecutionHeader, hid)
    assert header.status == SpecExecutionStatus.cancelled
    pool = list_producible(db, tenant_id=tenant.id)
    assert any(int(b.get("remaining_qty") or 0) >= 10 for b in pool)

