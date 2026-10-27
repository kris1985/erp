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
    assert ar.is_attendance_workday(date(2026, 3, 2), weekly)
    assert not ar.is_attendance_workday(date(2026, 3, 7), weekly)
    monthly = ar.merge_attendance_rules(
        {"rest_day_mode": "monthly", "monthly_rest_days": [15], "weekly_rest_days": []}
    )
    assert ar.is_attendance_workday(date(2026, 3, 14), monthly)
    assert not ar.is_attendance_workday(date(2026, 3, 15), monthly)
    assert ar.is_attendance_workday(date(2026, 3, 7), monthly)


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
    # 裁断当天 30+70，成型 90；包装没报工，不把当天压成 0
    fact = _pace(
        300,
        [1, 2, 3],
        [
            (1, date(2026, 3, 2), 30, 0, 0, "normal"),
            (1, date(2026, 3, 2), 70, 0, 0, "group"),
            (2, date(2026, 3, 2), 90, 0, 0, "supplement"),
        ],
    )
    assert fact["pace"] == Decimal("90")
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
    assert fact["pace"] == Decimal("80")
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


def test_special_holiday_skips_weekday():
    rules = ar.merge_attendance_rules(
        {
            "weekly_rest_days": [6, 7],
            "special_holidays": [{"start": "2026-03-03 00:00", "end": "2026-03-04 00:00"}],
        }
    )
    as_of = date(2026, 3, 2)
    finish = project_header_finish(
        [],
        {"kit_ok": True, "empty_bom": False},
        status="confirmed",
        as_of=as_of,
        attendance_rules=rules,
        pace=Decimal("100"),
        remaining_pairs=200,
    )
    assert finish == date(2026, 3, 4)


def test_special_overtime_counts_rest_day():
    rules = ar.merge_attendance_rules(
        {
            "weekly_rest_days": [6, 7],
            "special_overtimes": [{"start": "2026-03-08 08:00", "end": "2026-03-08 17:30"}],
        }
    )
    as_of = date(2026, 3, 6)
    finish = project_header_finish(
        [],
        {"kit_ok": True, "empty_bom": False},
        status="confirmed",
        as_of=as_of,
        attendance_rules=rules,
        pace=Decimal("100"),
        remaining_pairs=200,
    )
    assert finish == date(2026, 3, 8)


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
    assert fact["pace"] == Decimal("65")
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
        as_of=date.today(),
        pace=fact["pace"],
        remaining_pairs=fact["remaining"],
    )
    assert out["projected_finish"] == finish.isoformat()
