from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import AttendanceDay, AttendancePunch, Department, Employee, SalaryModel, Tenant
from app.services import attendance_service
from app.services.attendance_service import AttendanceError
from app.services.report_service import ReportError, submit_report
from app.services.salary_service import month_salary


@pytest.fixture()
def attendance_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="考勤测试厂")
    session.add(tenant)
    session.flush()
    department = Department(tenant_id=tenant.id, name="行政部")
    session.add(department)
    session.flush()
    fixed = Employee(
        tenant_id=tenant.id,
        name="包月员工",
        department_id=department.id,
        salary_model=SalaryModel.fixed,
        is_active=True,
    )
    piece = Employee(
        tenant_id=tenant.id,
        name="计件员工",
        department_id=department.id,
        salary_model=SalaryModel.pure_piece,
        is_active=True,
    )
    session.add_all([fixed, piece])
    session.commit()
    yield session, tenant, fixed, piece
    session.close()


def _enable_clock_site(db, tenant, **rules):
    tenant.settings_json = {
        "attendance_rules": {
            "weekly_rest_days": [],
            "work_periods": [{"start": "08:00", "end": "17:30"}],
            "overtime_periods": [],
            "clock_site": {"latitude": 30.0, "longitude": 120.0, "radius_meters": 200},
            **rules,
        }
    }
    db.commit()


def _freeze(monkeypatch, hm: str, day: date = date(2026, 10, 21)) -> None:
    hour, minute = (int(part) for part in hm.split(":"))
    local = datetime(day.year, day.month, day.day, hour, minute)
    utc = local - attendance_service.LOCAL_OFFSET
    monkeypatch.setattr(attendance_service, "_now_utc", lambda: utc)


def _clock(db, tenant, employee, punch_type, *, latitude=30.0, longitude=120.0, slot_id=None, update=False):
    return attendance_service.clock(
        db,
        tenant.id,
        employee.id,
        punch_type,
        latitude=latitude,
        longitude=longitude,
        slot_id=slot_id,
        update=update,
    )


def test_fixed_employee_clocks_in_and_out(attendance_db, monkeypatch):
    db, tenant, fixed, _ = attendance_db
    _enable_clock_site(db, tenant)
    _freeze(monkeypatch, "08:10")
    first = _clock(db, tenant, fixed, "on_duty")
    assert first["clock_in_at"]
    assert first["clock_out_at"] is None
    assert first["next_punch_type"] is None
    with pytest.raises(AttendanceError, match="17:00"):
        _clock(db, tenant, fixed, "off_duty", slot_id="work:0")

    _freeze(monkeypatch, "17:10")
    second = _clock(db, tenant, fixed, "off_duty")
    assert second["clock_out_at"]
    assert second["status"] in {"normal", "late", "early", "late_early"}
    assert second["next_punch_type"] is None

    with pytest.raises(AttendanceError, match="已打卡"):
        _clock(db, tenant, fixed, "on_duty")


