from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AttendanceDay, AttendancePunch, Department, Employee
from app.schemas.common import normalize_page, page_payload


LOCAL_OFFSET = timedelta(hours=8)
PUNCH_TYPES = {"on_duty", "off_duty"}


class AttendanceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _now_utc() -> datetime:
    # 数据库沿用项目现有的无时区 UTC 存储约定。
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _local_date(value: datetime | None = None) -> date:
    return ((value or _now_utc()) + LOCAL_OFFSET).date()


def _local_text(value: datetime | None) -> str | None:
    return (value + LOCAL_OFFSET).strftime("%Y-%m-%d %H:%M:%S") if value else None


def _require_employee(db: Session, tenant_id: int, employee_id: int) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee or employee.tenant_id != tenant_id or not employee.is_active:
        raise AttendanceError("employee_not_found", "员工不存在或未启用")
    return employee


def _day_payload(day: AttendanceDay | None, employee: Employee, work_date: date) -> dict:
    return {
        "eligible": True,
        "employee_id": employee.id,
        "employee_name": employee.name,
        "work_date": work_date.isoformat(),
        "clock_in_at": _local_text(day.clock_in_at) if day else None,
        "clock_out_at": _local_text(day.clock_out_at) if day else None,
        "work_minutes": int(day.work_minutes or 0) if day else 0,
        "status": day.status if day else "not_clocked",
        "next_punch_type": (
            "on_duty" if not day or not day.clock_in_at else "off_duty" if not day.clock_out_at else None
        ),
    }


def get_today(db: Session, tenant_id: int, employee_id: int) -> dict:
    employee = _require_employee(db, tenant_id, employee_id)
    today = _local_date()
    day = db.scalar(
        select(AttendanceDay).where(
            AttendanceDay.tenant_id == tenant_id,
            AttendanceDay.employee_id == employee_id,
            AttendanceDay.work_date == today,
        )
    )
    return _day_payload(day, employee, today)


def _rebuild_day(db: Session, tenant_id: int, employee_id: int, work_date: date) -> AttendanceDay:
    punches = db.scalars(
        select(AttendancePunch)
        .where(
            AttendancePunch.tenant_id == tenant_id,
            AttendancePunch.employee_id == employee_id,
            AttendancePunch.work_date == work_date,
        )
        .order_by(AttendancePunch.check_time.asc())
    ).all()
    clock_ins = [p for p in punches if p.punch_type == "on_duty"]
    clock_outs = [p for p in punches if p.punch_type == "off_duty"]
    clock_in = clock_ins[0].check_time if clock_ins else None
    clock_out = clock_outs[-1].check_time if clock_outs else None
    day = db.scalar(
        select(AttendanceDay).where(
            AttendanceDay.tenant_id == tenant_id,
            AttendanceDay.employee_id == employee_id,
            AttendanceDay.work_date == work_date,
        )
    )
    if not day:
        day = AttendanceDay(tenant_id=tenant_id, employee_id=employee_id, work_date=work_date)
        db.add(day)
    day.clock_in_at = clock_in
    day.clock_out_at = clock_out
    day.work_minutes = max(0, int((clock_out - clock_in).total_seconds() // 60)) if clock_in and clock_out else 0
    day.status = "normal" if clock_in and clock_out else "incomplete"
    day.source_provider = punches[-1].source_provider if punches else "local"
    day.raw_count = len(punches)
    day.last_sync_at = _now_utc()
    db.flush()
    return day


def clock(db: Session, tenant_id: int, employee_id: int, punch_type: str) -> dict:
    employee = _require_employee(db, tenant_id, employee_id)
    if punch_type not in PUNCH_TYPES:
        raise AttendanceError("invalid_punch_type", "打卡类型无效")
    now = _now_utc()
    today = _local_date(now)
    existing = db.scalar(
        select(AttendancePunch).where(
            AttendancePunch.tenant_id == tenant_id,
            AttendancePunch.employee_id == employee_id,
            AttendancePunch.work_date == today,
            AttendancePunch.punch_type == punch_type,
            AttendancePunch.source_provider == "local",
        )
    )
    if existing:
        label = "上班" if punch_type == "on_duty" else "下班"
        raise AttendanceError("already_clocked", f"今天已完成{label}打卡")
    if punch_type == "off_duty":
        clock_in = db.scalar(
            select(AttendancePunch).where(
                AttendancePunch.tenant_id == tenant_id,
                AttendancePunch.employee_id == employee_id,
                AttendancePunch.work_date == today,
                AttendancePunch.punch_type == "on_duty",
            )
        )
        if not clock_in:
            raise AttendanceError("clock_in_required", "请先完成上班打卡")

    db.add(
        AttendancePunch(
            tenant_id=tenant_id,
            employee_id=employee_id,
            work_date=today,
            punch_type=punch_type,
            check_time=now,
            time_result="normal",
            location_result="not_required",
            source_provider="local",
            external_corp_id="",
            external_user_id=str(employee_id),
            external_record_key=f"local:{employee_id}:{today.isoformat()}:{punch_type}",
            source_type="mobile_web",
            raw_payload={"source": "local", "punch_type": punch_type},
        )
    )
    db.flush()
    day = _rebuild_day(db, tenant_id, employee_id, today)
    db.commit()
    db.refresh(day)
    return _day_payload(day, employee, today)


def list_records(
    db: Session,
    tenant_id: int,
    *,
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page, page_size, offset = normalize_page(page, page_size, max_size=500)
    q = (
        select(AttendanceDay, Employee, Department)
        .join(Employee, Employee.id == AttendanceDay.employee_id)
        .outerjoin(Department, Department.id == Employee.department_id)
        .where(
            AttendanceDay.tenant_id == tenant_id,
            Employee.tenant_id == tenant_id,
        )
    )
    if employee_id:
        q = q.where(AttendanceDay.employee_id == employee_id)
    if department_id:
        q = q.where(Employee.department_id == department_id)
    if date_from:
        q = q.where(AttendanceDay.work_date >= date_from)
    if date_to:
        q = q.where(AttendanceDay.work_date <= date_to)
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    rows = db.execute(
        q.order_by(AttendanceDay.work_date.desc(), AttendanceDay.id.desc()).offset(offset).limit(page_size)
    ).all()
    items = [
        {
            "id": day.id,
            "work_date": day.work_date.isoformat(),
            "department_name": department.name if department else None,
            "employee_id": employee.id,
            "employee_name": employee.name,
            "clock_in_at": _local_text(day.clock_in_at),
            "clock_out_at": _local_text(day.clock_out_at),
            "work_minutes": int(day.work_minutes or 0),
            "status": day.status,
            "source_provider": day.source_provider,
        }
        for day, employee, department in rows
    ]
    return page_payload(items, int(total), page, page_size)
