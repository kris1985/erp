"""捆标追溯 + 不良事件 API。"""

from __future__ import annotations

import io

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_principal, require_roles, Principal
from app.db import get_db
from app.models import Order, TraceUnit, User, WorkLog
from app.schemas.common import normalize_page, ok
from app.services import trace_service
from app.services.trace_service import TraceError

router = APIRouter(tags=["trace"])


class TraceUnitCreate(BaseModel):
    order_no: str | None = None
    order_id: int | None = None
    qty: int = Field(gt=0)
    color_id: int | None = None
    size_id: int | None = None
    worker_id: int | None = None
    process_id: int | None = None
    work_log_id: int | None = None
    note: str | None = None


class DefectEventCreate(BaseModel):
    defect_type: str
    qty: int = Field(gt=0)
    order_no: str | None = None
    order_id: int | None = None
    trace_unit_id: int | None = None
    trace_code: str | None = None
    color_id: int | None = None
    size_id: int | None = None
    found_process_id: int | None = None
    responsible_process_id: int | None = None
    responsible_worker_id: int | None = None
    disposition: str = "rework"
    note: str | None = None
    auto_suggest_worker: bool = True


class DefectEventUpdate(BaseModel):
    status: str | None = None
    disposition: str | None = None
    responsible_worker_id: int | None = None
    note: str | None = None


class ReworkTaskCreate(BaseModel):
    worker_id: int
    process_id: int | None = None
    qty: int | None = Field(default=None, gt=0)
    note: str | None = None


class ReworkTaskComplete(BaseModel):
    close_defect: bool = True
    note: str | None = None


class ReworkTaskCancel(BaseModel):
    note: str | None = None


def _raise(e: TraceError) -> None:
    raise HTTPException(status_code=400, detail=e.message)


def _raise_rework(e) -> None:
    raise HTTPException(status_code=400, detail=e.message)


@router.get("/defect-types")
def list_defect_types():
    return ok({"items": trace_service.DEFECT_TYPES})


@router.post("/trace-units")
def create_trace_unit(
    body: TraceUnitCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    try:
        if body.work_log_id:
            log = db.get(WorkLog, body.work_log_id)
            if not log or log.tenant_id != principal.tenant_id:
                raise HTTPException(status_code=404, detail="报工记录不存在")
            if (
                principal.kind == "worker"
                and principal.worker
                and log.worker_id != principal.worker.id
            ):
                raise HTTPException(status_code=403, detail="只能为自己的报工打捆")
            unit = trace_service.create_bundle_from_work_log(
                db,
                tenant_id=principal.tenant_id,
                work_log_id=body.work_log_id,
                qty=body.qty,
            )
        else:
            order_id = body.order_id
            if not order_id and body.order_no:
                order = db.scalar(
                    select(Order).where(
                        Order.tenant_id == principal.tenant_id,
                        Order.order_no == body.order_no.strip(),
                    )
                )
                if not order:
                    raise HTTPException(status_code=404, detail="订单不存在")
                order_id = order.id
            if not order_id:
                raise HTTPException(status_code=400, detail="请指定订单或报工记录")
            worker_id = body.worker_id
            if principal.kind == "worker" and principal.worker:
                worker_id = principal.worker.id
            unit = trace_service.create_bundle(
                db,
                tenant_id=principal.tenant_id,
                order_id=order_id,
                qty=body.qty,
                color_id=body.color_id,
                size_id=body.size_id,
                worker_id=worker_id,
                process_id=body.process_id,
                note=body.note,
            )
    except TraceError as e:
        _raise(e)
        return
    return ok(trace_service.unit_detail_dict(db, unit))


@router.get("/trace-units/by-code/{code}")
def get_trace_by_code(code: str, db: Session = Depends(get_db)):
    """扫码公开读取捆标详情（报工/登记不良仍需登录）。"""
    unit = trace_service.get_unit_by_code(db, code)
    if not unit:
        raise HTTPException(status_code=404, detail="捆标不存在")
    return ok(trace_service.unit_detail_dict(db, unit))


@router.get("/trace-units/by-code/{code}/qr.png")
def trace_qr_png_by_code(code: str, request: Request, db: Session = Depends(get_db)):
    unit = trace_service.get_unit_by_code(db, code)
    if not unit:
        raise HTTPException(status_code=404, detail="捆标不存在")
    base = str(request.base_url).rstrip("/")
    url = f"{base}/trace/{unit.code}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="trace_{unit.code}.png"'},
    )


@router.get("/trace-units/{unit_id}")
def get_trace_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    unit = db.get(TraceUnit, unit_id)
    if not unit or unit.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="捆标不存在")
    return ok(trace_service.unit_detail_dict(db, unit))


class TraceUnitVoidBody(BaseModel):
    note: str | None = None