def test_clock_supports_multiple_periods_overtime_and_update(attendance_db, monkeypatch):
    db, tenant, fixed, _ = attendance_db
    _enable_clock_site(
        db,
        tenant,
        work_periods=[
            {"start": "08:00", "end": "12:00"},
            {"start": "13:30", "end": "17:30"},
        ],
    )
    raw = [
        {"id": "work:0", "kind": "work", "label": "上午", "start": "08:00", "end": "12:00", "clock_in_at": "2026-10-21 08:01:00", "clock_out_at": None},
        {"id": "work:1", "kind": "work", "label": "下午", "start": "13:30", "end": "17:30", "clock_in_at": None, "clock_out_at": None},
        {"id": "overtime:0", "kind": "overtime", "label": "加班", "start": "18:00", "end": "21:00", "clock_in_at": None, "clock_out_at": None},
    ]
    morning = attendance_service._decorate_slots(raw, [], "09:30", True)
    assert morning[0]["off_action"]["enabled"] is False
    assert morning[0]["off_action"]["label"] == "11:30后"
    assert morning[1]["on_action"]["enabled"] is False
    assert morning[0]["on_from"] == "07:00" and morning[0]["on_to"] == "08:30"
    assert morning[0]["off_from"] == "11:30" and morning[0]["off_to"] == "12:45"
    assert morning[1]["on_from"] == "12:45" and morning[1]["on_to"] == "14:00"
    assert morning[1]["off_from"] == "17:00"
    leaving = attendance_service._decorate_slots(raw, [], "11:40", True)
    assert leaving[0]["off_action"]["enabled"] is True
    afternoon = attendance_service._decorate_slots(raw, [], "14:00", True)
    assert afternoon[0]["on_action"]["enabled"] is False
    assert afternoon[1]["on_action"]["enabled"] is True
    assert afternoon[2]["on_action"]["label"].endswith("后")
    missed = attendance_service._decorate_slots(
        [{**raw[0], "clock_in_at": None}], [], "09:00", True
    )
    assert missed[0]["on_action"]["enabled"] is False
    assert missed[0]["on_action"]["label"] == "已过时间"

    _freeze(monkeypatch, "08:10")
    today = attendance_service.get_today(db, tenant.id, fixed.id)
    assert [slot["id"] for slot in today["slots"]] == ["work:0", "work:1"]
    opened = next(
        (slot["on_action"] if slot["on_action"]["enabled"] else slot["off_action"])
        for slot in attendance_service.get_today(db, tenant.id, fixed.id)["slots"]
        if slot["on_action"]["enabled"] or slot["off_action"]["enabled"]
    )
    punched = _clock(db, tenant, fixed, opened["punch_type"], slot_id=opened["slot_id"])
    assert any(slot["id"] == opened["slot_id"] and (slot["clock_in_at"] or slot["clock_out_at"]) for slot in punched["slots"])


def test_clock_rejects_outside_the_factory_radius(attendance_db, monkeypatch):
    _freeze(monkeypatch, "08:10")
    db, tenant, fixed, _ = attendance_db
    _enable_clock_site(db, tenant)
    with pytest.raises(AttendanceError, match="超出 200 米范围"):
        _clock(db, tenant, fixed, "on_duty", latitude=30.02, longitude=120.0)
    with pytest.raises(AttendanceError, match="工厂还没设置打卡地点"):
        tenant.settings_json = {"attendance_rules": {}}
        db.commit()
        _clock(db, tenant, fixed, "on_duty")


def test_piecework_employees_can_also_use_attendance(attendance_db, monkeypatch):
    db, tenant, fixed, piece = attendance_db
    _enable_clock_site(db, tenant)
    _freeze(monkeypatch, "08:10")
    _clock(db, tenant, fixed, "on_duty")
    _clock(db, tenant, piece, "on_duty")

    result = attendance_service.list_records(db, tenant.id)
    assert result["total"] == 2
    assert {row["employee_id"] for row in result["items"]} == {fixed.id, piece.id}
    assert {row["department_name"] for row in result["items"]} == {"行政部"}
    department_result = attendance_service.list_records(
        db, tenant.id, department_id=fixed.department_id
    )
    assert department_result["total"] == 2
    assert attendance_service.list_records(db, tenant.id, department_id=999999)["total"] == 0


def test_clock_windows_follow_configured_work_periods():
    """窗口跟着规则里的上班、下班时间走，改一段，相邻窗口一起动。"""
    rules = {
        "weekly_rest_days": [],
        "work_periods": [
            {"start": "07:30", "end": "11:30"},
            {"start": "13:00", "end": "17:00"},
            {"start": "18:30", "end": "22:30"},
        ],
        "overtime_periods": [],
    }
    slots = attendance_service._window_bounds(
        attendance_service._schedule_slots(rules, date(2026, 10, 21))
    )
    assert [(slot["start"], slot["end"]) for slot in slots] == [
        ("07:30", "11:30"),
        ("13:00", "17:00"),
        ("18:30", "22:30"),
    ]
    assert slots[0]["on_from"] == "06:30" and slots[0]["on_to"] == "08:00"
    assert slots[0]["off_from"] == "11:00" and slots[0]["off_to"] == "12:15"
    assert slots[1]["on_from"] == "12:15" and slots[1]["on_to"] == "13:30"
    assert slots[1]["off_from"] == "16:30" and slots[1]["off_to"] == "17:45"
    assert slots[2]["on_from"] == "17:45" and slots[2]["on_to"] == "19:00"
    assert slots[2]["off_from"] == "22:00" and slots[2]["off_to"] == "23:30"


