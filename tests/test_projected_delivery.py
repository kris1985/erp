"""预计交货日期：工序段报工节拍正排；没有正常报工日则为空。"""

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
    OwnProductMaterial,
    Partner,
    ProcessDefinition,
    ProcessSegment,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    ReportType,
    SalesOrder,
    SalesOrderLine,
    SalesOrderLineItem,
    SalesOrderLineStatus,
    SalesOrderStatus,
    SharedMaterialStock,
    Size,
    SpecExecutionStatus,
    SupplierProduct,
    Tenant,
    WorkLog,
    WorkLogStatus,
)
from app.services import inventory_settings
from app.services.execution_service import (
    apply_projected_finish,
    create_execution_from_sales_line,
    header_out,
    project_finish_by_process_capacity,
    project_header_finish,
    segment_pace_for_headers,
    segment_report_pace,
)
from app.services import attendance_rules as ar
from app.services.material_service import get_header_kit, header_kit_summaries


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
    tenant = Tenant(name="预计交期厂")
    session.add(tenant)
    session.flush()
    session.add(Color(tenant_id=tenant.id, name="黑", code="BK"))
    session.add(Size(tenant_id=tenant.id, size_value="40", sort_order=0))
    partner = Partner(tenant_id=tenant.id, name="料商", is_supplier=True, is_active=True)
    session.add(partner)
    cut = ProcessDefinition(
        tenant_id=tenant.id,
        name="裁断",
        code="CD",
        default_price=Decimal("1"),
        per_worker_capacity=Decimal("100"),
        standard_workers=1,
        sort_order=1,
    )
    form = ProcessDefinition(
        tenant_id=tenant.id,
        name="成型",
        code="CX",
        default_price=Decimal("1"),
        per_worker_capacity=Decimal("100"),
        standard_workers=1,
        sort_order=2,
    )
    session.add_all([cut, form])
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="PD-1", is_active=True)
    session.add(product)
    session.flush()
    for i, proc in enumerate((cut, form)):
        session.add(
            OwnProductLabor(
                tenant_id=tenant.id,
                own_product_id=product.id,
                process_id=proc.id,
                process_name=proc.name,
                unit_price=Decimal("1"),
                sort_order=i,
            )
        )
    mat = SupplierProduct(
        tenant_id=tenant.id,
        product_code="MAT-1",
        name="面料",
        partner_id=partner.id,
        unit_price=Decimal("1"),
        is_active=True,
    )
    session.add(mat)
    session.flush()
    session.add(
        OwnProductMaterial(
            tenant_id=tenant.id,
            own_product_id=product.id,
            supplier_product_id=mat.id,
            qty=Decimal("1"),
            unit_price=Decimal("1"),
            line_total=Decimal("1"),
            sort_order=0,
        )
    )
    session.commit()
    inventory_settings.save_inventory_patch(
        session,
        tenant.id,
        {
            "shared_pool": True,
            "allocate_ui": True,
            "stock_docs": True,
            "kit_include_unallocated_pool": True,
        },
    )
    yield session
    session.close()


