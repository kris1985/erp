from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import Color, OrderProcessAssignment, OwnProduct, SalesOrder, Size, TraceUnit, User, Worker
from app.schemas.api import (
    AssignmentQuotaOut,
    OrderCreate,
    OrderItemOut,
    OrderOut,
    OrderProcessAssign,
    OrderProcessOut,
    OrderStatusUpdate,
    SizeAdjustRequest,
)
from app.schemas.common import normalize_page, ok, page_payload
from app.services.assignment_service import (
    is_bundle_scope,
    is_sku_scope,
    list_assignments,
    reported_for_assignment,
    worker_reported_qty,
)
from app.services.order_service import (
    OrderError,
    adjust_order_sizes,
    count_orders_by_status,
    create_order,
    get_order,
    import_orders_csv,
    import_template_csv,
    list_orders,
    update_order,
)

router = APIRouter(prefix="/orders", tags=["orders"])


def _assignment_rows(db: Session, process_id: int) -> list[OrderProcessAssignment]:
    return list_assignments(db, process_id)


def _pool_stats(plan_qty: int, quotas: list[int | None]) -> dict:
    """未分配池 = 计划 − 已派配额合计。有人「不限」则池不可用。"""
    if not quotas:
        return {
            "allocated_quota": 0,
            "unallocated_qty": int(plan_qty),
            "has_unlimited_quota": False,
        }
    if any(q is None for q in quotas):
        return {
            "allocated_quota": None,
            "unallocated_qty": None,
            "has_unlimited_quota": True,
        }
    allocated = sum(int(q) for q in quotas)
    return {
        "allocated_quota": allocated,
        "unallocated_qty": int(plan_qty) - allocated,
        "has_unlimited_quota": False,
    }