def test_short_period_splits_clock_windows_at_midpoint():
    raw = [{"id": "work:0", "kind": "work", "label": "上下班", "start": "08:00", "end": "08:40", "clock_in_at": None, "clock_out_at": None}]
    slot = attendance_service._decorate_slots(raw, [], "08:10", True)[0]
    assert slot["on_from"] == "07:00" and slot["on_to"] == "08:20"
    assert slot["off_from"] == "08:20"
    assert slot["on_action"]["enabled"] is True
    assert slot["off_action"]["label"] == "先上班"


def test_attendance_duration_sums_segments_and_status():
    work_date = date(2026, 10, 21)

    def at(hm: str) -> datetime:
        hour, minute = (int(part) for part in hm.split(":"))
        return datetime(work_date.year, work_date.month, work_date.day, hour, minute) - attendance_service.LOCAL_OFFSET

    rules = {
        "weekly_rest_days": [],
        "work_periods": [{"start": "08:00", "end": "12:00"}, {"start": "13:30", "end": "17:30"}],
        "overtime_periods": [],
        "special_holidays": [],
        "special_overtimes": [],
        "late_early_deduction": {"grace_minutes": 5},
    }
    punches = [
        SimpleNamespace(punch_type="on_duty", schedule_id="work:0", check_time=at("08:20")),
        SimpleNamespace(punch_type="off_duty", schedule_id="work:0", check_time=at("12:00")),
        SimpleNamespace(punch_type="on_duty", schedule_id="work:1", check_time=at("13:30")),
        SimpleNamespace(punch_type="off_duty", schedule_id="work:1", check_time=at("16:00")),
    ]
    summary = attendance_service.summarize_attendance(rules, work_date, punches)
    assert summary["work_minutes"] == 220 + 150
    assert summary["status"] == "late_early"
    assert summary["late_minutes"] == 15
    assert summary["early_minutes"] == 85
    assert summary["segments"][0]["clock_in_at"].endswith("08:20:00")
    assert summary["segments"][1]["clock_out_at"].endswith("16:00:00")

    missing = attendance_service.summarize_attendance(rules, work_date, punches[:2])
    assert missing["status"] == "missing"
    assert missing["work_minutes"] == 220


def test_designated_rest_minutes_split_the_shift():
    from app.services import attendance_service

    rules = {
        "weekly_rest_days": [],
        "work_periods": [
            {"start": "08:00", "end": "12:00"},
            {"start": "13:30", "end": "17:30"},
        ],
        "designated_rest_ranges": [
            {"start": "2026-03-03 10:15", "end": "2026-03-03 11:00"},
        ],
    }
    slots = attendance_service._schedule_slots(rules, date(2026, 3, 3))
    assert [(slot["start"], slot["end"]) for slot in slots] == [
        ("08:00", "10:15"),
        ("11:01", "12:00"),
        ("13:30", "17:30"),
    ]


def test_overtime_period_minutes_are_paid_separately():
    work_date = date(2026, 10, 21)

    def at(hm: str) -> datetime:
        hour, minute = (int(part) for part in hm.split(":"))
        return datetime(work_date.year, work_date.month, work_date.day, hour, minute) - attendance_service.LOCAL_OFFSET

    rules = {
        "weekly_rest_days": [],
        "work_periods": [{"start": "08:00", "end": "17:00"}],
        "overtime_periods": [{"start": "18:00", "end": "21:00"}],
    }
    slots = attendance_service._schedule_slots(rules, work_date)
    assert [(slot["id"], slot["kind"]) for slot in slots] == [("work:0", "work"), ("overtime:0", "overtime")]
    punches = [
        SimpleNamespace(punch_type="on_duty", schedule_id="work:0", check_time=at("08:00")),
        SimpleNamespace(punch_type="off_duty", schedule_id="work:0", check_time=at("17:00")),
        SimpleNamespace(punch_type="on_duty", schedule_id="overtime:0", check_time=at("18:00")),
        SimpleNamespace(punch_type="off_duty", schedule_id="overtime:0", check_time=at("20:30")),
    ]
    summary = attendance_service.summarize_attendance(rules, work_date, punches)
    assert summary["work_minutes"] == 9 * 60
    assert summary["overtime_minutes"] == 150
    assert summary["status"] == "normal"


