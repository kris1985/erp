"""排产建议草稿 API。"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import User
from app.schemas.common import ok, paginate_sequence
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
    auto_assign: bool = True


class PatchLineIn(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    included: Optional[bool] = None
    plan_qty: Optional[int] = Field(default=None, ge=1)


class DraftAssignmentIn(BaseModel):
    worker_id: int
    quota_qty: Optional[int] = Field(default=None, ge=0)
    share_weight: Optional[int] = Field(default=1, ge=0)


class SetAssignmentsIn(BaseModel):
    assignments: list[DraftAssignmentIn] = Field(default_factory=list)
    equal_split: bool = False


class ConfirmIn(BaseModel):
    require_first_kit: bool = True
    apply_assignments: bool = True


@router.get("/pool")
def api_schedule_pool(
    keyword: Optional[str] = None,
    rush_only: bool = False,
    hide_first_kit_blocked: bool = False,
    hide_scheduled: bool = True,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    items = schedule_service.list_schedule_pool(
        db,
        user.tenant_id,
        keyword=keyword,
        rush_only=rush_only,
        hide_first_kit_blocked=hide_first_kit_blocked,
        hide_scheduled=hide_scheduled,
    )
    return ok(paginate_sequence(items, page, page_size, max_size=200))


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
                auto_assign=body.auto_assign,
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


@router.put("/drafts/{draft_id}/lines/{line_id}/assignments")
def api_set_line_assignments(
    draft_id: int,
    line_id: int,
    body: SetAssignmentsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            schedule_service.set_line_assignments(
                db,
                user.tenant_id,
                draft_id,
                line_id,
                [a.model_dump() for a in body.assignments],
                equal_split=body.equal_split,
            )
        )
    except schedule_service.ScheduleError as e:
        _http(e)


@router.post("/drafts/{draft_id}/suggest-assignments")
def api_suggest_assignments(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(schedule_service.suggest_assignments(db, user.tenant_id, draft_id))
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
        apply_assignments = True if body is None else body.apply_assignments
        return ok(
            schedule_service.confirm_draft(
                db,
                user.tenant_id,
                draft_id,
                user_id=user.id,
                require_first_kit=require_first,
                apply_assignments=apply_assignments,
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


class ProposeIn(BaseModel):
    order_ids: Optional[list[int]] = None
    hide_scheduled: bool = True


class InsertSimIn(BaseModel):
    order_id: int


class AdoptProposalIn(BaseModel):
    proposal: dict
    note: Optional[str] = None
    auto_assign: bool = True


class AgentChatIn(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: Optional[str] = None


class AgentMetricQueryIn(BaseModel):
    metric_id: str = Field(min_length=1)
    params: dict = Field(default_factory=dict)


class ScheduleSettingsPatchIn(BaseModel):
    default_process_days: Optional[int] = Field(default=None, ge=1, le=30)
    tight_days: Optional[int] = Field(default=None, ge=0, le=30)
    default_daily_capacity: Optional[int] = Field(default=None, ge=0)
    daily_capacity_by_process: Optional[dict[str, int]] = None


@router.get("/settings")
def api_get_schedule_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_settings as ss

    return ok(ss.get_schedule_by_tenant_id(db, user.tenant_id))


@router.patch("/settings")
def api_patch_schedule_settings(
    body: ScheduleSettingsPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    from app.services import schedule_settings as ss

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无有效更新字段")
    try:
        return ok(ss.save_schedule_patch(db, user.tenant_id, patch))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/proposals")
def api_generate_proposals(
    body: ProposeIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_engine

    body = body or ProposeIn()
    items = schedule_engine.generate_proposals(
        db,
        user.tenant_id,
        order_ids=body.order_ids,
        hide_scheduled=body.hide_scheduled,
    )
    return ok({"items": items, "total": len(items)})


@router.get("/load")
def api_daily_load(
    date_from: date,
    date_to: date,
    include_draft_orders: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_engine

    if date_to < date_from:
        raise HTTPException(status_code=400, detail="date_to 不能早于 date_from")
    if (date_to - date_from).days > 90:
        raise HTTPException(status_code=400, detail="查询跨度不能超过 90 天")
    return ok(
        schedule_engine.daily_load(
            db,
            user.tenant_id,
            date_from=date_from,
            date_to=date_to,
            include_draft_orders=include_draft_orders,
        )
    )


@router.post("/simulate-insert")
def api_simulate_insert(
    body: InsertSimIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_engine

    try:
        items = schedule_engine.simulate_insert(db, user.tenant_id, body.order_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="订单不存在")
    return ok({"items": items, "total": len(items)})


@router.post("/proposals/adopt")
def api_adopt_proposal(
    body: AdoptProposalIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            schedule_service.create_draft_from_proposal(
                db,
                user.tenant_id,
                body.proposal,
                user_id=user.id,
                note=body.note,
                auto_assign=body.auto_assign,
            )
        )
    except schedule_service.ScheduleError as e:
        _http(e)


@router.get("/agent/status")
def api_agent_status(user: User = Depends(require_roles("admin", "manager", "leader"))):
    from app.services import schedule_agent

    return ok(schedule_agent.agent_available())


@router.get("/agent/conversations")
def api_agent_conversations(
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_agent

    return ok({"items": schedule_agent.list_conversations(user.tenant_id)})


@router.get("/agent/conversations/{conversation_id}")
def api_agent_conversation_detail(
    conversation_id: str,
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_agent

    try:
        return ok(schedule_agent.get_conversation_messages(user.tenant_id, conversation_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="对话不存在")


class AgentRenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)


@router.patch("/agent/conversations/{conversation_id}")
def api_agent_rename(
    conversation_id: str,
    body: AgentRenameIn,
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_agent

    try:
        return ok(schedule_agent.rename_conversation(user.tenant_id, conversation_id, body.title))
    except ValueError as e:
        code = 404 if str(e) == "not_found" else 400
        raise HTTPException(status_code=code, detail=str(e)) from e


@router.delete("/agent/conversations/{conversation_id}")
def api_agent_delete(
    conversation_id: str,
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_agent

    try:
        return ok(schedule_agent.delete_conversation(user.tenant_id, conversation_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="对话不存在")


@router.post("/agent/chat")
def api_agent_chat(
    body: AgentChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import rbac_service, schedule_agent

    try:
        perms = rbac_service.get_user_permissions(db, user)
        return ok(
            schedule_agent.chat(
                db,
                user.tenant_id,
                body.message,
                conversation_id=body.conversation_id,
                permission_codes=perms,
            )
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"agent_error: {e}") from e


@router.post("/agent/chat/stream")
def api_agent_chat_stream(
    body: AgentChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """车间军师 SSE 流式输出（text/event-stream）。"""
    from fastapi.responses import StreamingResponse

    from app.services import rbac_service, schedule_agent

    status = schedule_agent.agent_available()
    if not status.get("enabled"):
        raise HTTPException(status_code=503, detail=status.get("reason") or "agent_disabled")
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="empty_message")

    perms = rbac_service.get_user_permissions(db, user)
    return StreamingResponse(
        schedule_agent.iter_chat_sse(
            user.tenant_id,
            message,
            conversation_id=body.conversation_id,
            permission_codes=perms,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/agent/metrics")
def api_agent_metrics(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import rbac_service, workshop_metrics

    perms = rbac_service.get_user_permissions(db, user)
    items = workshop_metrics.list_metrics(permission_codes=perms)
    return ok({"items": items, "total": len(items)})


@router.post("/agent/metrics/query")
def api_agent_metric_query(
    body: AgentMetricQueryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import rbac_service, workshop_metrics

    perms = rbac_service.get_user_permissions(db, user)
    result = workshop_metrics.query_metric(
        db,
        user.tenant_id,
        body.metric_id,
        params=body.params or {},
        permission_codes=perms,
    )
    return ok(result)


@router.get("/agent/memory")
def api_agent_memory(
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_agent

    return ok({"items": schedule_agent.list_memories(user.tenant_id)})