def test_attendance_workday_helpers():
    weekly = ar.merge_attendance_rules({"weekly_rest_days": [6, 7]})
    assert weekly["rest_pay_salary"] is True
    assert weekly["rest_pay_meal"] is False
    assert weekly["rest_pay_housing"] is False
    assert weekly["rest_pay_other"] is False
    assert ar.is_fixed_rest_day(date(2026, 3, 7), weekly)
    assert not ar.is_fixed_rest_day(date(2026, 3, 2), weekly)
    unpaid = ar.merge_attendance_rules({"rest_pay_salary": False, "rest_pay_meal": True})
    assert unpaid["rest_pay_salary"] is False
    assert unpaid["rest_pay_meal"] is True
    assert unpaid["rest_pay_housing"] is False
    assert unpaid["rest_pay_other"] is False
    assert ar.is_attendance_workday(date(2026, 3, 2), weekly)
    assert not ar.is_attendance_workday(date(2026, 3, 7), weekly)
    monthly = ar.merge_attendance_rules(
        {"rest_day_mode": "monthly", "monthly_rest_days": [15], "weekly_rest_days": []}
    )
    assert ar.is_attendance_workday(date(2026, 3, 14), monthly)
    assert not ar.is_attendance_workday(date(2026, 3, 15), monthly)
    assert ar.is_attendance_workday(date(2026, 3, 7), monthly)
    ranged = ar.merge_attendance_rules(
        {
            "weekly_rest_days": [6, 7],
            "designated_rest_ranges": [
                {"start": "2026-03-03", "end": "2026-03-04"},
                {"start": "2026-03-10", "end": "2026-03-10"},
                {"start": "2026-03-20", "end": "2026-03-01"},
            ],
        }
    )
    assert ranged["designated_rest_ranges"] == [
        {
            "start": "2026-03-03 00:00",
            "end": "2026-03-04 23:59",
            "pay_salary": True,
            "pay_meal": False,
            "pay_housing": False,
            "pay_other": False,
        },
        {
            "start": "2026-03-10 00:00",
            "end": "2026-03-10 23:59",
            "pay_salary": True,
            "pay_meal": False,
            "pay_housing": False,
            "pay_other": False,
        },
    ]
    paid = ar.designated_rest_pay(date(2026, 3, 3), ranged)
    assert paid == {"pay_salary": True, "pay_meal": False, "pay_housing": False, "pay_other": False}
    assert ar.designated_rest_pay(date(2026, 3, 5), ranged) is None
    assert not ar.is_attendance_workday(date(2026, 3, 3), ranged)
    assert not ar.is_attendance_workday(date(2026, 3, 4), ranged)
    assert ar.is_attendance_workday(date(2026, 3, 5), ranged)
    assert not ar.is_attendance_workday(date(2026, 3, 10), ranged)
    partial = ar.merge_attendance_rules(
        {
            "weekly_rest_days": [],
            "work_periods": [
                {"start": "08:00", "end": "12:00"},
                {"start": "13:30", "end": "17:30"},
            ],
            "designated_rest_ranges": [
                {"start": "2026-03-03 10:15", "end": "2026-03-03 11:00"},
            ],
        }
    )
    assert ar.is_attendance_workday(date(2026, 3, 3), partial)


def _header(db, *, stocked: bool, qty: int = 100):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    color = db.scalar(select(Color).limit(1))
    size = db.scalar(select(Size).limit(1))
    partner = db.scalar(select(Partner).limit(1))
    mat = db.scalar(select(SupplierProduct).limit(1))
    if stocked:
        db.add(
            SharedMaterialStock(
                tenant_id=tenant.id,
                supplier_product_id=mat.id,
                size_id=None,
                qty=Decimal("1000"),
            )
        )
        db.flush()
    so = SalesOrder(
        tenant_id=tenant.id,
        order_no="SO-PD",
        customer_name="客户",
        ordered_at=date(2026, 3, 2),
        status=SalesOrderStatus.draft,
    )
    db.add(so)
    db.flush()
    line = SalesOrderLine(
        tenant_id=tenant.id,
        sales_order_id=so.id,
        own_product_id=product.id,
        color_id=color.id,
        total_qty=qty,
        delivery_date=date(2026, 4, 1),
        status=SalesOrderLineStatus.pending,
        sort_order=0,
    )
    db.add(line)
    db.flush()
    db.add(
        SalesOrderLineItem(
            tenant_id=tenant.id,
            sales_order_line_id=line.id,
            color_id=color.id,
            size_id=size.id,
            qty=qty,
            allocated_qty=0,
            produced_qty=0,
        )
    )
    db.flush()
    header = create_execution_from_sales_line(
        db, tenant_id=tenant.id, sales_order=so, line=line, created_by=1, commit=True
    )
    return tenant, partner, mat, header


def _expected_finish(start: date, process_days: list[int], rules=None) -> date:
    cursor = ar.next_attendance_workday(start, rules)
    finish = cursor
    for days in process_days:
        _s, finish = ar.attendance_span_starting(cursor, days, rules)
        cursor = ar.next_attendance_workday(finish + timedelta(days=1), rules)
    return finish


def _pace(plan, route, logs, sorts=None):
    return segment_report_pace(
        plan_qty=plan,
        route_segment_ids=route,
        segment_sorts=sorts or {1: 1, 2: 2, 3: 3},
        logs=logs,
    )


