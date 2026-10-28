"""请假登记。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services.leave_service import LeaveError, delete_leave, list_leaves, save_leave

router = APIRouter(prefix="/leaves", tags=["leaves"])


class LeaveIn(BaseModel):
    worker_id: int
    start_date: date
    end_date: date
    start_half: str = Field(default="am", description="am | pm")
    end_half: str = Field(default="pm", description="am | pm")
    pay_salary: bool = False
    pay_meal: bool = False
    pay_housing: bool = False
    pay_other: bool = False
    notes: str | None = None


def _http(err: LeaveError) -> HTTPException:
    return HTTPException(status_code=400, detail=err.message)


@router.get("")
def get_leaves(
    worker_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("menu.leaves", "mobile.leaves")),
):
    return ok(list_leaves(db, user.tenant_id, worker_id=worker_id, date_from=date_from, date_to=date_to))


@router.post("")
def create_leave(
    body: LeaveIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.leaves.write", "mobile.leaves.write")),
):
    try:
        return ok(save_leave(db, user.tenant_id, created_by=user.id, **body.model_dump()))
    except LeaveError as err:
        raise _http(err) from err


@router.patch("/{leave_id}")
def update_leave(
    leave_id: int,
    body: LeaveIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.leaves.write", "mobile.leaves.write")),
):
    try:
        return ok(save_leave(db, user.tenant_id, leave_id=leave_id, **body.model_dump()))
    except LeaveError as err:
        raise _http(err) from err


@router.delete("/{leave_id}")
def remove_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_permissions("btn.leaves.write", "mobile.leaves.write")),
):
    try:
        delete_leave(db, user.tenant_id, leave_id)
    except LeaveError as err:
        raise _http(err) from err
    return ok({"id": leave_id})
