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
    ym = "2026-08"
    adv = hr_service.create_advance(
        db,
        tenant.id,
        worker_id=worker.id,
        amount=200,
        repay_year_month=ym,
        advanced_at=date(2026, 8, 5),
        notes="借支",
    )
    assert adv["status"] == "open"
    detail = month_salary(db, tenant.id, worker.id, ym)
    assert detail["advance_repay"] == pytest.approx(200)
    assert detail["total_wage"] == pytest.approx(-200)

    set_month_lock(db, tenant.id, ym, locked=True, locked_by=worker.id)
    row = db.get(SalaryAdvance, adv["id"])
    assert row.status == "repaid"

    set_month_lock(db, tenant.id, ym, locked=False)
    db.refresh(row)
    assert row.status == "open"


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