def test_daily_min_sums_same_day_and_ignores_silent_segment():
    # 最后工序段没报工时，前面的裁断、成型不产生节拍
    fact = _pace(
        300,
        [1, 2, 3],
        [
            (1, date(2026, 3, 2), 30, 0, 0, "normal"),
            (1, date(2026, 3, 2), 70, 0, 0, "group"),
            (2, date(2026, 3, 2), 90, 0, 0, "supplement"),
        ],
    )
    assert fact["pace"] is None
    assert fact["completed"] == 0
    assert fact["remaining"] == 300


def test_utc_created_at_buckets_on_shanghai_day():
    # 15:00 UTC 仍是上海 3月1日；16:30 UTC 已是上海 3月2日，两天分开取中位数
    fact = _pace(
        200,
        [1],
        [
            (1, datetime(2026, 3, 1, 15, 0), 100, 0, 0, "normal"),
            (1, datetime(2026, 3, 1, 16, 30), 50, 0, 0, "normal"),
        ],
    )
    assert fact["pace"] == Decimal("75")
    assert fact["completed"] == 150
    assert fact["remaining"] == 50


def test_tail_and_final_inspection_days_leave_the_sample():
    sorts = {1: 1, 2: 2}
    # 第二天两段都收到计划，是尾货日，不进中位数
    closed = _pace(
        100,
        [1, 2],
        [
            (1, date(2026, 3, 2), 80, 0, 0, "normal"),
            (2, date(2026, 3, 2), 80, 0, 0, "normal"),
            (1, date(2026, 3, 3), 20, 0, 0, "tail"),
            (2, date(2026, 3, 3), 20, 0, 0, "normal"),
        ],
        sorts,
    )
    assert closed["pace"] == Decimal("80")
    assert closed["completed"] == 100
    assert closed["remaining"] == 0

    # 最后一段是当天最小，且有报废，这一天不进样本；报废要补做
    inspected = _pace(
        200,
        [1, 2],
        [
            (1, date(2026, 3, 2), 100, 0, 0, "normal"),
            (2, date(2026, 3, 2), 30, 2, 0, "normal"),
            (1, date(2026, 3, 3), 100, 0, 0, "normal"),
            (2, date(2026, 3, 3), 100, 0, 0, "normal"),
        ],
        sorts,
    )
    assert inspected["pace"] == Decimal("100")
    assert inspected["remake"] == 2
    assert inspected["completed"] == 130
    assert inspected["remaining"] == 72

    # 最小数同时有正常段时，不因为最后一段也有报废就把整天丢掉
    tied = _pace(
        200,
        [1, 2],
        [
            (1, date(2026, 3, 2), 50, 0, 0, "normal"),
            (2, date(2026, 3, 2), 50, 1, 0, "normal"),
        ],
        sorts,
    )
    assert tied["pace"] == Decimal("50")
    assert tied["remake"] == 1


def test_only_closeout_day_still_sets_a_pace():
    # 当天做完整单，没有更早的正常日；这一天仍要留下节拍，后面的单才排得出日期
    finished = _pace(
        210,
        [1, 2, 3],
        [
            (1, date(2026, 10, 27), 210, 0, 0, "normal"),
            (2, date(2026, 10, 27), 840, 0, 0, "normal"),
            (3, date(2026, 10, 27), 2100, 0, 0, "normal"),
        ],
        {1: 1, 2: 2, 3: 3},
    )
    assert finished["pace"] == Decimal("210")
    assert finished["completed"] == 210
    assert finished["remaining"] == 0

    # 只报了第一段，最后工序段没报工，不产生节拍
    cutting_only = _pace(
        630,
        [1, 2, 3],
        [(1, date(2026, 10, 28), 630, 0, 0, "normal")],
        {1: 1, 2: 2, 3: 3},
    )
    assert cutting_only["pace"] is None
    assert cutting_only["completed"] == 0
    assert cutting_only["remaining"] == 630

    # 最后工序段各工序两人都报 105，节拍是 210；前面工序段的超额报工不参与
    last_segment = _pace(
        210,
        [1, 2, 3],
        [
            (1, date(2026, 10, 27), 210, 0, 0, "normal", 10),
            (2, date(2026, 10, 27), 840, 0, 0, "normal", 20),
            (3, date(2026, 10, 28), 105, 0, 0, "normal", 41),
            (3, date(2026, 10, 28), 105, 0, 0, "normal", 41),
            (3, date(2026, 10, 28), 105, 0, 0, "normal", 51),
            (3, date(2026, 10, 28), 105, 0, 0, "normal", 51),
        ],
        {1: 1, 2: 2, 3: 3},
    )
    assert last_segment["pace"] == Decimal("210")
    assert last_segment["remaining"] == 0

    # 裁断 210 与后段超额报工被午夜拆成两天时，节拍不能超过订单 210
    split = _pace(
        210,
        [1, 2, 3],
        [
            (1, date(2026, 10, 27), 210, 0, 0, "normal"),
            (2, date(2026, 10, 28), 840, 0, 0, "normal"),
            (3, date(2026, 10, 28), 2100, 0, 0, "normal"),
        ],
        {1: 1, 2: 2, 3: 3},
    )
    assert split["pace"] == Decimal("210")
    assert split["remaining"] == 0