def test_fixed_salary_uses_overtime_period_minutes(attendance_db):
    db, tenant, fixed, _ = attendance_db
    _enable_clock_site(
        db,
        tenant,
        work_periods=[{"start": "08:00", "end": "17:00"}],
        overtime_periods=[{"start": "18:00", "end": "21:00"}],
    )
    fixed.base_salary = Decimal("3000")
    fixed.overtime_hourly_rate = Decimal("20")
    db.add(
        AttendanceDay(
            tenant_id=tenant.id,
            employee_id=fixed.id,
            work_date=date(2026, 9, 1),
            work_minutes=9 * 60,
            overtime_minutes=150,
            status="normal",
        )
    )
    db.commit()

    result = month_salary(db, tenant.id, fixed.id, "2026-09")
    assert result["overtime_hours"] == 2.5
    assert result["overtime_pay"] == 50.0


def test_fixed_employee_cannot_submit_production_report(attendance_db):
    db, tenant, fixed, _ = attendance_db
    with pytest.raises(ReportError) as exc:
        submit_report(
            db,
            tenant_id=tenant.id,
            worker_id=fixed.id,
            process_name="针车",
            qualified_qty=1,
        )
    assert exc.value.code == "fixed_salary_no_report"
    assert "不参与生产报工" in exc.value.message


def test_fixed_salary_adds_hourly_overtime_from_attendance(attendance_db):
    db, tenant, fixed, _ = attendance_db
    fixed.base_salary = Decimal("3000")
    fixed.overtime_hourly_rate = Decimal("20")
    fixed.meal_allowance_daily = Decimal("10")
    fixed.housing_allowance_daily = Decimal("20")
    db.add(
        AttendanceDay(
            tenant_id=tenant.id,
            employee_id=fixed.id,
            work_date=date(2026, 9, 1),
            work_minutes=600,
            status="normal",
        )
    )
    db.commit()

    result = month_salary(db, tenant.id, fixed.id, "2026-09")
    from app.services.attendance_rules import is_fixed_rest_day

    rest = sum(1 for day in range(1, 31) if is_fixed_rest_day(date(2026, 9, day), None))
    paid_days = 30 - rest

    assert result["overtime_hours"] == 2.0
    assert result["overtime_hourly_rate"] == 20.0
    assert result["overtime_pay"] == 40.0
    assert result["scheduled_days"] > result["attended_days"] == 1
    assert result["base_salary"] == pytest.approx(3000)
    assert result["leave_days"] == 0
    assert result["meal_allowance"] == pytest.approx(10 * paid_days)
    assert result["housing_allowance"] == pytest.approx(20 * paid_days)
    assert result["allowance_days"] == 30
    assert result["total_wage"] == pytest.approx(result["base_salary"] + 40 + result["meal_allowance"] + result["housing_allowance"])
    assert result["settled_wage"] == 0
    assert result["unsettled_wage"] == pytest.approx(result["total_wage"])


def test_fixed_rest_pay_flags_change_base_and_allowances(attendance_db):
    """休息日没勾工资就从日历里扣掉；补贴只算勾了的休息日。不看出勤。"""
    from app.services.attendance_rules import is_fixed_rest_day

    db, tenant, fixed, _ = attendance_db
    rules = {
        "rest_day_mode": "weekly",
        "weekly_rest_days": [6, 7],
        "rest_pay_salary": False,
        "rest_pay_meal": True,
        "rest_pay_housing": False,
        "rest_pay_other": True,
    }
    tenant.settings_json = {"attendance_rules": rules}
    fixed.base_salary = Decimal("3000")
    fixed.meal_allowance_daily = Decimal("10")
    fixed.housing_allowance_daily = Decimal("20")
    fixed.other_allowance_daily = Decimal("5")
    db.add(
        AttendanceDay(
            tenant_id=tenant.id,
            employee_id=fixed.id,
            work_date=date(2026, 9, 1),
            work_minutes=480,
            status="normal",
        )
    )
    db.commit()

    result = month_salary(db, tenant.id, fixed.id, "2026-09")
    rest = 0
    day = date(2026, 9, 1)
    while day.month == 9:
        if is_fixed_rest_day(day, rules):
            rest += 1
        day += timedelta(days=1)
    assert rest > 0
    assert result["attended_days"] == 1
    assert result["base_salary"] == pytest.approx(100 * (30 - rest))
    assert result["meal_allowance"] == pytest.approx(10 * 30)
    assert result["housing_allowance"] == pytest.approx(20 * (30 - rest))
    assert result["other_allowance"] == pytest.approx(5 * 30)
    assert result["allowance_days"] == 30
    assert f"休息{rest}天不发工资" in result["settle_note"]
    assert f"住宿补¥{20 * (30 - rest):.2f}（20.00/天×{30 - rest}天）" in result["settle_note"]