def _serialize_order(
    db: Session,
    order,
    *,
    kit_ok: bool | None = None,
    kit_ready_date: str | None = None,
) -> dict:
    processes = []
    for p in order.processes:
        rows = _assignment_rows(db, p.id)
        assignment_outs: list[AssignmentQuotaOut] = []
        ids: list[int] = []
        names: list[str] = []
        quotas: list[int | None] = []
        if any(is_bundle_scope(a) for a in rows):
            dispatch_mode = "bundle"
        elif any(is_sku_scope(a) for a in rows):
            dispatch_mode = "sku"
        else:
            dispatch_mode = "process"
        for a in rows:
            w = db.get(Worker, a.worker_id)
            if not w:
                continue
            if w.id not in ids:
                ids.append(w.id)
                names.append(w.name)
            quotas.append(a.quota_qty)
            color = db.get(Color, a.color_id) if a.color_id else None
            size = db.get(Size, a.size_id) if a.size_id else None
            unit = db.get(TraceUnit, a.trace_unit_id) if a.trace_unit_id else None
            assignment_outs.append(
                AssignmentQuotaOut(
                    worker_id=w.id,
                    worker_name=w.name,
                    quota_qty=a.quota_qty,
                    reported_qty=reported_for_assignment(db, a),
                    color_id=a.color_id,
                    color_name=color.name if color else None,
                    size_id=a.size_id,
                    size_value=size.size_value if size else None,
                    trace_unit_id=a.trace_unit_id,
                    trace_code=unit.code if unit else None,
                    bundle_qty=unit.qty if unit else None,
                    share_weight=a.share_weight,
                )
            )
        if dispatch_mode == "process":
            pool = _pool_stats(p.plan_qty, quotas)
        else:
            # 色码/捆模式：工序级未分配池不展示（池按色码或捆在前端算）
            pool = {
                "allocated_quota": None,
                "unallocated_qty": None,
                "has_unlimited_quota": any(q is None for q in quotas) if quotas else False,
            }
        processes.append(
            OrderProcessOut(
                id=p.id,
                process_id=p.process_id,
                process_name=p.process_name,
                plan_qty=p.plan_qty,
                completed_qty=p.completed_qty,
                defect_qty=p.defect_qty,
                rework_qty=getattr(p, "rework_qty", 0) or 0,
                process_type=p.process_type.value if hasattr(p.process_type, "value") else str(p.process_type),
                assigned_worker_ids=ids,
                assigned_worker_names=names,
                assignments=assignment_outs,
                dispatch_mode=dispatch_mode,
                allocated_quota=pool["allocated_quota"],
                unallocated_qty=pool["unallocated_qty"],
                has_unlimited_quota=pool["has_unlimited_quota"],
                assigned_worker_id=ids[0] if ids else None,
                assigned_worker_name=names[0] if names else None,
                status=p.status.value if hasattr(p.status, "value") else str(p.status),
            )
        )
    product = db.get(OwnProduct, order.own_product_id)
    sales_order = db.get(SalesOrder, order.sales_order_id) if order.sales_order_id else None
    if kit_ok is None:
        try:
            from app.services.material_service import order_kit_summary

            kit_ok = order_kit_summary(db, order.tenant_id, order.id).get("kit_ok")
        except Exception:
            kit_ok = None
    from app.services.order_risk import compute_order_risk, overall_progress_percent

    risk = compute_order_risk(
        status=order.status,
        delivery_date=order.delivery_date,
        overall_percent=overall_progress_percent(order.processes),
        is_rush=bool(getattr(order, "is_rush", False)),
        kit_ok=kit_ok,
        kit_ready_date=kit_ready_date,
    )
    return OrderOut(
        id=order.id,
        order_no=order.order_no,
        customer_id=getattr(order, "customer_id", None),
        customer_name=order.customer_name,
        own_product_id=order.own_product_id,
        product_code=product.product_code if product else None,
        product_image_url=product.image_url if product else None,
        trace_enabled=bool(product.trace_enabled) if product else False,
        sales_order_id=order.sales_order_id,
        sales_order_no=sales_order.order_no if sales_order else None,
        sales_order_line_id=order.sales_order_line_id,
        total_qty=order.total_qty,
        delivery_date=order.delivery_date,
        status=order.status.value if hasattr(order.status, "value") else str(order.status),
        notes=order.notes,
        unit_price=getattr(order, "unit_price", None),
        other_cost_amount=getattr(order, "other_cost_amount", None),
        is_rush=bool(getattr(order, "is_rush", False)),
        rush_reason=getattr(order, "rush_reason", None),
        rushed_at=getattr(order, "rushed_at", None),
        kit_ok=kit_ok,
        kit_ready_date=kit_ready_date,
        kit_ready_label="预计齐套日" if kit_ready_date else None,
        risk_level=risk["risk_level"],
        risk_label=risk["risk_label"],
        risk_reasons=risk["risk_reasons"],
        at_risk=risk["at_risk"],
        created_at=order.created_at,
        items=_serialize_order_items(db, order.items),
        processes=processes,
    ).model_dump(mode="json")


def _serialize_order_items(db: Session, items) -> list[OrderItemOut]:
    color_ids = {i.color_id for i in items if getattr(i, "color_id", None)}
    size_ids = {i.size_id for i in items if getattr(i, "size_id", None)}
    colors: dict[int, str] = {}
    sizes: dict[int, str] = {}
    if color_ids:
        for c in db.scalars(select(Color).where(Color.id.in_(color_ids))).all():
            colors[c.id] = c.name
    if size_ids:
        for s in db.scalars(select(Size).where(Size.id.in_(size_ids))).all():
            sizes[s.id] = s.size_value
    out: list[OrderItemOut] = []
    for i in items:
        out.append(
            OrderItemOut(
                id=i.id,
                color_id=i.color_id,
                color_name=colors.get(i.color_id) if i.color_id else None,
                size_id=i.size_id,
                size_value=sizes.get(i.size_id) if i.size_id else None,
                qty=i.qty,
                completed_qty=i.completed_qty,
                shipped_qty=getattr(i, "shipped_qty", 0) or 0,
            )
        )
    return out