def test_rework_adds_to_remaining_and_does_not_set_the_pace():
    fact = _pace(
        100,
        [1, 2],
        [
            (1, date(2026, 3, 2), 80, 0, 0, "normal"),
            (2, date(2026, 3, 2), 0, 0, 10, "rework"),
            (1, date(2026, 3, 2), 50, 0, 0, "rework"),
        ],
        {1: 1, 2: 2},
    )
    assert fact["pace"] is None
    assert fact["remake"] == 10
    assert fact["completed"] == 0
    assert fact["remaining"] == 110


def test_median_averages_two_middle_days():
    one_segment = [
        (1, date(2026, 3, 2), 40, 0, 0, "normal"),
        (1, date(2026, 3, 3), 80, 0, 0, "normal"),
        (1, date(2026, 3, 4), 100, 0, 0, "normal"),
        (1, date(2026, 3, 5), 120, 0, 0, "normal"),
    ]
    assert _pace(500, [1], one_segment, {1: 1})["pace"] == Decimal("90")
    assert _pace(500, [1], one_segment[:1], {1: 1})["pace"] == Decimal("40")
    assert _pace(500, [1], one_segment[:3], {1: 1})["pace"] == Decimal("80")
    half = _pace(
        500,
        [1],
        [
            (1, date(2026, 3, 2), 80, 0, 0, "normal"),
            (1, date(2026, 3, 3), 81, 0, 0, "normal"),
        ],
        {1: 1},
    )
    assert half["pace"] == Decimal("81")
    assert _pace(100, [1], [], {1: 1})["pace"] is None


def test_without_reports_has_no_finish(db):
    _tenant, _partner, _mat, header = _header(db, stocked=True)
    as_of = date(2026, 3, 2)
    out = header_out(db, header)
    assert out["kit"]["kit_ok"] is True
    finish = project_header_finish(
        out["process_progress"],
        out["kit"],
        status=str(header.status.value),
        as_of=as_of,
        remaining_pairs=100,
    )
    assert finish is None
    assert out["projected_finish"] is None
    assert any(item["code"] == "awaiting_report" for item in out["risk"]["reasons"])


def test_shortage_without_pace_does_not_invent_a_date(db):
    tenant, partner, mat, header = _header(db, stocked=False)
    as_of = date(2026, 3, 2)
    eta = date(2026, 3, 16)
    po = PurchaseOrder(
        tenant_id=tenant.id,
        po_no="PO-ETA",
        partner_id=partner.id,
        status=PurchaseOrderStatus.ordered,
        expected_date=eta,
        ordered_at=datetime(2026, 3, 1),
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            tenant_id=tenant.id,
            purchase_order_id=po.id,
            supplier_product_id=mat.id,
            qty=Decimal("100"),
            received_qty=Decimal("0"),
            unit_price=Decimal("1"),
        )
    )
    db.commit()

    kit = get_header_kit(db, tenant.id, header.id)
    assert kit["kit_ok"] is False
    assert kit["kit_ready_date"] == eta.isoformat()
    batch = header_kit_summaries(db, tenant.id, [header.id])
    assert batch[header.id]["kit_ready_date"] == eta.isoformat()
    finish = project_header_finish(
        [],
        {"kit_ok": False, "empty_bom": False, "kit_ready_date": kit["kit_ready_date"]},
        status="confirmed",
        as_of=as_of,
        remaining_pairs=100,
    )
    assert finish is None