def test_designated_rest_range_pay_flags(attendance_db):
    """指定休息盖住整天时按该段勾选计薪；只休一部分班次不改当天工资和补贴。"""
    db, tenant, fixed, _ = attendance_db
    tenant.settings_json = {
        "attendance_rules": {
            "rest_day_mode": "weekly",
            "weekly_rest_days": [6, 7],
            "rest_pay_salary": True,
            "work_periods": [
                {"start": "08:00", "end": "12:00"},
                {"start": "13:30", "end": "17:30"},
            ],
            "designated_rest_ranges": [
                {
                    "start": "2026-09-02 00:00",
                    "end": "2026-09-02 23:59",
                    "pay_salary": False,
                    "pay_meal": True,
                    "pay_housing": False,
                    "pay_other": True,
                },
                {
                    "start": "2026-09-03 10:15",
                    "end": "2026-09-03 11:00",
                    "pay_salary": False,
                    "pay_meal": True,
                    "pay_housing": True,
                    "pay_other": True,
                },
            ],
        }
    }
    fixed.base_salary = Decimal("3000")
    fixed.meal_allowance_daily = Decimal("10")
    fixed.housing_allowance_daily = Decimal("20")
    fixed.other_allowance_daily = Decimal("5")
    db.add(
        AttendanceDay(
            tenant_id=tenant.id,
            employee_id=fixed.id,
            work_date=date(2026, 9, 1),
            work_minutes=480,
            status="normal",
        )
    )
    db.commit()

    result = month_salary(db, tenant.id, fixed.id, "2026-09")
    from app.services.attendance_rules import is_fixed_rest_day

    weekends = sum(1 for day in range(1, 31) if is_fixed_rest_day(date(2026, 9, day), {"weekly_rest_days": [6, 7]}))
    assert result["attended_days"] == 1
    assert result["base_salary"] == pytest.approx(100 * 29)
    assert result["meal_allowance"] == pytest.approx(10 * (30 - weekends))
    assert result["housing_allowance"] == pytest.approx(20 * (30 - weekends - 1))
    assert result["other_allowance"] == pytest.approx(5 * (30 - weekends))
    assert "休息1天不发工资" in result["settle_note"]
    assert "出勤" not in result["settle_note"]


def test_leave_half_days_deduct_fixed_salary_by_calendar_rate(attendance_db):
    from app.services.leave_service import leave_day_count, save_leave

    db, tenant, fixed, _ = attendance_db
    fixed.base_salary = Decimal("3000")
    fixed.meal_allowance_daily = Decimal("10")
    db.commit()
    assert leave_day_count(date(2026, 9, 2), "am", date(2026, 9, 2), "am") == Decimal("0.5")
    assert leave_day_count(date(2026, 9, 2), "am", date(2026, 9, 2), "pm") == Decimal("1.0")
    assert leave_day_count(date(2026, 9, 2), "pm", date(2026, 9, 4), "am") == Decimal("2.0")
    save_leave(
        db,
        tenant.id,
        worker_id=fixed.id,
        start_date=date(2026, 9, 2),
        end_date=date(2026, 9, 2),
        start_half="am",
        end_half="am",
        pay_salary=False,
        pay_meal=True,
    )
    save_leave(
        db,
        tenant.id,
        worker_id=fixed.id,
        start_date=date(2026, 9, 3),
        end_date=date(2026, 9, 3),
        start_half="am",
        end_half="pm",
        pay_salary=True,
    )
    result = month_salary(db, tenant.id, fixed.id, "2026-09")
    from app.services.attendance_rules import is_fixed_rest_day

    weekends = sum(1 for day in range(1, 31) if is_fixed_rest_day(date(2026, 9, day), None))
    meal_days = 30 - weekends - 1
    assert result["base_salary"] == pytest.approx(3000)
    assert result["leave_days"] == pytest.approx(1.5)
    assert result["leave_deduction"] == pytest.approx(50)
    assert result["meal_allowance"] == pytest.approx(10 * meal_days)
    assert result["total_wage"] == pytest.approx(3000 - 50 + 10 * meal_days)