@router.get("")
def api_list_orders(
    page: int = 1,
    page_size: int = 20,
    order_no: str | None = None,
    customer_id: int | None = None,
    customer_keyword: str | None = None,
    own_product_id: int | None = None,
    status: str | None = None,
    delivery_date_from: str | None = None,
    delivery_date_to: str | None = None,
    kit_ok: bool | None = None,
    is_rush: bool | None = None,
    sales_order_id: int | None = None,
    sales_order_no: str | None = None,
    q: str | None = None,
    sort_by: str | None = Query(
        None,
        description="order_no|sales_order_no|product_code|total_qty|created_at|delivery_date",
    ),
    sort_order: str | None = Query(None, description="asc|desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from datetime import date as date_cls

    page, page_size, _ = normalize_page(page, page_size)

    def _parse_date(v: str | None):
        if not v:
            return None
        try:
            return date_cls.fromisoformat(v[:10])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"日期格式无效: {v}") from e

    try:
        from app.services import team_service

        scoped_orders = team_service.leader_order_ids(db, user)
        rows, total = list_orders(
            db,
            user.tenant_id,
            page=page,
            page_size=page_size,
            order_no=order_no,
            customer_id=customer_id,
            customer_keyword=customer_keyword,
            own_product_id=own_product_id,
            status=status,
            delivery_date_from=_parse_date(delivery_date_from),
            delivery_date_to=_parse_date(delivery_date_to),
            kit_ok=kit_ok,
            is_rush=is_rush,
            sales_order_id=sales_order_id,
            sales_order_no=sales_order_no,
            q=q,
            order_ids=scoped_orders,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except OrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    from app.services.material_service import list_shortages, order_kit_summaries
    from app.services.purchase_service import annotate_rows_with_etas

    kit_map = order_kit_summaries(db, user.tenant_id, [o.id for o in rows])
    short_ids = [
        o.id
        for o in rows
        if kit_map.get(o.id, {}).get("kit_ok") is False
        and not kit_map.get(o.id, {}).get("empty_bom")
    ]
    ready_by_order: dict[str, str] = {}
    if short_ids:
        shortage_rows = list_shortages(
            db,
            user.tenant_id,
            order_ids=short_ids,
            include_shared=True,
            hide_purchased=False,
        )
        # 列表齐套日按「缺料」口径（shortage>0），含已建草稿/在途仍缺的行
        eta = annotate_rows_with_etas(db, user.tenant_id, shortage_rows)
        ready_by_order = eta.get("by_order_id") or {}

    payload = page_payload(
        [
            _serialize_order(
                db,
                o,
                kit_ok=kit_map.get(o.id, {}).get("kit_ok"),
                kit_ready_date=ready_by_order.get(str(o.id)),
            )
            for o in rows
        ],
        total,
        page,
        page_size,
    )
    payload["team_scoped"] = scoped_orders is not None
    payload["team_empty"] = bool(scoped_orders is not None and not scoped_orders)
    return ok(payload)


@router.get("/status-stats")
def api_order_status_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按生产单状态统计数量（草稿/已确认/生产中/已完成/已取消）。"""
    from app.services import team_service

    scoped = team_service.leader_order_ids(db, user)
    return ok(count_orders_by_status(db, user.tenant_id, order_ids=scoped))


@router.post("")
def api_create_order(
    body: OrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        order = create_order(db, user.tenant_id, body, created_by=user.id)
    except OrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(_serialize_order(db, order))


@router.get("/import-template")
def api_order_import_template(user: User = Depends(require_roles("admin", "manager", "leader"))):
    csv_text = import_template_csv()
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="order_import_template.csv"'},
    )


@router.post("/import")
async def api_order_import(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
    file: UploadFile | None = File(None),
):
    if not file:
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gbk")
        except UnicodeDecodeError as e:
            raise HTTPException(status_code=400, detail="无法解码 CSV，请使用 UTF-8 或 GBK") from e
    try:
        result = import_orders_csv(db, user.tenant_id, text, created_by=user.id)
    except OrderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return ok(result)


@router.get("/{order_id}")
def api_get_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        order = get_order(db, user.tenant_id, order_id)
    except OrderError as e:
        raise HTTPException(status_code=404, detail=e.message)
    return ok(_serialize_order(db, order))


@router.patch("/{order_id}")
def api_update_order(
    order_id: int,
    body: OrderStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        data = body.model_dump(exclude_unset=True)
        order = update_order(
            db,
            user.tenant_id,
            order_id,
            status=data.get("status"),
            customer_id=data.get("customer_id"),
            customer_name=data.get("customer_name"),
            delivery_date=data.get("delivery_date"),
            notes=data.get("notes"),
            items=body.items if "items" in data else None,
            set_customer_id="customer_id" in data,
            set_customer_name="customer_name" in data,
            unit_price=data.get("unit_price"),
            other_cost_amount=data.get("other_cost_amount"),
            set_unit_price="unit_price" in data,
            set_other_cost_amount="other_cost_amount" in data,
            is_rush=data.get("is_rush") if "is_rush" in data else None,
            rush_reason=data.get("rush_reason"),
            set_rush_reason="rush_reason" in data,
            changed_by=user.id,
        )
    except OrderError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message)
    return ok(_serialize_order(db, order))


@router.post("/{order_id}/size-adjust")
def api_size_adjust_order(
    order_id: int,
    body: SizeAdjustRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """B2e 补码/改码/尾数向导：调整色码计划数量并重算需求。`dry_run=true` 仅预览差异，不落库。"""
    try:
        result = adjust_order_sizes(
            db,
            user.tenant_id,
            order_id,
            items=body.items,
            mode=body.mode,
            note=body.note,
            user_id=user.id,
            dry_run=body.dry_run,
        )
    except OrderError as e:
        code = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=code, detail=e.message)
    if not result.get("dry_run"):
        order = get_order(db, user.tenant_id, order_id)
        result["order"] = _serialize_order(db, order)
    return ok(result)


@router.patch("/{order_id}/processes/{process_id}")
def api_assign_process(
    order_id: int,
    process_id: int,
    body: OrderProcessAssign,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    try:
        order = get_order(db, user.tenant_id, order_id)
    except OrderError as e:
        raise HTTPException(status_code=404, detail=e.message)
    process = next((p for p in order.processes if p.id == process_id), None)
    if not process:
        raise HTTPException(status_code=404, detail="工序不存在")

    # 优先 assignments；否则兼容 worker_ids（配额不限 · 整工序）
    # item: worker_id, quota, color_id, size_id, trace_unit_id, share_weight
    if body.assignments is not None:
        items: list[tuple[int, int | None, int | None, int | None, int | None, int | None]] = []
        seen: set[tuple[int, int | None, int | None, int | None]] = set()
        for a in body.assignments:
            key = (a.worker_id, a.color_id, a.size_id, a.trace_unit_id)
            if key in seen:
                continue
            seen.add(key)
            if a.quota_qty is not None and a.quota_qty < 0:
                raise HTTPException(status_code=400, detail="配额不能为负")
            weight = a.share_weight
            if weight is not None and int(weight) < 0:
                raise HTTPException(status_code=400, detail="分账权重不能为负")
            items.append((a.worker_id, a.quota_qty, a.color_id, a.size_id, a.trace_unit_id, weight))
    else:
        items = [(wid, None, None, None, None, None) for wid in dict.fromkeys(body.worker_ids or [])]

    from app.services import team_service
    from app.services.team_service import TeamError

    try:
        team_service.assert_workers_in_scope(db, user, [it[0] for it in items])
    except TeamError as e:
        raise HTTPException(status_code=403, detail=e.message)

    bundle_flags = [tid is not None for _, _, _, _, tid, _ in items]
    sku_flags = [(cid is not None or sid is not None) for _, _, cid, sid, _, _ in items]
    if items and any(bundle_flags) and not all(bundle_flags):
        raise HTTPException(status_code=400, detail="同一工序不可混用捆派工与其它派工方式")
    if items and any(sku_flags) and not all(sku_flags):
        raise HTTPException(status_code=400, detail="同一工序不可混用整工序派工与色码派工")
    if items and any(bundle_flags) and any(sku_flags):
        raise HTTPException(status_code=400, detail="同一工序不可混用捆派工与色码派工")
    dispatch_bundle = bool(items) and all(bundle_flags)
    dispatch_sku = bool(items) and all(sku_flags) and not dispatch_bundle

    item_keys = {(it.color_id, it.size_id) for it in order.items or []}
    item_qty = {(it.color_id, it.size_id): int(it.qty) for it in order.items or []}

    workers: list[tuple[Worker, int | None, int | None, int | None, int | None, int | None]] = []
    for wid, quota, color_id, size_id, trace_unit_id, share_weight in items:
        worker = db.get(Worker, wid)
        if not worker or worker.tenant_id != user.tenant_id or not worker.is_active:
            raise HTTPException(status_code=400, detail=f"工人不存在或未启用：{wid}")
        if dispatch_bundle:
            if color_id is not None or size_id is not None:
                raise HTTPException(status_code=400, detail="捆派工不能带色码")
            unit = db.get(TraceUnit, trace_unit_id)
            if not unit or unit.tenant_id != user.tenant_id or unit.order_id != order.id:
                raise HTTPException(status_code=400, detail=f"捆标不存在或不属于本订单：{trace_unit_id}")
            if quota is None:
                quota = int(unit.qty)
            reported = worker_reported_qty(
                db, process.id, wid, trace_unit_id=trace_unit_id, scope="bundle"
            )
        elif dispatch_sku:
            if color_id is None or size_id is None:
                raise HTTPException(status_code=400, detail="色码派工须同时指定颜色与尺码")
            if (color_id, size_id) not in item_keys:
                raise HTTPException(status_code=400, detail="派工色码不在本订单明细中")
            reported = worker_reported_qty(
                db, process.id, wid, color_id=color_id, size_id=size_id, scope="sku"
            )
        else:
            if color_id is not None or size_id is not None or trace_unit_id is not None:
                raise HTTPException(status_code=400, detail="整工序派工不能带色码或捆")
            reported = worker_reported_qty(db, process.id, wid, scope="process")
        if quota is not None and int(quota) < reported:
            raise HTTPException(
                status_code=400,
                detail=f"{worker.name}已报{reported}，配额不能低于已报（请假请用「收回剩余」锁到已报量）",
            )
        workers.append((worker, quota, color_id, size_id, trace_unit_id, share_weight))

    if dispatch_bundle:
        by_unit: dict[int, list[int | None]] = {}
        unit_qty: dict[int, int] = {}
        for _, quota, _, _, tid, _ in workers:
            assert tid is not None
            by_unit.setdefault(tid, []).append(quota)
            if tid not in unit_qty:
                u = db.get(TraceUnit, tid)
                unit_qty[tid] = int(u.qty) if u else 0
        for tid, quotas in by_unit.items():
            plan = unit_qty.get(tid, 0)
            pool = _pool_stats(plan, quotas)
            if (
                not pool["has_unlimited_quota"]
                and pool["unallocated_qty"] is not None
                and pool["unallocated_qty"] < 0
            ):
                u = db.get(TraceUnit, tid)
                tip = u.code if u else str(tid)
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{process.process_name}捆 {tip} 已派配额{pool['allocated_quota']}"
                        f"超过本捆{plan}，请减少配额"
                    ),
                )
    elif dispatch_sku:
        by_sku: dict[tuple[int | None, int | None], list[int | None]] = {}
        for _, quota, color_id, size_id, _, _ in workers:
            by_sku.setdefault((color_id, size_id), []).append(quota)
        for sku_key, quotas in by_sku.items():
            plan = item_qty.get(sku_key, 0)
            pool = _pool_stats(plan, quotas)
            if (
                not pool["has_unlimited_quota"]
                and pool["unallocated_qty"] is not None
                and pool["unallocated_qty"] < 0
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{process.process_name}色码已派配额{pool['allocated_quota']}"
                        f"超过该色码计划{plan}，请减少配额"
                    ),
                )
    else:
        pool = _pool_stats(process.plan_qty, [q for _, q, _, _, _, _ in workers])
        if (
            not pool["has_unlimited_quota"]
            and pool["unallocated_qty"] is not None
            and pool["unallocated_qty"] < 0
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{process.process_name}已派配额{pool['allocated_quota']}超过计划{process.plan_qty}，"
                    f"请减少配额或留出未分配池"
                ),
            )

    existing = db.scalars(
        select(OrderProcessAssignment).where(OrderProcessAssignment.order_process_id == process.id)
    ).all()
    for row in existing:
        db.delete(row)
    db.flush()

    for w, quota, color_id, size_id, trace_unit_id, share_weight in workers:
        db.add(
            OrderProcessAssignment(
                tenant_id=user.tenant_id,
                order_id=order.id,
                order_process_id=process.id,
                worker_id=w.id,
                color_id=color_id,
                size_id=size_id,
                trace_unit_id=trace_unit_id,
                quota_qty=quota,
                share_weight=share_weight,
            )
        )
    process.assigned_worker_id = workers[0][0].id if workers else None
    db.commit()
    db.refresh(order)
    return ok(_serialize_order(db, order))


@router.get("/{order_id}/change-logs")
def api_list_order_change_logs(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """B2c：生产单变更历史（qty/交期变更留痕）。"""
    from app.services.order_change_service import OrderChangeError, list_order_change_logs

    try:
        return ok({"items": list_order_change_logs(db, user.tenant_id, order_id)})
    except OrderChangeError as e:
        raise HTTPException(status_code=404, detail=e.message)


class CutCardsBody(BaseModel):
    dry_run: bool = True
    bundle_size: int | None = None
    only_missing: bool = True


@router.post("/{order_id}/cut-cards")
def api_cut_cards(
    order_id: int,
    body: CutCardsBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """B2h-M1：开裁打主码（预览 dry_run=true / 生成 dry_run=false）。"""
    from app.services.trace_service import TraceError, preview_or_create_cut_cards

    try:
        data = preview_or_create_cut_cards(
            db,
            tenant_id=user.tenant_id,
            order_id=order_id,
            dry_run=body.dry_run,
            bundle_size=body.bundle_size,
            only_missing=body.only_missing,
        )
    except TraceError as e:
        code = 404 if e.code in ("order_not_found", "product_not_found") else 400
        raise HTTPException(status_code=code, detail=e.message)
    return ok(data)


@router.get("/{order_id}/trace-units")
def api_list_order_trace_units(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "leader")),
):
    """派工选捆：列出本订单已有捆标。"""
    try:
        order = get_order(db, user.tenant_id, order_id)
    except OrderError as e:
        raise HTTPException(status_code=404, detail=e.message)
    units = db.scalars(
        select(TraceUnit)
        .where(TraceUnit.tenant_id == user.tenant_id, TraceUnit.order_id == order.id)
        .order_by(TraceUnit.id.desc())
    ).all()
    items = []
    for u in units:
        color = db.get(Color, u.color_id) if u.color_id else None
        size = db.get(Size, u.size_id) if u.size_id else None
        items.append(
            {
                "id": u.id,
                "code": u.code,
                "qty": u.qty,
                "color_id": u.color_id,
                "color_name": color.name if color else None,
                "size_id": u.size_id,
                "size_value": size.size_value if size else None,
                "status": u.status.value if hasattr(u.status, "value") else str(u.status),
            }
        )
    return ok({"items": items})
