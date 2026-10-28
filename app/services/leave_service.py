"""请假登记：上午、下午按半天计，重叠的半天只算一次。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Employee, LeaveRecord

HALF = Decimal("0.5")
_HALVES = ("am", "pm")


class LeaveError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def leave_halves(
    start_date: date,
    start_half: str,
    end_date: date,
    end_half: str,
) -> list[tuple[date, str]]:
    """闭区间内的上午、下午。同一天只选上午或只选下午是半天，上午到下午是一天。"""
    if start_half not in _HALVES or end_half not in _HALVES:
        raise LeaveError("时段只能是上午或下午")
    if end_date < start_date or (start_date == end_date and start_half == "pm" and end_half == "am"):
        raise LeaveError("结束时间不能早于开始时间")
    slots: list[tuple[date, str]] = []
    if start_date == end_date:
        if start_half == end_half:
            return [(start_date, start_half)]
        return [(start_date, "am"), (start_date, "pm")]
    if start_half == "am":
        slots.append((start_date, "am"))
    slots.append((start_date, "pm"))
    day = start_date + timedelta(days=1)
    while day < end_date:
        slots.append((day, "am"))
        slots.append((day, "pm"))
        day += timedelta(days=1)
    slots.append((end_date, "am"))
    if end_half == "pm":
        slots.append((end_date, "pm"))
    return slots


def leave_day_count(start_date: date, start_half: str, end_date: date, end_half: str) -> Decimal:
    return (Decimal(len(leave_halves(start_date, start_half, end_date, end_half))) * HALF).quantize(HALF)


def _worker(db: Session, tenant_id: int, worker_id: int) -> Employee:
    worker = db.get(Employee, worker_id)
    if worker is None or worker.tenant_id != tenant_id:
        raise LeaveError("员工不存在")
    return worker


def _dump(row: LeaveRecord, worker_name: str | None = None) -> dict:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "worker_name": worker_name,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "start_half": row.start_half,
        "end_half": row.end_half,
        "days": float(row.days or 0),
        "pay_salary": bool(row.pay_salary),
        "pay_meal": bool(row.pay_meal),
        "pay_housing": bool(row.pay_housing),
        "pay_other": bool(row.pay_other),
        "notes": row.notes or "",
    }


def list_leaves(
    db: Session,
    tenant_id: int,
    *,
    worker_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    q = select(LeaveRecord).where(LeaveRecord.tenant_id == tenant_id)
    if worker_id is not None:
        q = q.where(LeaveRecord.worker_id == worker_id)
    if date_from is not None:
        q = q.where(LeaveRecord.end_date >= date_from)
    if date_to is not None:
        q = q.where(LeaveRecord.start_date <= date_to)
    rows = db.scalars(q.order_by(LeaveRecord.start_date.desc(), LeaveRecord.id.desc())).all()
    names = {
        worker.id: worker.name
        for worker in db.scalars(
            select(Employee).where(Employee.id.in_({row.worker_id for row in rows}))
        ).all()
    } if rows else {}
    return [_dump(row, names.get(row.worker_id)) for row in rows]


def save_leave(
    db: Session,
    tenant_id: int,
    *,
    worker_id: int,
    start_date: date,
    end_date: date,
    start_half: str,
    end_half: str,
    pay_salary: bool = False,
    pay_meal: bool = False,
    pay_housing: bool = False,
    pay_other: bool = False,
    notes: str | None = None,
    created_by: int | None = None,
    leave_id: int | None = None,
) -> dict:
    _worker(db, tenant_id, worker_id)
    days = leave_day_count(start_date, start_half, end_date, end_half)
    if leave_id is None:
        row = LeaveRecord(
            tenant_id=tenant_id,
            worker_id=worker_id,
            created_by=created_by,
        )
        db.add(row)
    else:
        row = db.get(LeaveRecord, leave_id)
        if row is None or row.tenant_id != tenant_id:
            raise LeaveError("请假记录不存在")
    row.worker_id = worker_id
    row.start_date = start_date
    row.end_date = end_date
    row.start_half = start_half
    row.end_half = end_half
    row.days = days
    row.pay_salary = bool(pay_salary)
    row.pay_meal = bool(pay_meal)
    row.pay_housing = bool(pay_housing)
    row.pay_other = bool(pay_other)
    row.notes = (notes or "").strip() or None
    db.commit()
    db.refresh(row)
    worker = db.get(Employee, row.worker_id)
    return _dump(row, worker.name if worker else None)


def delete_leave(db: Session, tenant_id: int, leave_id: int) -> None:
    row = db.get(LeaveRecord, leave_id)
    if row is None or row.tenant_id != tenant_id:
        raise LeaveError("请假记录不存在")
    db.delete(row)
    db.commit()


def leave_pay_in_period(
    db: Session,
    tenant_id: int,
    worker_id: int,
    period_start: date,
    period_end: date,
) -> dict:
    """窗口内的请假天数。同一半天多条记录只计一次；有一条照发工资就不扣这半天。"""
    empty = {
        "leave_days": Decimal("0"),
        "unpaid_days": Decimal("0"),
        "meal_days": Decimal("0"),
        "housing_days": Decimal("0"),
        "other_days": Decimal("0"),
        "halves": [],
    }
    if period_start > period_end:
        return empty
    rows = db.scalars(
        select(LeaveRecord).where(
            LeaveRecord.tenant_id == tenant_id,
            LeaveRecord.worker_id == worker_id,
            LeaveRecord.end_date >= period_start,
            LeaveRecord.start_date <= period_end,
        )
    ).all()
    slots: dict[tuple[date, str], dict[str, bool]] = {}
    for row in rows:
        try:
            halves = leave_halves(row.start_date, row.start_half, row.end_date, row.end_half)
        except LeaveError:
            continue
        for day, half in halves:
            if day < period_start or day > period_end:
                continue
            flag = slots.setdefault(
                (day, half),
                {"pay_salary": False, "pay_meal": False, "pay_housing": False, "pay_other": False},
            )
            flag["pay_salary"] = flag["pay_salary"] or bool(row.pay_salary)
            flag["pay_meal"] = flag["pay_meal"] or bool(row.pay_meal)
            flag["pay_housing"] = flag["pay_housing"] or bool(row.pay_housing)
            flag["pay_other"] = flag["pay_other"] or bool(row.pay_other)
    leave_days = unpaid = meal = housing = other = Decimal("0")
    for flag in slots.values():
        leave_days += HALF
        if not flag["pay_salary"]:
            unpaid += HALF
        if flag["pay_meal"]:
            meal += HALF
        if flag["pay_housing"]:
            housing += HALF
        if flag["pay_other"]:
            other += HALF
    halves = [
        {"date": day, "half": half, **flag}
        for (day, half), flag in slots.items()
    ]
    return {
        "leave_days": leave_days,
        "unpaid_days": unpaid,
        "meal_days": meal,
        "housing_days": housing,
        "other_days": other,
        "halves": halves,
    }
