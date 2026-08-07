"""排产建议草稿 API。"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import User
from app.schemas.common import ok
from app.services import schedule_service

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _http(e: schedule_service.ScheduleError):
    code = 400
    if e.code in ("not_found", "line_not_found", "order_not_found"):
        code = 404
    raise HTTPException(status_code=code, detail={"code": e.code, "message": e.message})


class CreateDraftIn(BaseModel):
    order_ids: list[int] = Field(min_length=1)
    note: Optional[str] = None
    process_ids: Optional[list[int]] = None
    days_per_process: int = Field(default=1, ge=1, le=30)


class PatchLineIn(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    included: Optional[bool] = None
    plan_qty: Optional[int] = Field(default=None, ge=1)


class ConfirmIn(BaseModel):
    require_first_kit: bool = True


@router.get("/pool")
def api_schedule_pool(
    keyword: Optional[str] = None,
    rush_only: bool = False,
    hide_first_kit_blocked: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    return ok(
        {
            "items": schedule_service.list_schedule_pool(
                db,
                user.tenant_id,
                keyword=keyword,
                rush_only=rush_only,
                hide_first_kit_blocked=hide_first_kit_blocked,
            )
        }
    )


@router.get("/drafts")
def api_list_drafts(
    status: Optional[str] = "draft",
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok({"items": schedule_service.list_drafts(db, user.tenant_id, status=status)})
    except ValueError:
        raise HTTPException(status_code=400, detail="无效状态")


@router.post("/drafts")
def api_create_draft(
    body: CreateDraftIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            schedule_service.create_draft(
                db,
                user.tenant_id,
                body.order_ids,
                user_id=user.id,
                note=body.note,
                process_ids=body.process_ids,
                days_per_process=body.days_per_process,
            )
        )
    except schedule_service.ScheduleError as e:
        _http(e)


@router.get("/drafts/{draft_id}")
def api_get_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(schedule_service.get_draft(db, user.tenant_id, draft_id))
    except schedule_service.ScheduleError as e:
        _http(e)


@router.patch("/drafts/{draft_id}/lines/{line_id}")
def api_patch_line(
    draft_id: int,
    line_id: int,
    body: PatchLineIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        data = body.model_dump(exclude_unset=True)
        return ok(
            schedule_service.patch_draft_line(
                db, user.tenant_id, draft_id, line_id, **data
            )
        )
    except schedule_service.ScheduleError as e:
        _http(e)


@router.post("/drafts/{draft_id}/confirm")
def api_confirm_draft(
    draft_id: int,
    body: ConfirmIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        require_first = True if body is None else body.require_first_kit
        return ok(
            schedule_service.confirm_draft(
                db,
                user.tenant_id,
                draft_id,
                user_id=user.id,
                require_first_kit=require_first,
            )
        )
    except schedule_service.ScheduleError as e:
        _http(e)


@router.post("/drafts/{draft_id}/discard")
def api_discard_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(schedule_service.discard_draft(db, user.tenant_id, draft_id))
    except schedule_service.ScheduleError as e:
        _http(e)


@router.get("/calendar")
def api_schedule_calendar(
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            schedule_service.list_calendar(
                db, user.tenant_id, date_from=date_from, date_to=date_to
            )
        )
    except schedule_service.ScheduleError as e:
        _http(e)