def test_in_progress_shortage_cannot_finish_before_kit_ready():
    as_of = date(2026, 3, 2)
    kit_ready = date(2026, 3, 20)
    production_finish = _expected_finish(as_of, [1])
    finish = project_header_finish(
        [],
        {"kit_ok": False, "empty_bom": False, "kit_ready_date": kit_ready.isoformat()},
        status="in_progress",
        as_of=as_of,
        pace=Decimal("100"),
        remaining_pairs=100,
    )
    assert finish == ar.next_attendance_workday(max(production_finish, kit_ready))


def test_unstarted_shortage_starts_after_kit_ready():
    as_of = date(2026, 3, 2)
    eta = date(2026, 3, 16)
    finish = project_header_finish(
        [],
        {"kit_ok": False, "empty_bom": False, "kit_ready_date": eta.isoformat()},
        status="confirmed",
        as_of=as_of,
        pace=Decimal("100"),
        remaining_pairs=200,
    )
    assert finish == _expected_finish(eta, [2])


def test_uses_attendance_rest_days_not_national_weekend():
    rules = ar.merge_attendance_rules({"weekly_rest_days": [7]})
    as_of = date(2026, 3, 6)  # 周五，只休周日
    finish = project_header_finish(
        [],
        {"kit_ok": True, "empty_bom": False},
        status="confirmed",
        as_of=as_of,
        attendance_rules=rules,
        pace=Decimal("100"),
        remaining_pairs=200,
    )
    assert finish == date(2026, 3, 7)


def test_exception_dates_do_not_change_workdays():
    holiday_rules = ar.merge_attendance_rules(
        {
            "weekly_rest_days": [6, 7],
            "special_holidays": [{"start": "2026-03-03 00:00", "end": "2026-03-04 00:00"}],
        }
    )
    assert holiday_rules["special_holidays"] == []
    as_of = date(2026, 3, 2)
    finish = project_header_finish(
        [],
        {"kit_ok": True, "empty_bom": False},
        status="confirmed",
        as_of=as_of,
        attendance_rules=holiday_rules,
        pace=Decimal("100"),
        remaining_pairs=200,
    )
    assert finish == date(2026, 3, 3)

    overtime_rules = ar.merge_attendance_rules(
        {
            "weekly_rest_days": [6, 7],
            "special_overtimes": [{"start": "2026-03-08 08:00", "end": "2026-03-08 17:30"}],
        }
    )
    assert overtime_rules["special_overtimes"] == []
    weekend = project_header_finish(
        [],
        {"kit_ok": True, "empty_bom": False},
        status="confirmed",
        as_of=date(2026, 3, 6),
        attendance_rules=overtime_rules,
        pace=Decimal("100"),
        remaining_pairs=200,
    )
    assert weekend == date(2026, 3, 9)


def test_business_report_still_uses_process_capacity():
    as_of = date(2026, 3, 2)
    finish = project_finish_by_process_capacity(
        [
            {"process_id": 1, "plan_qty": 100, "completed_qty": 0, "is_done": False},
            {"process_id": 2, "plan_qty": 100, "completed_qty": 0, "is_done": False},
        ],
        {"kit_ok": True, "empty_bom": False},
        status="confirmed",
        cap_map={1: (Decimal("100"), 1), 2: (Decimal("100"), 1)},
        as_of=as_of,
    )
    assert finish == _expected_finish(as_of, [1, 1])


