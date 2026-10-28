"""提前结算 settle_through：截断取数 + 固定类按日折算。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    AttendanceDay,
    DefectDisposition,
    DefectEvent,
    DefectEventStatus,
    DefectResponsibility,
    Department,
    Employee,
    OwnProduct,
    ProcessDefinition,
    ProcessType,
    SalaryModel,
    Tenant,
    WorkLog,
    WorkLogSource,
    WorkLogStatus,
    ReportType,
)
from app.services.trace_service import apply_defect_loss_allocation, _assign_responsibility_share_amounts
from app.services.attendance_rules import is_attendance_workday
from app.services.salary_service import (
    export_bank_payroll_csv,
    month_salary,
    resolve_settle_window,
    set_month_lock,
    settle_month,
)


@pytest.fixture()
def settle_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="截断结算厂", settings_json={})
    session.add(tenant)
    session.flush()
    dept = Department(tenant_id=tenant.id, name="车间")
    session.add(dept)
    session.flush()
    product = OwnProduct(tenant_id=tenant.id, product_code="P1", is_active=True)
    process = ProcessDefinition(
        tenant_id=tenant.id,
        name="针车",
        code="ZC",
        type=ProcessType.personal,
    )
    session.add_all([product, process])
    session.flush()
    fixed = Employee(
        tenant_id=tenant.id,
        name="固定工",
        department_id=dept.id,
        salary_model=SalaryModel.fixed,
        base_salary=Decimal("3100"),
        is_active=True,
        bank_account="62220000",
        bank_name="工行",
        bank_account_name="固定工",
    )
    piece = Employee(
        tenant_id=tenant.id,
        name="计件工",
        department_id=dept.id,
        salary_model=SalaryModel.pure_piece,
        is_active=True,
        bank_account="62220001",
        bank_name="工行",
        bank_account_name="计件工",
    )
    session.add_all([fixed, piece])
    session.commit()
    yield session, tenant, fixed, piece, product, process
    session.close()


def test_resolve_settle_window_proration():
    w = resolve_settle_window("2026-12", date(2026, 12, 25))
    assert w["period_days"] == 25
    assert w["days_in_month"] == 31
    assert w["is_partial"] is True
    assert float(w["proration"]) == pytest.approx(25 / 31, rel=1e-4)

    full = resolve_settle_window("2026-12", None)
    assert full["is_partial"] is False
    assert float(full["proration"]) == 1.0


def test_current_month_stops_at_today(monkeypatch):
    from app.services import salary_service

    monkeypatch.setattr(salary_service, "_local_today", lambda: date(2026, 10, 28))
    window = resolve_settle_window("2026-10", None)
    assert window["period_end"] == date(2026, 10, 28)
    assert window["period_days"] == 28

    tail = resolve_settle_window("2026-10", None, date(2026, 10, 28))
    assert tail["period_start"] == date(2026, 10, 28)
    assert tail["period_end"] == date(2026, 10, 28)
    assert tail["period_days"] == 1

    past = resolve_settle_window("2026-09", None)
    assert past["period_end"] == date(2026, 9, 30)


def _workdays(year: int, month: int, last: int) -> list[date]:
    return [date(year, month, day) for day in range(1, last + 1) if is_attendance_workday(date(year, month, day), None)]


def _mark_present(db, tenant, employee, work_date: date) -> None:
    db.add(
        AttendanceDay(
            tenant_id=tenant.id,
            employee_id=employee.id,
            work_date=work_date,
            status="normal",
            work_minutes=480,
        )
    )


def test_fixed_salary_partial_window_uses_calendar_days(settle_db):
    db, tenant, fixed, _piece, _product, _process = settle_db
    scheduled = _workdays(2026, 12, 31)
    attended = [day for day in scheduled if day <= date(2026, 12, 25)]
    for day in attended:
        _mark_present(db, tenant, fixed, day)
    db.commit()

    detail = month_salary(
        db, tenant.id, fixed.id, "2026-12", settle_through=date(2026, 12, 25)
    )
    daily = (Decimal("3100") / Decimal(31)).quantize(Decimal("1"))
    expected = daily * Decimal(25)
    assert detail["base_salary"] == pytest.approx(float(expected))
    assert detail["total_wage"] == pytest.approx(float(expected))
    assert detail["settle_through"] == "2026-12-25"
    assert detail["settled_wage"] == 0
    assert detail["unsettled_wage"] == pytest.approx(float(expected))
    assert "出勤" not in detail["settle_note"]


def test_piecework_cutoff_excludes_later_logs(settle_db):
    db, tenant, _fixed, piece, product, process = settle_db
    # 本地 12/20 与 12/28（UTC = 本地 - 8h）；order_process_id 仅占位，结算不读订单工序。
    early = WorkLog(
        tenant_id=tenant.id,
        worker_id=piece.id,
        order_process_id=1,
        own_product_id=product.id,
        process_id=process.id,
        qualified_qty=10,
        unit_price=Decimal("2"),
        report_type=ReportType.normal,
        status=WorkLogStatus.valid,
        source=WorkLogSource.manual,
        created_at=datetime(2026, 12, 19, 16, 0, 0),  # 本地 12/20 00:00
    )
    late = WorkLog(
        tenant_id=tenant.id,
        worker_id=piece.id,
        order_process_id=1,
        own_product_id=product.id,
        process_id=process.id,
        qualified_qty=10,
        unit_price=Decimal("2"),
        report_type=ReportType.normal,
        status=WorkLogStatus.valid,
        source=WorkLogSource.manual,
        created_at=datetime(2026, 12, 27, 16, 0, 0),  # 本地 12/28 00:00
    )
    db.add_all([early, late])
    db.commit()

    full = month_salary(db, tenant.id, piece.id, "2026-12")
    assert full["total_piece_wage"] == pytest.approx(40)

    cut = month_salary(
        db, tenant.id, piece.id, "2026-12", settle_through=date(2026, 12, 25)
    )
    assert cut["total_piece_wage"] == pytest.approx(20)
    assert cut["total_wage"] == pytest.approx(20)
    assert cut["settled_wage"] == 0
    assert cut["unsettled_wage"] == pytest.approx(20)


def test_local_db_clock_keeps_same_day_evening_log(settle_db, monkeypatch):
    """数据库 NOW() 是东八区时，当天 16 点后的报工仍算在当天。"""
    db, tenant, _fixed, piece, product, process = settle_db
    monkeypatch.setattr(
        "app.services.salary_service._work_log_clock_offset",
        lambda _db: timedelta(hours=8),
    )
    db.add_all([
        WorkLog(
            tenant_id=tenant.id,
            worker_id=piece.id,
            order_process_id=1,
            own_product_id=product.id,
            process_id=process.id,
            qualified_qty=10,
            unit_price=Decimal("2"),
            report_type=ReportType.normal,
            status=WorkLogStatus.valid,
            source=WorkLogSource.manual,
            created_at=datetime(2026, 12, 25, 17, 19, 0),
        ),
        WorkLog(
            tenant_id=tenant.id,
            worker_id=piece.id,
            order_process_id=1,
            own_product_id=product.id,
            process_id=process.id,
            qualified_qty=5,
            unit_price=Decimal("2"),
            report_type=ReportType.normal,
            status=WorkLogStatus.valid,
            source=WorkLogSource.manual,
            created_at=datetime(2026, 12, 26, 0, 30, 0),
        ),
    ])
    db.commit()

    cut = month_salary(db, tenant.id, piece.id, "2026-12", settle_through=date(2026, 12, 25))
    assert cut["total_piece_wage"] == pytest.approx(20)
    assert [str(row["created_at"])[:10] for row in cut["details"]] == ["2026-12-25"]


def test_locked_month_splits_settled_and_unsettled(settle_db):
    db, tenant, fixed, piece, product, process = settle_db
    scheduled = _workdays(2026, 12, 31)
    before = next(day for day in scheduled if day <= date(2026, 12, 25))
    after = next(day for day in scheduled if day > date(2026, 12, 25))
    _mark_present(db, tenant, fixed, before)
    _mark_present(db, tenant, fixed, after)
    db.add_all([
        WorkLog(
            tenant_id=tenant.id,
            worker_id=piece.id,
            order_process_id=1,
            own_product_id=product.id,
            process_id=process.id,
            qualified_qty=10,
            unit_price=Decimal("2"),
            report_type=ReportType.normal,
            status=WorkLogStatus.valid,
            source=WorkLogSource.manual,
            created_at=datetime(2026, 12, 19, 16, 0, 0),
        ),
        WorkLog(
            tenant_id=tenant.id,
            worker_id=piece.id,
            order_process_id=1,
            own_product_id=product.id,
            process_id=process.id,
            qualified_qty=10,
            unit_price=Decimal("2"),
            report_type=ReportType.normal,
            status=WorkLogStatus.valid,
            source=WorkLogSource.manual,
            created_at=datetime(2026, 12, 27, 16, 0, 0),
        ),
    ])
    db.commit()
    saved = settle_month(db, tenant.id, "2026-12", date(2026, 12, 25), settled_by=fixed.id)
    assert saved["is_locked"] is False
    assert saved["settle_through"] == "2026-12-25"

    fixed_pay = month_salary(db, tenant.id, fixed.id, "2026-12")
    daily = (Decimal("3100") / Decimal(31)).quantize(Decimal("1"))
    assert fixed_pay["settled_wage"] == pytest.approx(float(daily * 25))
    assert fixed_pay["unsettled_wage"] == pytest.approx(float(daily * 6))
    assert fixed_pay["total_wage"] == pytest.approx(float(daily * 25))

    piece_pay = month_salary(db, tenant.id, piece.id, "2026-12")
    assert piece_pay["settled_wage"] == pytest.approx(20)
    assert piece_pay["unsettled_wage"] == pytest.approx(20)
    assert {row["settlement"] for row in piece_pay["details"]} == {"settled", "unsettled"}

    with pytest.raises(ValueError, match="不能再次结算"):
        settle_month(db, tenant.id, "2026-12", date(2026, 12, 31), settled_by=fixed.id)


def test_lock_persists_settle_through_and_bank_remark(settle_db):
    db, tenant, fixed, _piece, _product, _process = settle_db
    _mark_present(db, tenant, fixed, date(2026, 12, 1))
    db.commit()
    lock = set_month_lock(
        db,
        tenant.id,
        "2026-12",
        locked=True,
        locked_by=fixed.id,
        settle_through=date(2026, 12, 25),
    )
    assert lock["settle_through"] == "2026-12-25"
    assert lock["is_locked"] is True

    # 锁定后不传参数也应截断
    detail = month_salary(db, tenant.id, fixed.id, "2026-12")
    assert detail["settle_through"] == "2026-12-25"

    csv_text = export_bank_payroll_csv(db, tenant.id, "2026-12")
    assert "截至12-25" in csv_text
    assert "2026-12-25发" in csv_text

    unlocked = set_month_lock(db, tenant.id, "2026-12", locked=False)
    assert unlocked["settle_through"] is None


def test_scrap_salary_uses_entered_yuan_not_rounded_percent(settle_db):
    db, tenant, _fixed, piece, _product, _process = settle_db
    event = DefectEvent(
        tenant_id=tenant.id,
        defect_type="报废",
        qty=1,
        disposition=DefectDisposition.scrap,
        status=DefectEventStatus.closed,
        loss_amount=Decimal("59.85"),
        company_share_percent=50,
        scrap_confirmed_at=datetime(2026, 12, 10, 8, 0),
    )
    db.add(event)
    db.flush()
    apply_defect_loss_allocation(
        db,
        tenant_id=tenant.id,
        event=event,
        loss_amount=Decimal("59.85"),
        company_share_percent=50,
        responsibilities=[
            {"worker_id": piece.id, "share_percent": 50, "share_amount": Decimal("30")},
        ],
    )
    db.commit()
    row = db.scalar(
        select(DefectResponsibility).where(DefectResponsibility.defect_event_id == event.id)
    )
    assert row.share_amount == Decimal("30.00")
    result = month_salary(db, tenant.id, piece.id, "2026-12")
    assert result["loss_deduction"] == pytest.approx(30.0)
    detail = next(item for item in result["details"] if item.get("report_type") == "scrap_deduction")
    assert detail["wage_deduction"] == pytest.approx(30.0)


def test_entered_amount_splits_across_sizes_without_changing_total(settle_db):
    db, tenant, _fixed, piece, _product, _process = settle_db
    events = []
    for loss in (Decimal("40.00"), Decimal("19.85")):
        event = DefectEvent(
            tenant_id=tenant.id,
            defect_type="other",
            qty=1,
            disposition=DefectDisposition.scrap,
            status=DefectEventStatus.closed,
            loss_amount=loss,
        )
        db.add(event)
        db.flush()
        apply_defect_loss_allocation(
            db,
            tenant_id=tenant.id,
            event=event,
            loss_amount=loss,
            company_share_percent=50,
            responsibilities=[{"worker_id": piece.id, "share_percent": 50}],
        )
        events.append(event)
    _assign_responsibility_share_amounts(
        db,
        tenant_id=tenant.id,
        events=events,
        amounts={piece.id: Decimal("30.00")},
    )
    amounts = [
        db.scalar(
            select(DefectResponsibility.share_amount).where(
                DefectResponsibility.defect_event_id == event.id
            )
        )
        for event in events
    ]
    assert amounts == [Decimal("20.05"), Decimal("9.95")]
    assert sum(amounts, Decimal("0")) == Decimal("30.00")
