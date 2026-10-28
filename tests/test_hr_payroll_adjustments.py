"""发薪加减项：奖惩、预支、迟到扣款、发薪日。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    AttendanceDay,
    Department,
    Employee,
    SalaryAdvance,
    SalaryModel,
    Tenant,
    WorkerAdjustment,
)
from app.services import attendance_rules, hr_service, payroll_settings
from app.services.report_service import ReportError
from app.services.salary_service import (
    export_bank_payroll_csv,
    month_salary,
    set_month_lock,
)


@pytest.fixture()
def hr_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="加减项厂", settings_json={})
    session.add(tenant)
    session.flush()
    dept = Department(tenant_id=tenant.id, name="车间")
    session.add(dept)
    session.flush()
    worker = Employee(
        tenant_id=tenant.id,
        name="张三",
        department_id=dept.id,
        salary_model=SalaryModel.pure_piece,
        base_salary=Decimal("2600"),
        is_active=True,
        bank_account="622200001111",
        bank_name="测试银行",
        bank_account_name="张三",
    )
    session.add(worker)
    session.commit()
    yield session, tenant, worker
    session.close()


def test_reward_and_penalty_in_salary(hr_db):
    db, tenant, worker = hr_db
    ym = "2026-08"
    hr_service.create_adjustment(
        db,
        tenant.id,
        worker_id=worker.id,
        year_month=ym,
        kind="reward",
        category="full_attendance",
        amount=100,
        title="全勤奖",
    )
    hr_service.create_adjustment(
        db,
        tenant.id,
        worker_id=worker.id,
        year_month=ym,
        kind="penalty",
        category="other",
        amount=30,
        title="违纪",
    )
    detail = month_salary(db, tenant.id, worker.id, ym)
    assert detail["reward_total"] == pytest.approx(100)
    assert detail["penalty_total"] == pytest.approx(30)
    assert detail["adjustment_net"] == pytest.approx(70)
    assert detail["total_wage"] == pytest.approx(70)

    set_month_lock(db, tenant.id, ym, locked=True, locked_by=worker.id)
    with pytest.raises(ReportError):
        hr_service.create_adjustment(
            db,
            tenant.id,
            worker_id=worker.id,
            year_month=ym,
            kind="reward",
            amount=10,
        )


def test_advance_repay_and_lock_status(hr_db):
    db, tenant, worker = hr_db
    ym = hr_service.open_advance_month(db, tenant.id)
    adv = hr_service.create_advance(
        db,
        tenant.id,
        worker_id=worker.id,
        amount=200,
        advanced_at=date(2026, 8, 5),
        notes="借支",
    )
    hr_service.create_advance(
        db,
        tenant.id,
        worker_id=worker.id,
        amount=300,
        advanced_at=date(2026, 8, 6),
    )
    assert adv["status"] == "open"
    assert adv["repay_year_month"] is None
    detail = month_salary(db, tenant.id, worker.id, ym)
    assert detail["advance_repay"] == pytest.approx(500)
    assert detail["penalty_total"] == pytest.approx(0)
    assert detail["total_wage"] == pytest.approx(-500)
    assert month_salary(db, tenant.id, worker.id, "2026-01")["advance_repay"] == pytest.approx(0)
    adjustments = db.scalars(
        select(WorkerAdjustment).where(WorkerAdjustment.tenant_id == tenant.id)
    ).all()
    assert adjustments == []
    listed_adv = hr_service.list_advances(db, tenant.id, status="open")
    assert listed_adv["summary"]["open_total"] == pytest.approx(500)
    assert listed_adv["summary"]["count"] == 2

    set_month_lock(db, tenant.id, ym, locked=True, locked_by=worker.id)
    row = db.get(SalaryAdvance, adv["id"])
    assert row.status == "repaid"
    assert row.repay_year_month == ym
    assert month_salary(db, tenant.id, worker.id, ym)["advance_repay"] == pytest.approx(500)
    with pytest.raises(ValueError, match="advance_already_repaid"):
        hr_service.void_advance(db, tenant.id, adv["id"])

    set_month_lock(db, tenant.id, ym, locked=False)
    db.refresh(row)
    assert row.status == "open"
    assert row.repay_year_month is None
    assert month_salary(db, tenant.id, worker.id, ym)["advance_repay"] == pytest.approx(500)


def test_advance_does_not_touch_adjustments(hr_db):
    db, tenant, worker = hr_db
    reward_month = "2026-08"
    pay_month = hr_service.open_advance_month(db, tenant.id)
    hr_service.create_adjustment(
        db,
        tenant.id,
        worker_id=worker.id,
        year_month=reward_month,
        kind="reward",
        category="full_attendance",
        amount=100,
    )
    with pytest.raises(ValueError, match="category_invalid"):
        hr_service.create_adjustment(
            db,
            tenant.id,
            worker_id=worker.id,
            year_month=reward_month,
            kind="penalty",
            category="advance_repay",
            amount=50,
        )
    first = hr_service.create_advance(
        db, tenant.id, worker_id=worker.id, amount=200, advanced_at=date(2026, 8, 5)
    )
    hr_service.create_advance(
        db, tenant.id, worker_id=worker.id, amount=50, advanced_at=date(2026, 8, 6)
    )
    later = hr_service.create_advance(
        db, tenant.id, worker_id=worker.id, amount=80, advanced_at=date(2099, 1, 1)
    )
    paid = month_salary(db, tenant.id, worker.id, pay_month)
    assert paid["advance_repay"] == pytest.approx(250)
    assert paid["reward_total"] == pytest.approx(0 if pay_month != reward_month else 100)
    reward = month_salary(db, tenant.id, worker.id, reward_month)
    assert reward["reward_total"] == pytest.approx(100)
    assert reward["penalty_total"] == pytest.approx(0)
    if pay_month != reward_month:
        assert reward["advance_repay"] == pytest.approx(0)
    assert [i["category"] for i in reward["adjustments"]] == ["full_attendance"]

    hr_service.void_advance(db, tenant.id, first["id"])
    assert month_salary(db, tenant.id, worker.id, pay_month)["advance_repay"] == pytest.approx(50)
    listed = hr_service.list_adjustments(db, tenant.id, year_month=reward_month)
    assert len(listed["items"]) == 1
    assert listed["summary"]["penalty_total"] == pytest.approx(0)
    assert later["status"] == "open"


def test_rebuild_late_deductions(hr_db):
    db, tenant, worker = hr_db
    ym = "2026-08"
    attendance_rules.save_attendance_rules_patch(
        db,
        tenant.id,
        {
            "late_early_deduction": {
                "enabled": True,
                "grace_minutes": 0,
                "monthly_free_times": 0,
                "mode": "per_minute",
                "amount_per_minute": 1,
            }
        },
    )
    db.add(
        AttendanceDay(
            tenant_id=tenant.id,
            employee_id=worker.id,
            work_date=date(2026, 8, 3),
            late_minutes=20,
            early_leave_minutes=0,
        )
    )
    db.commit()
    result = hr_service.rebuild_late_deductions(db, tenant.id, ym)
    assert result["enabled"] is True
    assert result["workers"] == 1
    assert result["total_amount"] == pytest.approx(20)
    detail = month_salary(db, tenant.id, worker.id, ym)
    assert detail["late_deduction"] == pytest.approx(20)
    assert detail["total_wage"] == pytest.approx(-20)

    # 幂等重算
    hr_service.rebuild_late_deductions(db, tenant.id, ym)
    rows = db.scalars(
        select(WorkerAdjustment).where(
            WorkerAdjustment.tenant_id == tenant.id,
            WorkerAdjustment.source == "auto_late",
        )
    ).all()
    assert len(rows) == 1


def test_payroll_payday_in_bank_export(hr_db):
    db, tenant, worker = hr_db
    ym = "2026-08"
    payroll_settings.save_payroll_patch(db, tenant.id, {"payday": 10})
    hr_service.create_adjustment(
        db,
        tenant.id,
        worker_id=worker.id,
        year_month=ym,
        kind="reward",
        amount=500,
        category="other",
    )
    set_month_lock(db, tenant.id, ym, locked=True, locked_by=worker.id)
    csv_text = export_bank_payroll_csv(db, tenant.id, ym)
    assert "2026-08工资·2026-09-10发" in csv_text
    assert "500.00" in csv_text