def test_header_out_projects_from_segment_reports(db):
    tenant, _partner, _mat, header = _header(db, stocked=True, qty=300)
    product = db.scalar(select(OwnProduct).limit(1))
    cut_seg = ProcessSegment(tenant_id=tenant.id, name="裁断段", code="CUT", sort_order=1)
    form_seg = ProcessSegment(tenant_id=tenant.id, name="成型段", code="FORM", sort_order=2)
    db.add_all([cut_seg, form_seg])
    db.flush()
    procs = list(
        db.scalars(
            select(OrderProcess).where(OrderProcess.header_id == header.id).order_by(OrderProcess.id)
        ).all()
    )
    assert len(procs) >= 2
    procs[0].segment_id = cut_seg.id
    procs[1].segment_id = form_seg.id
    db.flush()

    def add_log(segment, proc, day, qualified, *, status=WorkLogStatus.valid, report_type=ReportType.normal, defect=0, rework=0, log_header=header):
        db.add(
            WorkLog(
                tenant_id=tenant.id,
                worker_id=1,
                header_id=log_header.id,
                order_process_id=proc.id,
                own_product_id=product.id,
                process_id=proc.process_id,
                segment_id=segment.id if segment is not None else None,
                report_type=report_type,
                qualified_qty=Decimal(qualified),
                defect_qty=Decimal(defect),
                rework_qty=rework,
                status=status,
                created_at=datetime(day.year, day.month, day.day, 4, 0),
            )
        )

    add_log(cut_seg, procs[0], date(2026, 3, 2), 100)
    add_log(form_seg, procs[1], date(2026, 3, 2), 80)
    add_log(cut_seg, procs[0], date(2026, 3, 3), 100)
    add_log(form_seg, procs[1], date(2026, 3, 3), 100)
    add_log(cut_seg, procs[0], date(2026, 3, 4), 40)
    add_log(form_seg, procs[1], date(2026, 3, 4), 120)
    add_log(cut_seg, procs[0], date(2026, 3, 5), 1, status=WorkLogStatus.void)
    add_log(form_seg, procs[1], date(2026, 3, 5), 1, status=WorkLogStatus.void)
    child = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-RECUT",
        own_product_id=product.id,
        total_qty=20,
        parent_header_id=header.id,
        status=SpecExecutionStatus.in_progress,
    )
    db.add(child)
    db.flush()
    add_log(cut_seg, procs[0], date(2026, 3, 6), 50, log_header=child)
    add_log(form_seg, procs[1], date(2026, 3, 6), 50, log_header=child)
    add_log(None, procs[0], date(2026, 3, 6), 0, rework=4, report_type=ReportType.rework)
    db.commit()

    fact = segment_pace_for_headers(db, tenant.id, [header])[header.id]
    # 节拍只取最后工序段成型：80、100、50，收尾的 120 不进样本，中位数 80
    assert fact["pace"] == Decimal("80")
    assert fact["completed"] == 290
    assert fact["remake"] == 4
    assert fact["remaining"] == 14
    out = header_out(db, header)
    rules = ar.get_attendance_rules_by_tenant_id(db, tenant.id)
    finish = project_header_finish(
        out["process_progress"],
        out["kit"],
        status=str(header.status.value),
        attendance_rules=rules,
        pace=fact["pace"],
        remaining_pairs=fact["remaining"],
    )
    assert out["projected_finish"] == finish.isoformat()


def test_unreported_order_follows_previous_pace_and_purchase_eta(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    as_of = date(2026, 3, 2)
    first = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-PACE",
        own_product_id=product.id,
        total_qty=100,
        status=SpecExecutionStatus.in_progress,
        schedule_sequence=1,
        created_at=datetime(2026, 3, 1, 1, 0),
    )
    second = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-WAIT",
        own_product_id=product.id,
        total_qty=200,
        status=SpecExecutionStatus.confirmed,
        schedule_sequence=2,
        created_at=datetime(2026, 3, 1, 2, 0),
    )
    db.add_all([first, second])
    db.commit()
    items = {
        first.id: {"process_progress": [], "kit": {"kit_ok": True, "empty_bom": False}},
        second.id: {
            "process_progress": [],
            "kit": {
                "kit_ok": False,
                "empty_bom": False,
                "kit_ready_date": "2026-03-20",
                "shortage_lines": 1,
            },
        },
    }
    apply_projected_finish(
        db,
        tenant.id,
        [first, second],
        items,
        pace_facts={
            first.id: {"pace": Decimal("100"), "remaining": 100},
            second.id: {"pace": None, "remaining": 200},
        },
        as_of=as_of,
    )
    first_finish = date.fromisoformat(items[first.id]["projected_finish"])
    assert first_finish == _expected_finish(as_of, [1])
    assert items[second.id]["projected_finish"] == _expected_finish(date(2026, 3, 20), [2]).isoformat()
    assert any(item["code"] == "borrowed_pace" for item in items[second.id]["risk"]["reasons"])

    items[second.id]["kit"] = {"kit_ok": True, "empty_bom": False}
    apply_projected_finish(
        db,
        tenant.id,
        [first, second],
        items,
        pace_facts={
            first.id: {"pace": Decimal("100"), "remaining": 100},
            second.id: {"pace": None, "remaining": 200},
        },
        as_of=as_of,
    )
    assert items[second.id]["projected_finish"] == _expected_finish(
        first_finish + timedelta(days=1), [2]
    ).isoformat()

    items[second.id]["kit"] = {"kit_ok": True, "empty_bom": False}
    apply_projected_finish(
        db,
        tenant.id,
        [first, second],
        items,
        pace_facts={
            first.id: {"pace": Decimal("100"), "remaining": 100},
            second.id: {"pace": Decimal("50"), "remaining": 100},
        },
        as_of=as_of,
    )
    assert items[second.id]["projected_finish"] == _expected_finish(as_of, [2]).isoformat()
    assert all(item["code"] != "borrowed_pace" for item in items[second.id]["risk"]["reasons"])


