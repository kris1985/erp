"""排产建议草稿 API。"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok, paginate_sequence
from app.services import schedule_service

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _http(e: schedule_service.ScheduleError):
    code = 400
    if e.code in ("not_found", "line_not_found", "order_not_found", "header_not_found"):
        code = 404
    raise HTTPException(status_code=code, detail={"code": e.code, "message": e.message})


class CreateDraftIn(BaseModel):
    order_ids: list[int] = Field(default_factory=list)
    header_ids: list[int] = Field(default_factory=list)
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
    team_id: Optional[int] = None
    team_mode: str = Field(default="members", description="members=整班成员；leader=仅组长")


class ConfirmIn(BaseModel):
    require_first_kit: bool = True
    apply_assignments: bool = True


@router.get("/pool")
def api_schedule_pool(
    keyword: Optional[str] = None,
    rush_only: bool = False,
    hide_first_kit_blocked: bool = False,
    hide_scheduled: bool = True,
    merge_batch_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    items = schedule_service.list_schedule_pool(
        db,
        user.tenant_id,
        keyword=keyword,
        rush_only=rush_only,
        hide_first_kit_blocked=hide_first_kit_blocked,
        hide_scheduled=hide_scheduled,
        merge_batch_id=merge_batch_id,
    )
    return ok(paginate_sequence(items, page, page_size, max_size=200))


# ----- AU-I3 M1：按款排产 → 执行单 HITL -----


class ExecutionDraftItemIn(BaseModel):
    sales_order_line_item_id: int = Field(gt=0)
    qty: int = Field(gt=0)


class ExecutionDraftCreateIn(BaseModel):
    items: list[ExecutionDraftItemIn] = Field(min_length=1)
    note: str | None = None
    is_rush: bool = False
    split_style_keys: list[str] = Field(default_factory=list)


@router.get("/color-pool")
def api_color_pool(
    own_product_id: int | None = None,
    kit_ready_only: bool = False,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """排产主输入：待排款色码池。"""
    from app.services import execution_schedule_service

    items = execution_schedule_service.list_color_pool(
        db,
        tenant_id=user.tenant_id,
        own_product_id=own_product_id,
        kit_ready_only=kit_ready_only,
    )
    return ok({"items": items, "total": len(items)})


@router.get("/gantt")
def api_schedule_gantt(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """指令甘特：已下发执行单头 × 工作日。草稿条由前端叠在草案 payload 上。"""
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.list_gantt_board(
            db, user.tenant_id, date_from=date_from, date_to=date_to
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code == "draft_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/execution-drafts")
def api_propose_execution_draft(
    body: ExecutionDraftCreateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.propose_draft(
            db,
            tenant_id=user.tenant_id,
            selections=[x.model_dump() for x in body.items],
            note=body.note,
            created_by=user.id,
            is_rush=body.is_rush,
            split_style_keys=body.split_style_keys,
        )
    except ExecutionScheduleError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    return ok(data)


class ExecutionDraftStrategyIn(BaseModel):
    strategy: str = Field(min_length=1)


@router.post("/execution-drafts/{draft_id}/strategy")
def api_select_execution_draft_strategy(
    draft_id: int,
    body: ExecutionDraftStrategyIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.select_draft_strategy(
            db,
            tenant_id=user.tenant_id,
            draft_id=draft_id,
            strategy=body.strategy,
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code == "draft_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


class ExecutionDraftShiftIn(BaseModel):
    job_key: str = Field(min_length=1)
    cut_start: date


class ExecutionDraftDropSourcesIn(BaseModel):
    job_key: str = Field(min_length=1)
    sales_order_ids: list[int] = Field(min_length=1)


@router.post("/execution-drafts/{draft_id}/shift")
def api_shift_execution_draft_job(
    draft_id: int,
    body: ExecutionDraftShiftIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.shift_draft_job(
            db,
            tenant_id=user.tenant_id,
            draft_id=draft_id,
            job_key=body.job_key,
            cut_start=body.cut_start,
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code == "draft_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


class ExecutionDraftProcessWindowIn(BaseModel):
    job_key: str = Field(min_length=1)
    process_id: int = Field(gt=0)
    start_date: Optional[date] = None
    days: Optional[int] = Field(default=None, ge=1, le=180)


@router.post("/execution-drafts/{draft_id}/process-window")
def api_patch_execution_draft_process_window(
    draft_id: int,
    body: ExecutionDraftProcessWindowIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """草稿内单道工序微调：改开始日 / 改天数（其它工序不动）。"""
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.patch_draft_job_process(
            db,
            tenant_id=user.tenant_id,
            draft_id=draft_id,
            job_key=body.job_key,
            process_id=body.process_id,
            start_date=body.start_date,
            days=body.days,
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code in ("draft_not_found", "unknown_job", "unknown_process") else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/execution-drafts/{draft_id}/drop-sources")
def api_drop_execution_draft_sources(
    draft_id: int,
    body: ExecutionDraftDropSourcesIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.drop_draft_sources(
            db,
            tenant_id=user.tenant_id,
            draft_id=draft_id,
            job_key=body.job_key,
            sales_order_ids=body.sales_order_ids,
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code == "draft_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


class GanttShiftIn(BaseModel):
    header_id: int = Field(gt=0)
    cut_start: date


class GanttWithdrawIn(BaseModel):
    header_id: int = Field(gt=0)


@router.post("/gantt-shift")
def api_shift_gantt_header(
    body: GanttShiftIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.shift_issued_header(
            db,
            tenant_id=user.tenant_id,
            header_id=body.header_id,
            cut_start=body.cut_start,
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code == "header_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/gantt-withdraw")
def api_withdraw_gantt_header(
    body: GanttWithdrawIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.withdraw_issued_header(
            db,
            tenant_id=user.tenant_id,
            header_id=body.header_id,
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code == "header_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


class GanttRushIn(BaseModel):
    header_id: int = Field(gt=0)
    push_workdays: int = Field(default=3, ge=1, le=60)
    reason: str | None = None


@router.post("/gantt-rush/simulate")
def api_simulate_gantt_rush(
    body: GanttRushIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.preview_header_rush(
            db,
            tenant_id=user.tenant_id,
            header_id=body.header_id,
            push_workdays=body.push_workdays,
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code in ("header_not_found", "draft_not_found") else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/gantt-rush/confirm")
def api_confirm_gantt_rush(
    body: GanttRushIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.confirm_header_rush(
            db,
            tenant_id=user.tenant_id,
            header_id=body.header_id,
            push_workdays=body.push_workdays,
            reason=body.reason,
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code in ("header_not_found", "draft_not_found") else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/confirm-production")
def api_confirm_production(
    body: ExecutionDraftCreateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """已停用：禁止出方案并立刻确认以跳过计划。请用草案 + 确认方案。"""
    raise HTTPException(
        status_code=400,
        detail="请先在排产出方案、看工序窗后再确认。禁止一键跳过计划直接下发。",
    )


@router.get("/execution-drafts/{draft_id}")
def api_get_execution_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        row = execution_schedule_service.get_draft(db, user.tenant_id, draft_id)
        return ok(execution_schedule_service._draft_out(row))
    except ExecutionScheduleError as e:
        code = 404 if e.code == "draft_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e


class ExecutionDraftConfirmIn(BaseModel):
    """确认下发：可选携带派工 {job_key: {process_id: [worker_id]}}。"""

    dispatch: dict | None = None


@router.post("/execution-drafts/{draft_id}/confirm")
def api_confirm_execution_draft(
    draft_id: int,
    body: ExecutionDraftConfirmIn | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.confirm_draft(
            db,
            tenant_id=user.tenant_id,
            draft_id=draft_id,
            created_by=user.id,
            dispatch=(body.dispatch if body else None),
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code == "draft_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/execution-drafts/{draft_id}/discard")
def api_discard_execution_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        data = execution_schedule_service.discard_draft(
            db, tenant_id=user.tenant_id, draft_id=draft_id
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code == "draft_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


class RushInsertIn(BaseModel):
    execution_id: int = Field(gt=0)
    push_days: int = Field(default=3, ge=1, le=60)
    reason: str | None = None


@router.post("/execution-rush/simulate")
def api_simulate_execution_rush(
    body: RushInsertIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """AU-I3 M2：急单冲击仿真（未开工延后，已开工冻结）。"""
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        return ok(
            execution_schedule_service.simulate_rush_insert(
                db,
                tenant_id=user.tenant_id,
                execution_id=body.execution_id,
                push_days=body.push_days,
            )
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code == "execution_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e


@router.post("/execution-rush/confirm")
def api_confirm_execution_rush(
    body: RushInsertIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """AU-I3 M2：确认急单冲击（非静默）。"""
    from app.services import execution_schedule_service
    from app.services.execution_schedule_service import ExecutionScheduleError

    try:
        return ok(
            execution_schedule_service.confirm_rush_insert(
                db,
                tenant_id=user.tenant_id,
                execution_id=body.execution_id,
                push_days=body.push_days,
                reason=body.reason,
                created_by=user.id,
            )
        )
    except ExecutionScheduleError as e:
        code = 404 if e.code in ("execution_not_found", "peer_not_found") else 400
        raise HTTPException(status_code=code, detail=e.message) from e


@router.get("/drafts")
def api_list_drafts(
    status: Optional[str] = "draft",
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok({"items": schedule_service.list_drafts(db, user.tenant_id, status=status)})
    except ValueError:
        raise HTTPException(status_code=400, detail="无效状态")


@router.post("/drafts")
def api_create_draft(
    body: CreateDraftIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        return ok(
            schedule_service.create_draft(
                db,
                user.tenant_id,
                body.order_ids,
                header_ids=body.header_ids,
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
                team_id=body.team_id,
                team_mode=body.team_mode or "members",
            )
        )
    except schedule_service.ScheduleError as e:
        _http(e)


@router.post("/drafts/{draft_id}/suggest-assignments")
def api_suggest_assignments(
    draft_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    header_ids: Optional[list[int]] = None
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
    allow_schedule_on_non_workdays: Optional[bool] = None
    schedule_blackout_dates: Optional[list[dict]] = None
    merge_delivery_window_days: Optional[int] = Field(default=None, ge=0, le=60)
    merge_require_same_color: Optional[bool] = None
    merge_min_qty: Optional[int] = Field(default=None, ge=0)
    load_warn_utilization: Optional[float] = Field(default=None, ge=0.1, le=2.0)


@router.get("/settings")
def api_get_schedule_settings(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_settings as ss

    return ok(ss.get_schedule_by_tenant_id(db, user.tenant_id))


@router.patch("/settings")
def api_patch_schedule_settings(
    body: ScheduleSettingsPatchIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_engine

    body = body or ProposeIn()
    pack = schedule_engine.generate_proposals(
        db,
        user.tenant_id,
        order_ids=body.order_ids,
        header_ids=body.header_ids,
        hide_scheduled=body.hide_scheduled,
    )
    return ok(
        {
            "items": pack.get("items") or [],
            "total": len(pack.get("items") or []),
            "scope": pack.get("scope") or {},
        }
    )


@router.get("/load")
def api_daily_load(
    date_from: date,
    date_to: date,
    include_draft_orders: bool = True,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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


@router.get("/load/weekly")
def api_weekly_load(
    weeks: int = Query(4, ge=1, le=12),
    include_draft_orders: bool = True,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """P1-1：自然周负荷汇总（本周/下周超载天数）。"""
    from app.services import schedule_engine

    return ok(
        schedule_engine.weekly_load(
            db,
            user.tenant_id,
            weeks=weeks,
            include_draft_orders=include_draft_orders,
        )
    )


@router.post("/simulate-insert")
def api_simulate_insert(
    body: InsertSimIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
def api_agent_status(user: Employee = Depends(require_roles("admin", "manager", "leader"))):
    from app.services import schedule_agent

    return ok(schedule_agent.agent_available())


@router.get("/agent/conversations")
def api_agent_conversations(
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_agent

    return ok({"items": schedule_agent.list_conversations(user.tenant_id)})


@router.get("/agent/conversations/{conversation_id}")
def api_agent_conversation_detail(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import rbac_service, schedule_agent

    try:
        return ok(
            schedule_agent.get_conversation_messages(
                user.tenant_id,
                conversation_id,
                permission_codes=rbac_service.get_user_permissions(db, user),
            )
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="对话不存在")


class AgentRenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)


@router.patch("/agent/conversations/{conversation_id}")
def api_agent_rename(
    conversation_id: str,
    body: AgentRenameIn,
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import rbac_service, workshop_metrics

    perms = rbac_service.get_user_permissions(db, user)
    items = workshop_metrics.list_metrics(permission_codes=perms)
    return ok({"items": items, "total": len(items)})


@router.post("/agent/metrics/query")
def api_agent_metric_query(
    body: AgentMetricQueryIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
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
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import schedule_agent

    return ok({"items": schedule_agent.list_memories(user.tenant_id)})
