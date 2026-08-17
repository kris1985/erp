"""AU-I1：规格执行单 / 可产合单 API。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
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
    is_rush: bool | None = None,
    delivery_from: date | None = None,
    delivery_to: date | None = None,
    sort_by: str | None = Query(
        None,
        description="execution_no|product_code|progress|delivery_date|created_at|is_rush",
    ),
    sort_order: str | None = Query(None, description="asc|desc"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager", "leader")),
):
    """默认按执行单头列表（方案 C）；码明细见 size_lines。"""
    scan = 300 if kit_ok is not None or first_kit_ok is not None else limit
    try:
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
            limit=scan,
        )
    except ExecutionError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    items_by_id = execution_service._headers_out_batch(db, rows, include_kit=False)
    items = [items_by_id[r.id] for r in rows]
    from app.services.material_service import header_kit_summaries

    kit_map = header_kit_summaries(db, user.tenant_id, [r.id for r in rows])
    for item in items:
        item["kit"] = _kit_list_payload(kit_map.get(int(item["id"])))
    if kit_ok is not None:
        items = [x for x in items if _kit_flag(x, "kit_ok") is kit_ok]
    if first_kit_ok is not None:
        items = [x for x in items if _kit_flag(x, "first_kit_ok") is first_kit_ok]
    items = items[:limit]
    return ok(
        {
            "items": items,
            "total": len(items),
            "view": "headers",
        }
    )


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
    dry_run: bool = True,
    bundle_size: int | None = None,
    only_missing: bool = True,
    mode: str | None = None,
    skip_kit_reason: str | None = None,
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
        )
    except ExecutionError as e:
        code = 404 if e.code in ("header_not_found",) else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)


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
        )
    except ExecutionError as e:
        code = 404 if e.code in ("not_found",) else 400
        raise HTTPException(status_code=code, detail=e.message) from e
    return ok(data)