def test_allowance_uses_hire_leave_rest_and_leave_flags(attendance_db):
    """餐补、住宿补按入职到离职的日历。休息日和请假没勾对应补贴就不算，不看出勤。"""
    from app.services.leave_service import save_leave

    db, tenant, _fixed, piece = attendance_db
    tenant.settings_json = {
        "attendance_rules": {
            "rest_day_mode": "weekly",
            "weekly_rest_days": [6, 7],
            "rest_pay_meal": False,
            "rest_pay_housing": True,
        }
    }
    piece.meal_allowance_daily = Decimal("10")
    piece.housing_allowance_daily = Decimal("20")
    piece.hire_date = date(2026, 9, 10)
    piece.leave_date = date(2026, 9, 20)
    db.commit()
    save_leave(
        db,
        tenant.id,
        worker_id=piece.id,
        start_date=date(2026, 9, 5),
        end_date=date(2026, 9, 5),
        start_half="am",
        end_half="pm",
        pay_meal=False,
        pay_housing=False,
    )
    save_leave(
        db,
        tenant.id,
        worker_id=piece.id,
        start_date=date(2026, 9, 15),
        end_date=date(2026, 9, 15),
        start_half="am",
        end_half="am",
        pay_meal=False,
        pay_housing=True,
    )
    save_leave(
        db,
        tenant.id,
        worker_id=piece.id,
        start_date=date(2026, 9, 25),
        end_date=date(2026, 9, 25),
        start_half="am",
        end_half="pm",
        pay_meal=True,
        pay_housing=True,
    )
    result = month_salary(db, tenant.id, piece.id, "2026-09")
    # 9/10–9/20 共 11 天。周末 9/12、9/13、9/19、9/20 不发餐补、发住宿补。9/15 上午不发餐补、发住宿补。
    assert result["meal_allowance"] == pytest.approx(10 * (11 - 4 - 0.5))
    assert result["housing_allowance"] == pytest.approx(20 * 11)
    assert "出勤" not in result["settle_note"]


def test_fixed_salary_clips_hire_leave_and_early_settle(attendance_db):
    """入职前、离职后、提前结算日之后不发固定工资，也不扣请假。"""
    from app.services.leave_service import save_leave

    db, tenant, fixed, _ = attendance_db
    fixed.base_salary = Decimal("3000")
    fixed.hire_date = date(2026, 9, 10)
    fixed.leave_date = date(2026, 9, 20)
    db.commit()
    save_leave(
        db,
        tenant.id,
        worker_id=fixed.id,
        start_date=date(2026, 9, 5),
        end_date=date(2026, 9, 5),
        start_half="am",
        end_half="pm",
        pay_salary=False,
    )
    save_leave(
        db,
        tenant.id,
        worker_id=fixed.id,
        start_date=date(2026, 9, 12),
        end_date=date(2026, 9, 12),
        start_half="am",
        end_half="am",
        pay_salary=False,
    )
    save_leave(
        db,
        tenant.id,
        worker_id=fixed.id,
        start_date=date(2026, 9, 25),
        end_date=date(2026, 9, 25),
        start_half="am",
        end_half="pm",
        pay_salary=False,
    )

    full = month_salary(db, tenant.id, fixed.id, "2026-09")
    # 9/10–9/20 共 11 天，日工资 100；只扣在职期间 9/12 上午
    assert full["base_salary"] == pytest.approx(1100)
    assert full["leave_days"] == pytest.approx(0.5)
    assert full["leave_deduction"] == pytest.approx(50)
    assert full["total_wage"] == pytest.approx(1050)

    early = month_salary(db, tenant.id, fixed.id, "2026-09", settle_through=date(2026, 9, 15))
    # 9/10–9/15 共 6 天，请假仍落在窗口内
    assert early["base_salary"] == pytest.approx(600)
    assert early["leave_deduction"] == pytest.approx(50)
    assert early["total_wage"] == pytest.approx(550)

