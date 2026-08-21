"""AU-I1：规格执行单 / 可产合单 API。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_employee, require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services import execution_service
from app.services.execution_service import ExecutionError

router = APIRouter(prefix="/executions", tags=["executions"])


class ExecutionAllocIn(BaseModel):
    sales_order_line_item_id: int
    qty: int = Field(gt=0)


class ExecutionCreateIn(BaseModel):
    items: list[ExecutionAllocIn]
    notes: str | None = None
    delivery_date: date | None = None


class ExecutionChangeQtyIn(BaseModel):
    items: list[ExecutionAllocIn]
    notes: str | None = None
    dry_run: bool = False


class ExecutionChangeSizeIn(BaseModel):
    size_id: int = Field(gt=0)


class ExecutionSupplementIn(BaseModel):
    items: list[ExecutionAllocIn]
    notes: str | None = None
    delivery_date: date | None = None


class StyleExecutionCreateIn(BaseModel):
    items: list[ExecutionAllocIn]
    notes: str | None = None
    delivery_date: date | None = None
    supplement: bool = False
    max_delivery_gap_days: int | None = Field(default=None, ge=0, le=60)


class ExecutionReorderPreviewIn(BaseModel):
    ordered_header_ids: list[int] = Field(min_length=1, max_length=200)


class ExecutionReorderConfirmIn(ExecutionReorderPreviewIn):
    base_header_ids: list[int] = Field(min_length=1, max_length=200)


class HeaderProcessAssignIn(BaseModel):
    worker_ids: list[int] = Field(default_factory=list)
    team_id: int | None = None


class HeaderCutCardsIn(BaseModel):
    target_qty_by_size: dict[int, int] | None = None
    new_batch: bool = False
    report_ids: list[int] = Field(default_factory=list)


@router.get("/producible")
def api_producible(
    own_product_id: int | None = None,
    kit_ready_only: bool = False,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    items = execution_service.list_producible(
        db,
        tenant_id=user.tenant_id,
        own_product_id=own_product_id,
        kit_ready_only=kit_ready_only,
    )
    return ok({"items": items, "total": len(items)})


def _kit_flag(item: dict, key: str) -> bool | None:
    kit = item.get("kit") or {}
    if kit.get("empty_bom") or kit.get(key) is None:
        return None
    return bool(kit.get(key))


def _kit_list_payload(raw: dict | None) -> dict | None:
    if not raw:
        return None
    return {
        "kit_ok": bool(raw.get("kit_ok")),
        "shortage_lines": raw.get("shortage_lines"),
        "empty_bom": bool(raw.get("empty_bom")),
        "first_kit_ok": bool(raw.get("first_kit_ok")),
        "material_status": raw.get("material_status"),
        "header_id": raw.get("header_id"),
        "header_no": raw.get("header_no"),
        "shop_order_id": raw.get("shop_order_id"),
    }


@router.get("")
def api_list_executions(
    status: str | None = None,
    q: str | None = Query(None, description="生产单号/款号/销售单/客户"),
    kit_ok: bool | None = None,
    first_kit_ok: bool | None = None,
    risk_level: str | None = Query(None, pattern="^(normal|attention|high|late)$"),
    exception_type: str | None = Query(None, pattern="^(progress_lag|unassigned)$"),
    is_rush: bool | None = None,
    delivery_from: date | None = None,
    delivery_to: date | None = None,
    sort_by: str | None = Query(
        None,
        description="execution_no|product_code|progress|delivery_date|created_at|is_rush",
    ),
    sort_order: str | None = Query(None, description="asc|desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """默认按执行单头列表（方案 C）；码明细见 size_lines。"""
    has_client_filter = (
        kit_ok is not None
        or first_kit_ok is not None
        or risk_level is not None
        or exception_type is not None
    )
    try:
        total_before_kit = execution_service.count_execution_headers(
            db,
            tenant_id=user.tenant_id,
            status=status,
            q=q,
            is_rush=is_rush,
            delivery_from=delivery_from,
            delivery_to=delivery_to,
        )
        rows = execution_service.list_execution_headers(
            db,
            tenant_id=user.tenant_id,
            status=status,
            q=q,
            is_rush=is_rush,
            delivery_from=delivery_from,
            delivery_to=delivery_to,
            sort_by=sort_by,
            sort_order=sort_order,
            offset=0 if has_client_filter else (page - 1) * page_size,
            limit=max(1, total_before_kit) if has_client_filter else page_size,
        )
    except ExecutionError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    items_by_id = execution_service._headers_out_batch(db, rows, include_kit=False)
    items = [items_by_id[r.id] for r in rows]
    from app.services.material_service import header_kit_summaries

    kit_map = header_kit_summaries(db, user.tenant_id, [r.id for r in rows])
    row_by_id = {int(row.id): row for row in rows}
    for item in items:
        item_id = int(item["id"])
        item["kit"] = _kit_list_payload(kit_map.get(item_id))
        item["risk"] = execution_service._header_risk_summary(
            row_by_id[item_id],
            list(item.get("process_progress") or []),
            item["kit"],
        )
    if kit_ok is not None:
        items = [x for x in items if _kit_flag(x, "kit_ok") is kit_ok]
    if first_kit_ok is not None:
        items = [x for x in items if _kit_flag(x, "first_kit_ok") is first_kit_ok]
    if risk_level is not None:
        items = [x for x in items if (x.get("risk") or {}).get("level") == risk_level]
    if exception_type == "progress_lag":
        items = [x for x in items if bool((x.get("risk") or {}).get("progress_lag"))]
    elif exception_type == "unassigned":
        items = [x for x in items if bool((x.get("risk") or {}).get("unassigned_exception"))]
    total = len(items) if has_client_filter else total_before_kit
    if has_client_filter:
        start = (page - 1) * page_size
        items = items[start : start + page_size]
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "view": "headers",
        }
    )


@router.get("/risk-stats")
def api_execution_risk_stats(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """生产单页顶部决策摘要；只统计未结束生产单。"""
    from datetime import timedelta

    from app.services import execution_schedule_service
    from app.services.material_service import header_kit_summaries

    total = execution_service.count_execution_headers(db, tenant_id=user.tenant_id)
    rows = execution_service.list_execution_headers(
        db, tenant_id=user.tenant_id, limit=max(1, total)
    )
    active = [
        row
        for row in rows
        if (row.status.value if hasattr(row.status, "value") else str(row.status))
        not in {"completed", "cancelled"}
    ]
    items_by_id = execution_service._headers_out_batch(db, active, include_kit=False)
    kit_map = header_kit_summaries(db, user.tenant_id, [row.id for row in active])
    counts = {"late": 0, "high": 0, "attention": 0, "normal": 0}
    shortage = 0
    progress_lag = 0
    unassigned = 0
    due_7_days = 0
    today = date.today()
    due_to = today + timedelta(days=7)
    for row in active:
        item = items_by_id[row.id]
        kit = _kit_list_payload(kit_map.get(int(row.id)))
        risk = execution_service._header_risk_summary(
            row, list(item.get("process_progress") or []), kit
        )
        level = str(risk.get("level") or "normal")
        counts[level] = counts.get(level, 0) + 1
        if risk.get("progress_lag"):
            progress_lag += 1
        if risk.get("unassigned_exception"):
            unassigned += 1
        if kit and not kit.get("empty_bom") and kit.get("kit_ok") is False:
            shortage += 1
        if row.delivery_date and today <= row.delivery_date <= due_to:
            due_7_days += 1
    overloaded_processes = 0
    try:
        staffing = execution_schedule_service.suggest_staffing(
            db, tenant_id=user.tenant_id, days=14
        )
        overloaded_processes = sum(
            1 for item in staffing.get("items") or [] if int(item.get("over_capacity_days") or 0) > 0
        )
    except Exception:
        overloaded_processes = 0
    return ok(
        {
            "active": len(active),
            "by_level": counts,
            "shortage": shortage,
            "due_7_days": due_7_days,
            "progress_lag": progress_lag,
            "unassigned": unassigned,
            "overloaded_processes": overloaded_processes,
            "as_of": today.isoformat(),
        }
    )


@router.post("/reorder/preview")
def api_preview_execution_reorder(
    body: ExecutionReorderPreviewIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service

    try:
        data = execution_schedule_service.simulate_execution_reorder(
            db,
            tenant_id=user.tenant_id,
            ordered_header_ids=body.ordered_header_ids,
        )
    except execution_schedule_service.ExecutionScheduleError as e:
        raise HTTPException(status_code=409, detail=e.message) from e
    return ok(data)


@router.post("/reorder/confirm")
def api_confirm_execution_reorder(
    body: ExecutionReorderConfirmIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import execution_schedule_service

    try:
        data = execution_schedule_service.confirm_execution_reorder(
            db,
            tenant_id=user.tenant_id,
            ordered_header_ids=body.ordered_header_ids,
            base_header_ids=body.base_header_ids,
        )
    except execution_schedule_service.ExecutionScheduleError as e:
        raise HTTPException(status_code=409, detail=e.message) from e
    return ok(data)


@router.get("/staffing-advice")
def api_staffing_advice(
    days: int = Query(14, ge=7, le=45),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """根据当前已下发生产单负荷，给出加人 / 减人 / 加班建议。"""
    from app.services import execution_schedule_service

    data = execution_schedule_service.suggest_staffing(
        db, tenant_id=user.tenant_id, days=days
    )
    return ok(data)


@router.get("/status-stats")
def api_execution_status_stats(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """按状态统计生产单数量（待开裁/已开裁/生产中/已完成/已取消）。"""
    return ok(execution_service.count_execution_headers_by_status(db, user.tenant_id))


@router.get("/size-lines")
def api_list_execution_size_lines(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """码明细平铺（调试/兼容）。"""
    rows = execution_service.list_executions(
        db, tenant_id=user.tenant_id, status=status, limit=limit
    )
    return ok(
        {
            "items": [execution_service.execution_out(db, r) for r in rows],
            "total": len(rows),
            "view": "size_lines",
        }
    )


@router.get("/headers/{header_id}")
def api_get_execution_header(
    header_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        header = execution_service.get_execution_header(db, user.tenant_id, header_id)
    except ExecutionError as e:
        raise HTTPException(status_code=404, detail=e.message) from e
    return ok(execution_service.header_out(db, header))


@router.post("/headers")
def api_create_style_header(
    body: StyleExecutionCreateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """已停用：紧急合单 / 补码须走排产确认，禁止无工序窗直接落执行单。"""
    raise HTTPException(
        status_code=400,
        detail="请走「生产 → 排产」出方案并确认。紧急合单请在本页勾选后跳转排产；禁止无工序窗直接生成生产单。",
    )


class HeaderAllocateIn(BaseModel):
    qty: float = Field(gt=0)


@router.get("/headers/{header_id}/materials")
def api_header_materials(
    header_id: int,
    include_shared: bool | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """去桥接：执行单头齐套/用料。"""
    from app.services import material_service

    try:
        data = material_service.get_header_kit(
            db, user.tenant_id, header_id, include_shared=include_shared
        )
    except material_service.MaterialError as e:
        code = 404 if e.code in ("header_not_found", "order_not_found") else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/headers/{header_id}/materials/{req_id}/allocate")
def api_header_allocate_material(
    header_id: int,
    req_id: int,
    body: HeaderAllocateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from decimal import Decimal

    from app.services import inventory_settings, material_service

    inv = inventory_settings.get_inventory_by_tenant_id(db, user.tenant_id)
    if not inventory_settings.has_capability(inv, "allocate_ui"):
        raise HTTPException(status_code=403, detail="capability_disabled:allocate_ui")
    try:
        return ok(
            material_service.allocate_from_pool_for_header(
                db,
                user.tenant_id,
                header_id,
                req_id,
                Decimal(str(body.qty)),
                user_id=user.id,
            )
        )
    except material_service.MaterialError as e:
        code = 404 if e.code in ("header_not_found", "not_found") else 400
        raise HTTPException(status_code=code, detail=e.message) from e


@router.post("/headers/{header_id}/materials/{req_id}/deallocate")
def api_header_deallocate_material(
    header_id: int,
    req_id: int,
    body: HeaderAllocateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from decimal import Decimal

    from app.services import inventory_settings, material_service

    inv = inventory_settings.get_inventory_by_tenant_id(db, user.tenant_id)
    if not inventory_settings.has_capability(inv, "allocate_ui"):
        raise HTTPException(status_code=403, detail="capability_disabled:allocate_ui")
    try:
        return ok(
            material_service.deallocate_to_pool_for_header(
                db,
                user.tenant_id,
                header_id,
                req_id,
                Decimal(str(body.qty)),
                user_id=user.id,
            )
        )
    except material_service.MaterialError as e:
        code = 404 if e.code in ("header_not_found", "not_found") else 400
        raise HTTPException(status_code=code, detail=e.message) from e


@router.post("/headers/{header_id}/cut-cards")
def api_header_cut_cards(
    header_id: int,
    body: HeaderCutCardsIn | None = None,
    dry_run: bool = True,
    bundle_size: int | None = None,
    only_missing: bool = True,
    mode: str | None = None,
    skip_kit_reason: str | None = None,
    batch_qtys: list[int] | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        data = execution_service.cut_cards_for_header(
            db,
            tenant_id=user.tenant_id,
            header_id=header_id,
            dry_run=dry_run,
            bundle_size=bundle_size,
            only_missing=only_missing,
            mode=mode,
            skip_kit_reason=skip_kit_reason,
            batch_qtys=batch_qtys,
            target_qty_by_size=body.target_qty_by_size if body else None,
            force_new_batch=bool(body and body.new_batch),
            report_ids=body.report_ids if body else None,
        )
    except ExecutionError as e:
        code = 404 if e.code in ("header_not_found",) else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.get("/headers/{header_id}/flow-card")
def api_header_flow_card(
    header_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader", "worker")),
):
    """生产流转卡内容：订单信息(无价格)+做货要求+工艺路线+框列表。"""
    try:
        data = execution_service.flow_card_out(db, user.tenant_id, header_id)
    except ExecutionError as e:
        code = 404 if e.code in ("header_not_found",) else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/headers/{header_id}/start-cutting")
def api_start_cutting(
    header_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """裁断组长确认开裁；只更新状态，不提前生成框码。"""
    try:
        data = execution_service.start_cutting(db, user.tenant_id, header_id)
    except ExecutionError as e:
        code = 404 if e.code == "header_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.get("/headers/{header_id}/cut-batches")
def api_header_cut_batches(
    header_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import batch_service

    execution_service.get_execution_header(db, user.tenant_id, header_id)
    created = batch_service.backfill_missing_batch_material_consumptions(
        db, user.tenant_id, header_id
    )
    if created:
        db.commit()
    return ok(batch_service.list_cut_batches(db, user.tenant_id, header_id))


@router.get("/headers/{header_id}/flow-card/qr.png")
def api_header_flow_card_qr(header_id: int, request: Request):
    """生产流转卡二维码（公开图）：扫后打开成型/包装报工落地页（页内仍需登录）。"""
    import io

    import qrcode
    from fastapi.responses import Response

    if header_id <= 0:
        raise HTTPException(status_code=400, detail="单号无效")
    base = str(request.base_url).rstrip("/")
    url = f"{base}/flow-card/{header_id}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="flow_card_{header_id}.png"'},
    )


@router.get("/headers/{header_id}/trace-units")
def api_header_trace_units(
    header_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """派工选捆 / 打印：按执行单头列追溯单元。"""
    try:
        data = execution_service.list_header_trace_units(db, user.tenant_id, header_id)
    except ExecutionError as e:
        code = 404 if e.code in ("header_not_found",) else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.get("/headers/{header_id}/processes")
def api_header_processes(
    header_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        header = execution_service.get_execution_header(db, user.tenant_id, header_id)
    except ExecutionError as e:
        raise HTTPException(status_code=404, detail=e.message) from e
    return ok(execution_service.header_processes_out(db, header))


@router.patch("/headers/{header_id}/processes/{process_id}/assign")
def api_assign_header_process(
    header_id: int,
    process_id: int,
    body: HeaderProcessAssignIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from app.services import team_service
    from app.services.team_service import TeamError

    try:
        team_service.assert_workers_in_scope(db, user, list(dict.fromkeys(body.worker_ids)))
        if body.team_id is not None and team_service.is_team_scoped(db, user):
            allowed_team_ids = {
                int(item["id"])
                for item in team_service.list_teams(
                    db,
                    user.tenant_id,
                    leader_worker_id=team_service.resolve_leader_worker_id(db, user) or -1,
                )
            }
            if int(body.team_id) not in allowed_team_ids:
                raise TeamError("out_of_team", "只能派工给本人负责的班组")
        data = execution_service.assign_header_process_workers(
            db,
            tenant_id=user.tenant_id,
            header_id=header_id,
            process_id=process_id,
            worker_ids=body.worker_ids,
            team_id=body.team_id,
        )
    except TeamError as e:
        raise HTTPException(status_code=403, detail=e.message) from e
    except ExecutionError as e:
        code = 404 if e.code in ("header_not_found", "process_not_found") else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


class HeaderReleaseIn(BaseModel):
    qty: float = Field(gt=0)
    deduct_shared: bool = False


@router.post("/headers/{header_id}/materials/{req_id}/release")
def api_header_release_material(
    header_id: int,
    req_id: int,
    body: HeaderReleaseIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    from decimal import Decimal

    from app.services import material_service

    try:
        return ok(
            material_service.release_to_workshop(
                db,
                user.tenant_id,
                None,
                req_id,
                Decimal(str(body.qty)),
                deduct_shared=body.deduct_shared,
                user_id=user.id,
                header_id=header_id,
            )
        )
    except material_service.MaterialError as e:
        code = 404 if e.code in ("header_not_found", "not_found") else 400
        raise HTTPException(status_code=code, detail=e.message) from e


@router.post("")
def api_create_execution(
    body: ExecutionCreateIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """已停用：禁止无工序窗直接 create_execution。请走排产确认。"""
    raise HTTPException(
        status_code=400,
        detail="请走「生产 → 排产」出方案并确认后再下发生产单。",
    )


@router.post("/supplement")
def api_supplement_execution(
    body: ExecutionSupplementIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """已停用：补码新单也须带工序窗，请走排产确认。"""
    raise HTTPException(
        status_code=400,
        detail="补码请勾剩余可产量后跳转「排产」出方案确认，须写入工序窗。",
    )


@router.get("/{execution_id}")
def api_get_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        execution = execution_service.get_execution(db, user.tenant_id, execution_id)
    except ExecutionError as e:
        raise HTTPException(status_code=404, detail=e.message) from e
    return ok(execution_service.execution_out(db, execution))


@router.post("/{execution_id}/change-qty")
def api_change_execution_qty(
    execution_id: int,
    body: ExecutionChangeQtyIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """AU-I3 M3：未开工改量（dry_run 可预览）。"""
    try:
        data = execution_service.change_execution_qty(
            db,
            tenant_id=user.tenant_id,
            execution_id=execution_id,
            items=[x.model_dump() for x in body.items],
            notes=body.notes,
            dry_run=body.dry_run,
            user_id=user.id,
        )
    except ExecutionError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/{execution_id}/change-size")
def api_change_execution_size(
    execution_id: int,
    body: ExecutionChangeSizeIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """AU-I3 M3：禁无痕改码（已开工硬拦）。"""
    try:
        execution = execution_service.change_execution_size(
            db,
            tenant_id=user.tenant_id,
            execution_id=execution_id,
            size_id=body.size_id,
        )
    except ExecutionError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(execution_service.execution_out(db, execution))


@router.get("/{execution_id}/labor-allocations")
def api_execution_labor_allocations(
    execution_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """AU-I2 M4：执行单入库/直发人工成本归集线索（对账）。"""
    from app.services.fg_service import FgError, list_execution_labor_allocations

    try:
        return ok(list_execution_labor_allocations(db, tenant_id=user.tenant_id, execution_id=execution_id))
    except FgError as e:
        code = 404 if e.code == "execution_not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e


class ExecutionHaltIn(BaseModel):
    target_total_qty: int | None = Field(default=None, ge=0)
    void_open_units: bool = True
    notes: str | None = None


@router.post("/{execution_id}/halt/simulate")
def api_simulate_halt(
    execution_id: int,
    body: ExecutionHaltIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """AU-I3 M4：停产/减产仿真。"""
    try:
        data = execution_service.simulate_halt(
            db,
            tenant_id=user.tenant_id,
            execution_id=execution_id,
            target_total_qty=body.target_total_qty,
            void_open_units=body.void_open_units,
        )
    except ExecutionError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/{execution_id}/halt/confirm")
def api_confirm_halt(
    execution_id: int,
    body: ExecutionHaltIn,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    """AU-I3 M4：确认停产/减产（释放可产与料，可选作废未报工筐）。"""
    try:
        data = execution_service.confirm_halt(
            db,
            tenant_id=user.tenant_id,
            execution_id=execution_id,
            target_total_qty=body.target_total_qty,
            void_open_units=body.void_open_units,
            notes=body.notes,
            user_id=user.id,
        )
    except ExecutionError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


@router.post("/{execution_id}/cancel")
def api_cancel_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    try:
        execution = execution_service.cancel_execution(
            db, tenant_id=user.tenant_id, execution_id=execution_id
        )
    except ExecutionError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(execution_service.execution_out(db, execution))


class ExecutionCutCardsBody(BaseModel):
    dry_run: bool = True
    bundle_size: int | None = None
    only_missing: bool = True
    mode: str | None = "basket_bundles"
    skip_kit_reason: str | None = None
    # D25/P7 开裁分批：空/None=不分批（自动默认批次号）；非空=每批双数拆多批
    batch_qtys: list[int] | None = None


@router.post("/{execution_id}/cut-cards")
def api_execution_cut_cards(
    execution_id: int,
    body: ExecutionCutCardsBody,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """执行单开裁打主码（挂 execution_id；筐打印带来源分配）。"""
    try:
        data = execution_service.cut_cards_for_execution(
            db,
            tenant_id=user.tenant_id,
            execution_id=execution_id,
            dry_run=body.dry_run,
            bundle_size=body.bundle_size,
            only_missing=body.only_missing,
            mode=body.mode,
            skip_kit_reason=body.skip_kit_reason,
            batch_qtys=body.batch_qtys,
        )
    except ExecutionError as e:
        code = 404 if e.code in ("not_found",) else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)
