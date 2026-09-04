"""为现有工厂生成少量考勤演示数据；按来源键去重，可重复执行。"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import AttendanceDay, AttendancePunch, Employee, SalaryModel


LOCAL_OFFSET = timedelta(hours=8)


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def salary_value(employee: Employee) -> str:
    return employee.salary_model.value if hasattr(employee.salary_model, "value") else str(employee.salary_model)


def main() -> None:
    AttendancePunch.__table__.create(bind=engine, checkfirst=True)
    AttendanceDay.__table__.create(bind=engine, checkfirst=True)

    db = SessionLocal()
    try:
        employees = db.scalars(
            select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.id.asc())
        ).all()
        pieceworkers = [e for e in employees if salary_value(e) != SalaryModel.fixed.value][:2]
        fixed_workers = [e for e in employees if salary_value(e) == SalaryModel.fixed.value][:1]
        selected = pieceworkers + fixed_workers
        if not selected:
            print("没有可生成考勤数据的在职员工")
            return

        today_local = (now_utc() + LOCAL_OFFSET).date()
        inserted_days = 0
        inserted_punches = 0
        for employee_index, employee in enumerate(selected):
            for days_ago in (1, 2, 3):
                work_date = today_local - timedelta(days=days_ago)
                in_local = datetime.combine(work_date, time(8, 5 + employee_index * 4))
                out_local = datetime.combine(work_date, time(17, 35 + employee_index * 5))
                in_utc = in_local - LOCAL_OFFSET
                out_utc = out_local - LOCAL_OFFSET
                punches = (
                    ("on_duty", in_utc),
                    ("off_duty", out_utc),
                )
                for punch_type, check_time in punches:
                    key = f"demo:{employee.id}:{work_date.isoformat()}:{punch_type}"
                    exists = db.scalar(
                        select(AttendancePunch.id).where(
                            AttendancePunch.tenant_id == employee.tenant_id,
                            AttendancePunch.source_provider == "local",
                            AttendancePunch.external_corp_id == "",
                            AttendancePunch.external_record_key == key,
                        )
                    )
                    if exists:
                        continue
                    db.add(
                        AttendancePunch(
                            tenant_id=employee.tenant_id,
                            employee_id=employee.id,
                            work_date=work_date,
                            punch_type=punch_type,
                            check_time=check_time,
                            time_result="normal",
                            location_result="not_required",
                            source_provider="local",
                            external_corp_id="",
                            external_user_id=str(employee.id),
                            external_record_key=key,
                            source_type="demo_seed",
                            raw_payload={"source": "demo_seed"},
                        )
                    )
                    inserted_punches += 1

                day = db.scalar(
                    select(AttendanceDay).where(
                        AttendanceDay.tenant_id == employee.tenant_id,
                        AttendanceDay.employee_id == employee.id,
                        AttendanceDay.work_date == work_date,
                    )
                )
                if not day:
                    day = AttendanceDay(
                        tenant_id=employee.tenant_id,
                        employee_id=employee.id,
                        work_date=work_date,
                    )
                    db.add(day)
                    inserted_days += 1
                day.clock_in_at = in_utc
                day.clock_out_at = out_utc
                day.work_minutes = int((out_utc - in_utc).total_seconds() // 60)
                day.status = "normal"
                day.source_provider = "local"
                day.raw_count = 2
                day.last_sync_at = now_utc()

        db.commit()
        names = "、".join(e.name for e in selected)
        print(f"已为 {names} 生成演示考勤：新增 {inserted_days} 个考勤日、{inserted_punches} 条打卡流水")
    finally:
        db.close()


if __name__ == "__main__":
    main()