def test_projected_finish_skips_fixed_and_designated_rest(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    weekly = ar.merge_attendance_rules({"rest_day_mode": "weekly", "weekly_rest_days": [6, 7]})
    friday = date(2026, 3, 6)

    # 周五起 3 个出勤日：周五、周一、周二，周六日休息
    finish = project_header_finish(
        [],
        {"kit_ok": True, "empty_bom": False},
        status="in_progress",
        as_of=friday,
        attendance_rules=weekly,
        pace=Decimal("100"),
        remaining_pairs=300,
    )
    assert finish == date(2026, 3, 10)
    assert ar.is_attendance_workday(finish, weekly)

    # 采购到货落在周日，未开工的单从周一开始
    eta_finish = project_header_finish(
        [],
        {"kit_ok": False, "empty_bom": False, "kit_ready_date": "2026-03-08"},
        status="confirmed",
        as_of=friday,
        attendance_rules=weekly,
        pace=Decimal("100"),
        remaining_pairs=100,
    )
    assert eta_finish == date(2026, 3, 9)

    # 每月 1 号休息；周末仍是出勤日。10-30 起 3 天跨过 11-01，落到 11-02
    monthly = ar.merge_attendance_rules(
        {"rest_day_mode": "monthly", "monthly_rest_days": [1], "weekly_rest_days": [6, 7]}
    )
    monthly_finish = project_header_finish(
        [],
        {"kit_ok": True, "empty_bom": False},
        status="in_progress",
        as_of=date(2026, 10, 30),
        attendance_rules=monthly,
        pace=Decimal("100"),
        remaining_pairs=300,
    )
    assert monthly_finish == date(2026, 11, 2)
    assert ar.is_attendance_workday(date(2026, 10, 31), monthly)

    designated = ar.merge_attendance_rules(
        {
            "rest_day_mode": "weekly",
            "weekly_rest_days": [],
            "designated_rest_ranges": [{"start": "2026-03-07", "end": "2026-03-08"}],
        }
    )
    designated_finish = project_header_finish(
        [],
        {"kit_ok": True, "empty_bom": False},
        status="in_progress",
        as_of=friday,
        attendance_rules=designated,
        pace=Decimal("100"),
        remaining_pairs=300,
    )
    assert designated_finish == date(2026, 3, 10)

    first = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-REST-1",
        own_product_id=product.id,
        total_qty=100,
        status=SpecExecutionStatus.in_progress,
        schedule_sequence=1,
        created_at=datetime(2026, 3, 6, 1, 0),
    )
    second = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-REST-2",
        own_product_id=product.id,
        total_qty=100,
        status=SpecExecutionStatus.confirmed,
        schedule_sequence=2,
        created_at=datetime(2026, 3, 6, 2, 0),
    )
    db.add_all([first, second])
    db.commit()
    items = {
        first.id: {"process_progress": [], "kit": {"kit_ok": True, "empty_bom": False}},
        second.id: {"process_progress": [], "kit": {"kit_ok": True, "empty_bom": False}},
    }
    apply_projected_finish(
        db,
        tenant.id,
        [first, second],
        items,
        pace_facts={
            first.id: {"pace": Decimal("100"), "remaining": 100},
            second.id: {"pace": None, "remaining": 100},
        },
        attendance_rules=weekly,
        as_of=friday,
    )
    assert items[first.id]["projected_finish"] == "2026-03-06"
    # 上一张周五完成，下一天是周六，未报工的单从周一开始，不排在休息日
    assert items[second.id]["projected_finish"] == "2026-03-09"
    assert ar.is_attendance_workday(date.fromisoformat(items[second.id]["projected_finish"]), weekly)


