from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_employee, require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.api import AttendanceClockRequest
from app.schemas.common import ok
from app.services import attendance_service
from app.services.attendance_service import AttendanceError


router = APIRouter(prefix="/attendance", tags=["attendance"])


def _call(action):
    try:
        return action()
    except AttendanceError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})


@router.get("/today")
def today(
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    return ok(_call(lambda: attendance_service.get_today(db, employee.tenant_id, employee.id)))


@router.post("/clock")
def clock(
    payload: AttendanceClockRequest,
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    return ok(
        _call(
            lambda: attendance_service.clock(
                db, employee.tenant_id, employee.id, payload.punch_type
            )
        )
    )


@router.get("/records")
def records(
    employee_id: int | None = None,
    department_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_roles("admin", "manager")),
):
    return ok(
        attendance_service.list_records(
            db,
            employee.tenant_id,
            employee_id=employee_id,
            department_id=department_id,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/daily-stats")
def daily_stats(
    employee_id: int | None = None,
    department_id: int | None = None,
    work_date: date | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_roles("admin", "manager")),
):
    """报工统计：按报工考勤日期单日查询（不可跨日）。"""
    return ok(
        attendance_service.list_daily_stats(
            db,
            employee.tenant_id,
            employee_id=employee_id,
            department_id=department_id,
            work_date=work_date,
            page=page,
            page_size=page_size,
        )
    )
