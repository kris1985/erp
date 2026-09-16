from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import AttendanceDay, Department, Employee, SalaryModel, Tenant
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


def test_fixed_employee_clocks_in_and_out(attendance_db):
    db, tenant, fixed, _ = attendance_db
    first = attendance_service.clock(db, tenant.id, fixed.id, "on_duty")
    assert first["clock_in_at"]
    assert first["clock_out_at"] is None
    assert first["next_punch_type"] == "off_duty"

    second = attendance_service.clock(db, tenant.id, fixed.id, "off_duty")
    assert second["clock_out_at"]
    assert second["status"] == "normal"
    assert second["next_punch_type"] is None

    with pytest.raises(AttendanceError, match="今天已完成上班打卡"):
        attendance_service.clock(db, tenant.id, fixed.id, "on_duty")


def test_piecework_employees_can_also_use_attendance(attendance_db):
    db, tenant, fixed, piece = attendance_db
    attendance_service.clock(db, tenant.id, fixed.id, "on_duty")
    attendance_service.clock(db, tenant.id, piece.id, "on_duty")

    result = attendance_service.list_records(db, tenant.id)
    assert result["total"] == 2
    assert {row["employee_id"] for row in result["items"]} == {fixed.id, piece.id}
    assert {row["department_name"] for row in result["items"]} == {"行政部"}
    department_result = attendance_service.list_records(
        db, tenant.id, department_id=fixed.department_id
    )
    assert department_result["total"] == 2
    assert attendance_service.list_records(db, tenant.id, department_id=999999)["total"] == 0


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

    assert result["overtime_hours"] == 2.0
    assert result["overtime_hourly_rate"] == 20.0
    assert result["overtime_pay"] == 40.0
    assert result["total_wage"] == 3040.0