def test_shift_hours_skip_lunch_and_weekend():
    rules = ar.merge_attendance_rules({"rest_day_mode": "weekly", "weekly_rest_days": [6, 7]})
    # 11:00 再做 60 分钟，上午到 12:00 正好结束
    assert ar.add_attendance_work_minutes(datetime(2026, 10, 28, 11, 0), 60, rules) == datetime(2026, 10, 28, 12, 0)
    # 多 1 分钟跨过午休，从 13:30 接着算
    assert ar.add_attendance_work_minutes(datetime(2026, 10, 28, 11, 0), 61, rules) == datetime(2026, 10, 28, 13, 31)
    # 周五 17:00 只剩 30 分钟，剩下的 30 分钟落到下周一 08:30
    assert ar.add_attendance_work_minutes(datetime(2026, 10, 30, 17, 0), 60, rules) == datetime(2026, 11, 2, 8, 30)


def test_small_orders_share_a_workday(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    rules = ar.merge_attendance_rules({"rest_day_mode": "weekly", "weekly_rest_days": [6, 7]})
    as_of = date(2026, 10, 28)
    done = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-DONE",
        own_product_id=product.id,
        total_qty=210,
        status=SpecExecutionStatus.in_progress,
        schedule_sequence=1,
        created_at=datetime(2026, 10, 26, 1, 0),
    )
    seven = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-7",
        own_product_id=product.id,
        total_qty=7,
        status=SpecExecutionStatus.confirmed,
        schedule_sequence=2,
        created_at=datetime(2026, 10, 26, 2, 0),
    )
    sixty = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-60",
        own_product_id=product.id,
        total_qty=60,
        status=SpecExecutionStatus.confirmed,
        schedule_sequence=3,
        created_at=datetime(2026, 10, 26, 3, 0),
    )
    db.add_all([done, seven, sixty])
    db.commit()
    items = {
        row.id: {"process_progress": [], "kit": {"kit_ok": True, "empty_bom": False}}
        for row in (done, seven, sixty)
    }
    apply_projected_finish(
        db,
        tenant.id,
        [done, seven, sixty],
        items,
        pace_facts={
            done.id: {"pace": Decimal("210"), "remaining": 0},
            seven.id: {"pace": None, "remaining": 7},
            sixty.id: {"pace": None, "remaining": 60},
        },
        attendance_rules=rules,
        as_of=as_of,
    )
    # 210 双/天、一天 8 小时：7 双约 16 分钟，60 双接着排，都在 28 日上午完成
    assert items[seven.id]["risk"]["projected_finish_at"] == "2026-10-28 08:16"
    assert items[sixty.id]["risk"]["projected_finish_at"] == "2026-10-28 10:34"
    assert items[seven.id]["projected_finish"] == "2026-10-28"
    assert items[sixty.id]["projected_finish"] == "2026-10-28"


def test_420_after_210_takes_two_days(db):
    tenant = db.scalar(select(Tenant).limit(1))
    product = db.scalar(select(OwnProduct).limit(1))
    rules = ar.merge_attendance_rules({"rest_day_mode": "weekly", "weekly_rest_days": [6, 7]})
    as_of = date(2026, 10, 28)
    previous = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-210",
        own_product_id=product.id,
        total_qty=210,
        status=SpecExecutionStatus.in_progress,
        schedule_sequence=1,
        created_at=datetime(2026, 10, 26, 1, 0),
    )
    current = ExecutionHeader(
        tenant_id=tenant.id,
        header_no="XE-420",
        own_product_id=product.id,
        total_qty=420,
        status=SpecExecutionStatus.confirmed,
        schedule_sequence=2,
        created_at=datetime(2026, 10, 26, 2, 0),
    )
    db.add_all([previous, current])
    db.commit()
    items = {
        previous.id: {"process_progress": [], "kit": {"kit_ok": True, "empty_bom": False}},
        current.id: {"process_progress": [], "kit": {"kit_ok": True, "empty_bom": False}},
    }
    apply_projected_finish(
        db,
        tenant.id,
        [previous, current],
        items,
        pace_facts={
            previous.id: {"pace": Decimal("210"), "remaining": 0},
            current.id: {"pace": None, "remaining": 420},
        },
        attendance_rules=rules,
        as_of=as_of,
    )
    assert items[previous.id]["projected_finish"] == "2026-10-28"
    # 420 双正好两个出勤日。上一张已经做完，从 28 日上班接着排，29 日下班完成
    assert items[current.id]["projected_finish"] == "2026-10-29"
    assert items[current.id]["risk"]["projected_finish_at"] == "2026-10-29 17:30"