@router.post("/trace-units/{unit_id}/void")
def void_trace_unit(
    unit_id: int,
    body: TraceUnitVoidBody | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """B2h-M1：开裁作废主码（无报工流水）。"""
    try:
        unit = trace_service.void_trace_unit(
            db,
            tenant_id=user.tenant_id,
            unit_id=unit_id,
            note=(body.note if body else None),
        )
    except TraceError as e:
        code = 404 if e.code == "trace_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message)
    return ok(trace_service.unit_detail_dict(db, unit))


@router.get("/trace-units/{unit_id}/suggest-responsible")
def suggest_responsible(
    unit_id: int,
    process_id: int = Query(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    unit = db.get(TraceUnit, unit_id)
    if not unit or unit.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="捆标不存在")
    return ok(
        trace_service.suggest_responsible_detail(
            db,
            tenant_id=principal.tenant_id,
            trace_unit_id=unit.id,
            responsible_process_id=process_id,
        )
    )


@router.get("/quality-trace")
def api_quality_trace(
    q: str = Query(..., min_length=1),
    unit_page: int = 1,
    unit_page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """B2g 品质追溯门面：单号 / 捆码 / 不良 ID。"""
    unit_page, unit_page_size, _ = normalize_page(unit_page, unit_page_size)
    try:
        return ok(
            trace_service.quality_trace_lookup(
                db,
                tenant_id=user.tenant_id,
                q=q,
                unit_page=unit_page,
                unit_page_size=unit_page_size,
            )
        )
    except TraceError as e:
        _raise(e)
        return


@router.get("/defect-events")
def list_defect_events(
    order_no: str | None = None,
    responsible_worker_id: int | None = None,
    responsible_process_id: int | None = None,
    defect_type: str | None = None,
    status: str | None = None,
    pending_rework: bool | None = None,
    trace_quality: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    page, page_size, _ = normalize_page(page, page_size)
    return ok(
        trace_service.list_defects(
            db,
            tenant_id=user.tenant_id,
            order_no=order_no,
            responsible_worker_id=responsible_worker_id,
            responsible_process_id=responsible_process_id,
            defect_type=defect_type,
            status=status,
            pending_rework=pending_rework,
            trace_quality=trace_quality,
            page=page,
            page_size=page_size,
        )
    )


@router.post("/defect-events")
def create_defect_event(
    body: DefectEventCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    order_id = body.order_id
    trace_unit_id = body.trace_unit_id
    if body.trace_code and not trace_unit_id:
        unit = trace_service.get_unit_by_code(db, body.trace_code)
        if not unit or unit.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=404, detail="捆标不存在")
        trace_unit_id = unit.id
    if not order_id and body.order_no:
        order = db.scalar(
            select(Order).where(
                Order.tenant_id == principal.tenant_id,
                Order.order_no == body.order_no.strip(),
            )
        )
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")
        order_id = order.id

    found_by_worker_id = None
    found_by_user_id = None
    if principal.kind == "worker" and principal.worker:
        found_by_worker_id = principal.worker.id
    elif principal.user:
        found_by_user_id = principal.user.id

    try:
        event = trace_service.create_defect_event(
            db,
            tenant_id=principal.tenant_id,
            defect_type=body.defect_type,
            qty=body.qty,
            order_id=order_id,
            trace_unit_id=trace_unit_id,
            color_id=body.color_id,
            size_id=body.size_id,
            found_process_id=body.found_process_id,
            responsible_process_id=body.responsible_process_id,
            responsible_worker_id=body.responsible_worker_id,
            disposition=body.disposition,
            found_by_worker_id=found_by_worker_id,
            found_by_user_id=found_by_user_id,
            note=body.note,
            auto_suggest_worker=body.auto_suggest_worker,
        )
    except TraceError as e:
        _raise(e)
        return
    return ok(trace_service.defect_out(db, event))


@router.patch("/defect-events/{defect_id}")
def patch_defect_event(
    defect_id: int,
    body: DefectEventUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        event = trace_service.update_defect(
            db,
            tenant_id=user.tenant_id,
            defect_id=defect_id,
            status=body.status,
            disposition=body.disposition,
            responsible_worker_id=body.responsible_worker_id,
            note=body.note,
            updated_by_user_id=user.id,
        )
    except TraceError as e:
        _raise(e)
        return
    return ok(trace_service.defect_out(db, event))


@router.post("/defect-events/{defect_id}/rework-tasks")
def create_defect_rework_task(
    defect_id: int,
    body: ReworkTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import rework_task_service
    from app.services.rework_task_service import ReworkTaskError

    try:
        return ok(
            rework_task_service.create_rework_task(
                db,
                user.tenant_id,
                defect_id,
                worker_id=body.worker_id,
                process_id=body.process_id,
                qty=body.qty,
                note=body.note,
                created_by=user.id,
            )
        )
    except ReworkTaskError as e:
        _raise_rework(e)
        return


@router.get("/rework-tasks")
def list_rework_tasks(
    status: str | None = Query("pending"),
    order_no: str | None = None,
    worker_id: int | None = None,
    defect_event_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services import rework_task_service
    from app.services.rework_task_service import ReworkTaskError

    try:
        items = rework_task_service.list_rework_tasks(
            db,
            user.tenant_id,
            status=status,
            order_no=order_no,
            worker_id=worker_id,
            defect_event_id=defect_event_id,
        )
    except ReworkTaskError as e:
        _raise_rework(e)
        return
    return ok({"items": items})


@router.post("/rework-tasks/{task_id}/complete")
def complete_rework_task(
    task_id: int,
    body: ReworkTaskComplete | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import rework_task_service
    from app.services.rework_task_service import ReworkTaskError

    body = body or ReworkTaskComplete()
    try:
        return ok(
            rework_task_service.complete_rework_task(
                db,
                user.tenant_id,
                task_id,
                close_defect=body.close_defect,
                note=body.note,
            )
        )
    except ReworkTaskError as e:
        _raise_rework(e)
        return


@router.post("/rework-tasks/{task_id}/cancel")
def cancel_rework_task(
    task_id: int,
    body: ReworkTaskCancel | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import rework_task_service
    from app.services.rework_task_service import ReworkTaskError

    body = body or ReworkTaskCancel()
    try:
        return ok(
            rework_task_service.cancel_rework_task(
                db,
                user.tenant_id,
                task_id,
                note=body.note,
            )
        )
    except ReworkTaskError as e:
        _raise_rework(e)
        return
