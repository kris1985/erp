"""捆标追溯单元 + 不良事件。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    DefectDisposition,
    DefectEvent,
    DefectEventStatus,
    Order,
    OrderItem,
    OwnProduct,
    ProcessDefinition,
    ProcessType,
    ReworkTask,
    ReworkTaskStatus,
    Size,
    TraceUnit,
    TraceUnitAction,
    TraceUnitLog,
    TraceUnitStatus,
    TraceUnitType,
    WorkLog,
    WorkLogStatus,
    Worker,
)

ACTIVE_BUNDLE_STATUSES = (TraceUnitStatus.open, TraceUnitStatus.in_process)

DEFECT_TYPES: list[dict[str, str]] = [
    {"code": "open_seam", "name": "开线"},
    {"code": "broken_thread", "name": "断线"},
    {"code": "skew_upper", "name": "歪帮"},
    {"code": "glue_overflow", "name": "溢胶"},
    {"code": "dirty", "name": "脏污"},
    {"code": "wrong_size", "name": "尺码错"},
    {"code": "torn", "name": "破面"},
    {"code": "other", "name": "其它"},
]

DEFECT_TYPE_CODES = {x["code"] for x in DEFECT_TYPES}
DEFECT_TYPE_NAMES = {x["code"]: x["name"] for x in DEFECT_TYPES}


class TraceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def assign_trace_code(unit: TraceUnit) -> str:
    """flush 拿到 id 后生成稳定码 TU{tenant}-{id:06d}。"""
    code = f"TU{unit.tenant_id}-{unit.id:06d}"
    unit.code = code
    return code


def create_bundle(
    db: Session,
    *,
    tenant_id: int,
    order_id: int,
    qty: int,
    color_id: int | None = None,
    size_id: int | None = None,
    worker_id: int | None = None,
    process_id: int | None = None,
    work_log_id: int | None = None,
    station_id: int | None = None,
    note: str | None = None,
    commit: bool = True,
) -> TraceUnit:
    if qty <= 0:
        raise TraceError("invalid_qty", "捆标数量必须大于 0")

    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise TraceError("order_not_found", "订单不存在")

    product = db.get(OwnProduct, order.own_product_id)
    if not product or product.tenant_id != tenant_id:
        raise TraceError("product_not_found", "产品不存在")

    if worker_id is not None:
        w = db.get(Worker, worker_id)
        if not w or w.tenant_id != tenant_id:
            raise TraceError("worker_not_found", "工人不存在")

    unit = TraceUnit(
        tenant_id=tenant_id,
        code=f"TMP-{tenant_id}",  # flush 前占位，随后覆盖
        unit_type=TraceUnitType.bundle,
        qty=qty,
        order_id=order.id,
        own_product_id=order.own_product_id,
        color_id=color_id,
        size_id=size_id,
        current_process_id=process_id,
        status=TraceUnitStatus.open,
        created_from_work_log_id=work_log_id,
        created_by_worker_id=worker_id,
    )
    db.add(unit)
    db.flush()
    assign_trace_code(unit)

    db.add(
        TraceUnitLog(
            tenant_id=tenant_id,
            trace_unit_id=unit.id,
            action=TraceUnitAction.create,
            worker_id=worker_id,
            station_id=station_id,
            process_id=process_id,
            work_log_id=work_log_id,
            qty=qty,
            note=note or "打捆",
        )
    )
    if commit:
        db.commit()
        db.refresh(unit)
    return unit


def create_bundle_from_work_log(
    db: Session,
    *,
    tenant_id: int,
    work_log_id: int,
    qty: int | None = None,
    commit: bool = True,
) -> TraceUnit:
    log = db.get(WorkLog, work_log_id)
    if not log or log.tenant_id != tenant_id:
        raise TraceError("work_log_not_found", "报工记录不存在")
    if log.status != WorkLogStatus.valid:
        raise TraceError("invalid_status", "仅有效报工可打捆")
    q = qty if qty is not None else int(log.qualified_qty or 0)
    if q <= 0:
        raise TraceError("invalid_qty", "合格数为 0，无法打捆")

    unit = create_bundle(
        db,
        tenant_id=tenant_id,
        order_id=log.order_id,
        qty=q,
        color_id=log.color_id,
        size_id=log.size_id,
        worker_id=log.worker_id,
        process_id=log.process_id,
        work_log_id=log.id,
        station_id=log.station_id,
        note=f"报工 #{log.id} 打捆",
        commit=False,
    )
    log.trace_unit_id = unit.id
    if commit:
        db.commit()
        db.refresh(unit)
    return unit


def order_has_cut_cards(db: Session, *, tenant_id: int, order_id: int) -> bool:
    """是否已有开裁生码（无报工来源且未作废）。"""
    return (
        db.scalar(
            select(func.count())
            .select_from(TraceUnit)
            .where(
                TraceUnit.tenant_id == tenant_id,
                TraceUnit.order_id == order_id,
                TraceUnit.created_from_work_log_id.is_(None),
                TraceUnit.status != TraceUnitStatus.scrapped,
            )
        )
        or 0
    ) > 0


def _plan_bundle_qtys(item_qty: int, bundle_size: int | None) -> list[int]:
    if item_qty <= 0:
        return []
    if bundle_size is None or bundle_size <= 0 or bundle_size >= item_qty:
        return [item_qty]
    out: list[int] = []
    left = item_qty
    while left > 0:
        chunk = min(bundle_size, left)
        out.append(chunk)
        left -= chunk
    return out


def _active_units_for_order(db: Session, *, tenant_id: int, order_id: int) -> list[TraceUnit]:
    return list(
        db.scalars(
            select(TraceUnit).where(
                TraceUnit.tenant_id == tenant_id,
                TraceUnit.order_id == order_id,
                TraceUnit.status != TraceUnitStatus.scrapped,
            )
        ).all()
    )


def preview_or_create_cut_cards(
    db: Session,
    *,
    tenant_id: int,
    order_id: int,
    dry_run: bool = True,
    bundle_size: int | None = None,
    only_missing: bool = True,
    commit: bool = True,
) -> dict:
    """B2h-M1：开裁打卡生码（一码一捆）。dry_run 只预览。"""
    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise TraceError("order_not_found", "生产单不存在")

    product = db.get(OwnProduct, order.own_product_id)
    if not product or product.tenant_id != tenant_id:
        raise TraceError("product_not_found", "产品不存在")
    if not product.trace_enabled:
        raise TraceError(
            "trace_not_enabled",
            "该款未开启追溯，请先在产品上打开「追溯」后再开裁打主码",
        )

    items = list(
        db.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
        ).all()
    )
    if not items:
        raise TraceError("no_items", "生产单无色码明细，请先维护色码后再开裁")

    if bundle_size is not None and bundle_size <= 0:
        raise TraceError("invalid_bundle_size", "捆量须为正整数")

    existing = _active_units_for_order(db, tenant_id=tenant_id, order_id=order.id)
    lines: list[dict] = []
    planned_creates: list[tuple[OrderItem, int]] = []

    for item in items:
        color = db.get(Color, item.color_id) if item.color_id else None
        size = db.get(Size, item.size_id) if item.size_id else None
        color_name = color.name if color else None
        size_value = size.size_value if size else None
        base = {
            "color_id": item.color_id,
            "size_id": item.size_id,
            "color_name": color_name,
            "size_value": size_value,
            "item_qty": int(item.qty or 0),
            "planned_units": [],
            "existing_unit_ids": [],
            "reason": None,
        }

        if not item.color_id or not item.size_id or int(item.qty or 0) <= 0:
            lines.append(
                {
                    **base,
                    "action": "skip_invalid",
                    "reason": "色码或数量不完整",
                }
            )
            continue

        same = [
            u
            for u in existing
            if u.color_id == item.color_id and u.size_id == item.size_id
        ]
        covered = sum(int(u.qty or 0) for u in same)
        base["existing_unit_ids"] = [u.id for u in same]

        if only_missing and covered >= int(item.qty):
            lines.append(
                {
                    **base,
                    "action": "skip_exists",
                    "reason": f"已有活跃捆合计 {covered} 双，已覆盖本行",
                    "planned_units": [],
                }
            )
            continue

        # 仅补未覆盖部分：按整行策略生成（已覆盖则整行 skip；部分覆盖时仍按行 qty 拆，
        # M1 简化：已有任意同色码活跃捆且 covered < qty 时仍允许按差额再拆）
        remain = int(item.qty) - covered if only_missing else int(item.qty)
        if remain <= 0:
            lines.append(
                {
                    **base,
                    "action": "skip_exists",
                    "reason": "已覆盖",
                    "planned_units": [],
                }
            )
            continue

        qtys = _plan_bundle_qtys(remain, bundle_size)
        planned = [{"qty": q} for q in qtys]
        lines.append({**base, "action": "create", "planned_units": planned, "reason": None})
        for q in qtys:
            planned_creates.append((item, q))

    to_create = len(planned_creates)
    created: list[dict] = []

    if not dry_run and to_create:
        for item, q in planned_creates:
            unit = create_bundle(
                db,
                tenant_id=tenant_id,
                order_id=order.id,
                qty=q,
                color_id=item.color_id,
                size_id=item.size_id,
                worker_id=None,
                process_id=None,
                work_log_id=None,
                note="开裁打卡",
                commit=False,
            )
            created.append(
                {
                    "id": unit.id,
                    "code": unit.code,
                    "qty": unit.qty,
                    "color_id": unit.color_id,
                    "size_id": unit.size_id,
                }
            )
        if commit:
            db.commit()
            for c in created:
                u = db.get(TraceUnit, c["id"])
                if u:
                    db.refresh(u)
                    c["code"] = u.code

    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "strategy": {"bundle_size": bundle_size},
        "lines": lines,
        "to_create": to_create,
        "created": created,
        "print_path": f"/admin/orders/print/{order.id}?mode=main-codes",
    }


def void_trace_unit(
    db: Session,
    *,
    tenant_id: int,
    unit_id: int,
    note: str | None = None,
    commit: bool = True,
) -> TraceUnit:
    """开裁作废：无报工流水的 open 捆 → scrapped + void log。"""
    unit = db.get(TraceUnit, unit_id)
    if not unit or unit.tenant_id != tenant_id:
        raise TraceError("trace_not_found", "捆标不存在")

    has_report = db.scalar(
        select(func.count())
        .select_from(TraceUnitLog)
        .where(
            TraceUnitLog.trace_unit_id == unit.id,
            TraceUnitLog.action == TraceUnitAction.report,
        )
    )
    if has_report:
        raise TraceError("has_reports", "该主码已有报工流水，不可作废")

    st = _enum_val(unit.status)
    if st != TraceUnitStatus.open.value:
        raise TraceError("invalid_status", "仅「未开工」主码可作废；已过站请走不良报废")

    unit.status = TraceUnitStatus.scrapped
    db.add(
        TraceUnitLog(
            tenant_id=tenant_id,
            trace_unit_id=unit.id,
            action=TraceUnitAction.void,
            qty=unit.qty,
            note=note or "开裁作废",
        )
    )
    if commit:
        db.commit()
        db.refresh(unit)
    return unit


def get_unit_by_code(db: Session, code: str) -> TraceUnit | None:
    c = (code or "").strip()
    if not c:
        return None
    unit = db.scalar(select(TraceUnit).where(TraceUnit.code == c))
    if unit:
        return unit
    return db.scalar(select(TraceUnit).where(TraceUnit.code == c.upper()))


def suggest_responsible_detail(
    db: Session,
    *,
    tenant_id: int,
    trace_unit_id: int,
    responsible_process_id: int | None,
) -> dict:
    """责任线索建议：主建议 + 依据 + 候选 + confidence（线索非鉴定）。"""
    empty = {
        "worker_id": None,
        "worker_name": None,
        "basis": "",
        "candidates": [],
        "confidence": "none",
    }
    if not responsible_process_id:
        empty["basis"] = "未指定责任工序"
        return empty

    process = db.get(ProcessDefinition, responsible_process_id)
    if not process or process.tenant_id != tenant_id:
        empty["basis"] = "责任工序不存在"
        return empty

    process_name = process.name or str(process.id)
    if _enum_val(process.type) == ProcessType.group.value:
        return {
            **empty,
            "basis": f"集体工序「{process_name}」，不自动建议个人",
            "confidence": "none",
        }

    unit = db.get(TraceUnit, trace_unit_id)
    if not unit or unit.tenant_id != tenant_id:
        empty["basis"] = "捆标不存在"
        return empty

    logs = list(
        db.scalars(
            select(TraceUnitLog)
            .where(
                TraceUnitLog.tenant_id == tenant_id,
                TraceUnitLog.trace_unit_id == trace_unit_id,
                TraceUnitLog.action == TraceUnitAction.report,
                TraceUnitLog.process_id == responsible_process_id,
                TraceUnitLog.worker_id.is_not(None),
            )
            .order_by(TraceUnitLog.id.desc())
            .limit(20)
        ).all()
    )
    if not logs:
        return {
            **empty,
            "basis": f"该捆 · {process_name} · 无报工流水，无法建议",
            "confidence": "none",
        }

    seen: set[int] = set()
    candidates: list[dict] = []
    for lg in logs:
        wid = int(lg.worker_id)  # type: ignore[arg-type]
        if wid in seen:
            continue
        seen.add(wid)
        w = db.get(Worker, wid)
        at = lg.created_at.isoformat() if lg.created_at else None
        candidates.append(
            {
                "worker_id": wid,
                "worker_name": w.name if w else None,
                "at": at,
                "log_id": lg.id,
            }
        )
        if len(candidates) >= 3:
            break

    top = candidates[0]
    at_short = (top.get("at") or "")[:16].replace("T", " ")
    basis = (
        f"该捆 · {process_name} · 最近报工 · {top.get('worker_name') or top['worker_id']}"
        + (f" · {at_short}" if at_short else "")
    )
    unique_workers = len(seen)
    confidence = "high" if unique_workers == 1 else "medium"
    return {
        "worker_id": top["worker_id"],
        "worker_name": top.get("worker_name"),
        "basis": basis,
        "candidates": candidates,
        "confidence": confidence,
    }


def suggest_responsible_worker(
    db: Session,
    *,
    tenant_id: int,
    trace_unit_id: int,
    responsible_process_id: int | None,
) -> int | None:
    """默认责任人：该捆最近一次 report 且工序=责任工序的工人；集体工序返回 None。"""
    detail = suggest_responsible_detail(
        db,
        tenant_id=tenant_id,
        trace_unit_id=trace_unit_id,
        responsible_process_id=responsible_process_id,
    )
    return detail.get("worker_id")


def order_has_active_bundles(db: Session, *, tenant_id: int, order_id: int) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(TraceUnit)
            .where(
                TraceUnit.tenant_id == tenant_id,
                TraceUnit.order_id == order_id,
                TraceUnit.status.in_(list(ACTIVE_BUNDLE_STATUSES)),
            )
        )
        or 0
    ) > 0


def derive_trace_quality(db: Session, e: DefectEvent) -> str:
    """派生追溯强度：weak / partial / strong（不落库）。"""
    if not e.trace_unit_id:
        return "weak"
    if e.responsible_worker_id:
        return "strong"
    if e.responsible_process_id:
        process = db.get(ProcessDefinition, e.responsible_process_id)
        if process and _enum_val(process.type) == ProcessType.group.value:
            return "strong"
    return "partial"


def attach_report_to_unit(
    db: Session,
    *,
    tenant_id: int,
    unit: TraceUnit,
    work_log: WorkLog,
    station_id: int | None = None,
) -> None:
    work_log.trace_unit_id = unit.id
    unit.current_process_id = work_log.process_id
    if unit.status == TraceUnitStatus.open:
        unit.status = TraceUnitStatus.in_process
    db.add(
        TraceUnitLog(
            tenant_id=tenant_id,
            trace_unit_id=unit.id,
            action=TraceUnitAction.report,
            worker_id=work_log.worker_id,
            station_id=station_id or work_log.station_id,
            process_id=work_log.process_id,
            work_log_id=work_log.id,
            qty=int(work_log.qualified_qty or 0) or int(work_log.rework_qty or 0),
            note="扫码报工",
        )
    )


def create_defect_event(
    db: Session,
    *,
    tenant_id: int,
    defect_type: str,
    qty: int,
    order_id: int | None = None,
    trace_unit_id: int | None = None,
    color_id: int | None = None,
    size_id: int | None = None,
    found_process_id: int | None = None,
    responsible_process_id: int | None = None,
    responsible_worker_id: int | None = None,
    disposition: str = "rework",
    found_by_worker_id: int | None = None,
    found_by_user_id: int | None = None,
    note: str | None = None,
    auto_suggest_worker: bool = True,
) -> DefectEvent:
    if qty <= 0:
        raise TraceError("invalid_qty", "不良数量必须大于 0")
    if defect_type not in DEFECT_TYPE_CODES:
        raise TraceError("invalid_defect_type", f"不支持的缺陷类型：{defect_type}")

    unit: TraceUnit | None = None
    if trace_unit_id is not None:
        unit = db.get(TraceUnit, trace_unit_id)
        if not unit or unit.tenant_id != tenant_id:
            raise TraceError("trace_not_found", "捆标不存在")
        order_id = order_id or unit.order_id
        color_id = color_id if color_id is not None else unit.color_id
        size_id = size_id if size_id is not None else unit.size_id

    if not order_id:
        raise TraceError("order_required", "请选择订单或扫捆标")

    order = db.get(Order, order_id)
    if not order or order.tenant_id != tenant_id:
        raise TraceError("order_not_found", "订单不存在")

    if unit is None and order_has_active_bundles(db, tenant_id=tenant_id, order_id=order.id):
        raise TraceError(
            "trace_unit_required",
            "本单有进行中捆，请选择捆标后再登记",
        )

    if disposition not in DefectDisposition.__members__:
        raise TraceError("invalid_disposition", f"不支持的处置方式：{disposition}")
    disp = DefectDisposition(disposition)

    if auto_suggest_worker and responsible_worker_id is None and unit and responsible_process_id:
        responsible_worker_id = suggest_responsible_worker(
            db,
            tenant_id=tenant_id,
            trace_unit_id=unit.id,
            responsible_process_id=responsible_process_id,
        )

    if responsible_worker_id is not None:
        w = db.get(Worker, responsible_worker_id)
        if not w or w.tenant_id != tenant_id:
            raise TraceError("worker_not_found", "责任人不存在")

    event = DefectEvent(
        tenant_id=tenant_id,
        trace_unit_id=unit.id if unit else None,
        order_id=order.id,
        color_id=color_id,
        size_id=size_id,
        found_process_id=found_process_id,
        responsible_process_id=responsible_process_id,
        responsible_worker_id=responsible_worker_id,
        defect_type=defect_type,
        qty=qty,
        disposition=disp,
        found_by_worker_id=found_by_worker_id,
        found_by_user_id=found_by_user_id,
        note=note,
        status=DefectEventStatus.open,
    )
    db.add(event)
    db.flush()

    if unit:
        db.add(
            TraceUnitLog(
                tenant_id=tenant_id,
                trace_unit_id=unit.id,
                action=TraceUnitAction.inspect,
                worker_id=found_by_worker_id,
                process_id=found_process_id,
                qty=qty,
                note=f"不良 {DEFECT_TYPE_NAMES.get(defect_type, defect_type)}×{qty}",
            )
        )
        if disp == DefectDisposition.scrap:
            unit.status = TraceUnitStatus.scrapped

    db.commit()
    db.refresh(event)
    return event


def unit_detail_dict(db: Session, unit: TraceUnit) -> dict:
    order = db.get(Order, unit.order_id)
    product = db.get(OwnProduct, unit.own_product_id)
    color = db.get(Color, unit.color_id) if unit.color_id else None
    size = db.get(Size, unit.size_id) if unit.size_id else None
    creator = db.get(Worker, unit.created_by_worker_id) if unit.created_by_worker_id else None
    process = db.get(ProcessDefinition, unit.current_process_id) if unit.current_process_id else None

    logs = db.scalars(
        select(TraceUnitLog)
        .where(TraceUnitLog.trace_unit_id == unit.id)
        .order_by(TraceUnitLog.id.desc())
        .limit(50)
    ).all()
    log_items = []
    for lg in logs:
        w = db.get(Worker, lg.worker_id) if lg.worker_id else None
        p = db.get(ProcessDefinition, lg.process_id) if lg.process_id else None
        log_items.append(
            {
                "id": lg.id,
                "action": _enum_val(lg.action),
                "worker_id": lg.worker_id,
                "worker_name": w.name if w else None,
                "process_id": lg.process_id,
                "process_name": p.name if p else None,
                "work_log_id": lg.work_log_id,
                "qty": lg.qty,
                "note": lg.note,
                "created_at": lg.created_at.isoformat() if lg.created_at else None,
            }
        )

    defects = db.scalars(
        select(DefectEvent)
        .where(DefectEvent.trace_unit_id == unit.id)
        .order_by(DefectEvent.id.desc())
        .limit(20)
    ).all()

    processes = []
    if order:
        for p in order.processes or []:
            processes.append(
                {
                    "process_id": p.process_id,
                    "process_name": p.process_name,
                    "status": _enum_val(p.status),
                    "plan_qty": p.plan_qty,
                    "completed_qty": p.completed_qty,
                }
            )

    return {
        "id": unit.id,
        "code": unit.code,
        "unit_type": _enum_val(unit.unit_type),
        "qty": unit.qty,
        "parent_id": unit.parent_id,
        "serial_no": unit.serial_no,
        "order_id": unit.order_id,
        "order_no": order.order_no if order else None,
        "customer_name": order.customer_name if order else None,
        "own_product_id": unit.own_product_id,
        "product_code": product.product_code if product else None,
        "trace_enabled": bool(product.trace_enabled) if product else False,
        "color_id": unit.color_id,
        "color_name": color.name if color else None,
        "size_id": unit.size_id,
        "size_value": size.size_value if size else None,
        "current_process_id": unit.current_process_id,
        "current_process_name": process.name if process else None,
        "status": _enum_val(unit.status),
        "created_from_work_log_id": unit.created_from_work_log_id,
        "created_by_worker_id": unit.created_by_worker_id,
        "created_by_worker_name": creator.name if creator else None,
        "created_at": unit.created_at.isoformat() if unit.created_at else None,
        "scan_path": f"/trace/{unit.code}",
        "logs": log_items,
        "defects": [defect_out(db, d) for d in defects],
        "order_processes": processes,
    }


def defect_out(db: Session, e: DefectEvent) -> dict:
    order = db.get(Order, e.order_id)
    unit = db.get(TraceUnit, e.trace_unit_id) if e.trace_unit_id else None
    color = db.get(Color, e.color_id) if e.color_id else None
    size = db.get(Size, e.size_id) if e.size_id else None
    found_p = db.get(ProcessDefinition, e.found_process_id) if e.found_process_id else None
    resp_p = db.get(ProcessDefinition, e.responsible_process_id) if e.responsible_process_id else None
    resp_w = db.get(Worker, e.responsible_worker_id) if e.responsible_worker_id else None
    found_w = db.get(Worker, e.found_by_worker_id) if e.found_by_worker_id else None
    pending_task = db.scalar(
        select(ReworkTask)
        .where(
            ReworkTask.defect_event_id == e.id,
            ReworkTask.status == ReworkTaskStatus.pending,
        )
        .order_by(ReworkTask.id.desc())
        .limit(1)
    )
    pending_worker = db.get(Worker, pending_task.worker_id) if pending_task else None
    return {
        "id": e.id,
        "trace_unit_id": e.trace_unit_id,
        "trace_code": unit.code if unit else None,
        "order_id": e.order_id,
        "order_no": order.order_no if order else None,
        "color_id": e.color_id,
        "color_name": color.name if color else None,
        "size_id": e.size_id,
        "size_value": size.size_value if size else None,
        "found_process_id": e.found_process_id,
        "found_process_name": found_p.name if found_p else None,
        "responsible_process_id": e.responsible_process_id,
        "responsible_process_name": resp_p.name if resp_p else None,
        "responsible_worker_id": e.responsible_worker_id,
        "responsible_worker_name": resp_w.name if resp_w else None,
        "defect_type": e.defect_type,
        "defect_type_name": DEFECT_TYPE_NAMES.get(e.defect_type, e.defect_type),
        "qty": e.qty,
        "disposition": _enum_val(e.disposition),
        "found_by_worker_id": e.found_by_worker_id,
        "found_by_worker_name": found_w.name if found_w else None,
        "found_by_user_id": e.found_by_user_id,
        "note": e.note,
        "status": _enum_val(e.status),
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "pending_rework_task_id": pending_task.id if pending_task else None,
        "pending_rework_worker_id": pending_task.worker_id if pending_task else None,
        "pending_rework_worker_name": pending_worker.name if pending_worker else None,
        "pending_rework_qty": pending_task.qty if pending_task else None,
        "trace_quality": derive_trace_quality(db, e),
    }


def list_defects(
    db: Session,
    *,
    tenant_id: int,
    order_no: str | None = None,
    responsible_worker_id: int | None = None,
    responsible_process_id: int | None = None,
    defect_type: str | None = None,
    status: str | None = None,
    pending_rework: bool | None = None,
    trace_quality: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    q = select(DefectEvent).where(DefectEvent.tenant_id == tenant_id)
    order_ids: list[int] | None = None
    if order_no:
        order_ids = list(
            db.scalars(
                select(Order.id).where(Order.tenant_id == tenant_id, Order.order_no == order_no.strip())
            ).all()
        )
        if not order_ids:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "summary": {"by_worker": [], "by_type": []},
            }
        q = q.where(DefectEvent.order_id.in_(order_ids))
    if responsible_worker_id:
        q = q.where(DefectEvent.responsible_worker_id == responsible_worker_id)
    if responsible_process_id:
        q = q.where(DefectEvent.responsible_process_id == responsible_process_id)
    if defect_type:
        q = q.where(DefectEvent.defect_type == defect_type)
    if status and status in DefectEventStatus.__members__:
        q = q.where(DefectEvent.status == DefectEventStatus(status))
    if pending_rework:
        pending_ids = select(ReworkTask.defect_event_id).where(
            ReworkTask.tenant_id == tenant_id,
            ReworkTask.status == ReworkTaskStatus.pending,
        )
        q = q.where(DefectEvent.id.in_(pending_ids))
    if trace_quality in ("weak", "partial", "strong"):
        q = _apply_trace_quality_filter(db, q, tenant_id=tenant_id, trace_quality=trace_quality)

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(
        q.order_by(DefectEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    summary_q = select(DefectEvent).where(DefectEvent.tenant_id == tenant_id)
    if order_ids is not None:
        summary_q = summary_q.where(DefectEvent.order_id.in_(order_ids))
    if responsible_worker_id:
        summary_q = summary_q.where(DefectEvent.responsible_worker_id == responsible_worker_id)
    if responsible_process_id:
        summary_q = summary_q.where(DefectEvent.responsible_process_id == responsible_process_id)
    if defect_type:
        summary_q = summary_q.where(DefectEvent.defect_type == defect_type)
    if status and status in DefectEventStatus.__members__:
        summary_q = summary_q.where(DefectEvent.status == DefectEventStatus(status))
    if pending_rework:
        pending_ids = select(ReworkTask.defect_event_id).where(
            ReworkTask.tenant_id == tenant_id,
            ReworkTask.status == ReworkTaskStatus.pending,
        )
        summary_q = summary_q.where(DefectEvent.id.in_(pending_ids))
    if trace_quality in ("weak", "partial", "strong"):
        summary_q = _apply_trace_quality_filter(
            db, summary_q, tenant_id=tenant_id, trace_quality=trace_quality
        )
    all_for_summary = db.scalars(summary_q).all()
    by_worker: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for e in all_for_summary:
        wname = "未指定"
        if e.responsible_worker_id:
            w = db.get(Worker, e.responsible_worker_id)
            wname = w.name if w else str(e.responsible_worker_id)
        by_worker[wname] = by_worker.get(wname, 0) + int(e.qty or 0)
        tname = DEFECT_TYPE_NAMES.get(e.defect_type, e.defect_type)
        by_type[tname] = by_type.get(tname, 0) + int(e.qty or 0)

    return {
        "items": [defect_out(db, e) for e in rows],
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "summary": {
            "by_worker": [{"name": k, "qty": v} for k, v in sorted(by_worker.items(), key=lambda x: -x[1])],
            "by_type": [{"name": k, "qty": v} for k, v in sorted(by_type.items(), key=lambda x: -x[1])],
        },
    }


def _apply_trace_quality_filter(db: Session, q, *, tenant_id: int, trace_quality: str):
    if trace_quality == "weak":
        return q.where(DefectEvent.trace_unit_id.is_(None))
    group_process_ids = list(
        db.scalars(
            select(ProcessDefinition.id).where(
                ProcessDefinition.tenant_id == tenant_id,
                ProcessDefinition.type == ProcessType.group,
            )
        ).all()
    )
    if trace_quality == "strong":
        conds = [DefectEvent.responsible_worker_id.is_not(None)]
        if group_process_ids:
            conds.append(DefectEvent.responsible_process_id.in_(group_process_ids))
        return q.where(DefectEvent.trace_unit_id.is_not(None), or_(*conds))
    # partial: has unit, no worker, and not (group process)
    q = q.where(
        DefectEvent.trace_unit_id.is_not(None),
        DefectEvent.responsible_worker_id.is_(None),
    )
    if group_process_ids:
        q = q.where(
            or_(
                DefectEvent.responsible_process_id.is_(None),
                DefectEvent.responsible_process_id.notin_(group_process_ids),
            )
        )
    return q


def update_defect(
    db: Session,
    *,
    tenant_id: int,
    defect_id: int,
    status: str | None = None,
    disposition: str | None = None,
    responsible_worker_id: int | None = None,
    note: str | None = None,
    updated_by_user_id: int | None = None,
) -> DefectEvent:
    e = db.get(DefectEvent, defect_id)
    if not e or e.tenant_id != tenant_id:
        raise TraceError("not_found", "不良事件不存在")
    if status is not None:
        if status not in DefectEventStatus.__members__:
            raise TraceError("invalid_status", f"无效状态：{status}")
        e.status = DefectEventStatus(status)
    if disposition is not None:
        if disposition not in DefectDisposition.__members__:
            raise TraceError("invalid_disposition", f"无效处置：{disposition}")
        e.disposition = DefectDisposition(disposition)
    if responsible_worker_id is not None:
        old_id = e.responsible_worker_id
        old_name = "空"
        if old_id:
            ow = db.get(Worker, old_id)
            old_name = ow.name if ow else str(old_id)
        if responsible_worker_id == 0:
            e.responsible_worker_id = None
            new_name = "空"
        else:
            w = db.get(Worker, responsible_worker_id)
            if not w or w.tenant_id != tenant_id:
                raise TraceError("worker_not_found", "责任人不存在")
            e.responsible_worker_id = responsible_worker_id
            new_name = w.name
        base_note = note if note is not None else (e.note or "")
        if old_id != e.responsible_worker_id:
            who = f"user#{updated_by_user_id}" if updated_by_user_id else "user"
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            line = f"[改责] {old_name}→{new_name} by {who} @ {stamp}"
            e.note = f"{base_note.rstrip()}\n{line}".strip() if base_note.strip() else line
        elif note is not None:
            e.note = note
    elif note is not None:
        e.note = note
    db.commit()
    db.refresh(e)
    return e

def _unit_summary(db: Session, u: TraceUnit) -> dict:
    color = db.get(Color, u.color_id) if u.color_id else None
    size = db.get(Size, u.size_id) if u.size_id else None
    return {
        "id": u.id,
        "code": u.code,
        "qty": u.qty,
        "color_id": u.color_id,
        "color_name": color.name if color else None,
        "size_id": u.size_id,
        "size_value": size.size_value if size else None,
        "status": _enum_val(u.status),
        "current_process_id": u.current_process_id,
    }


def _order_header(db: Session, order: Order) -> dict:
    product = db.get(OwnProduct, order.own_product_id) if order.own_product_id else None
    return {
        "id": order.id,
        "order_no": order.order_no,
        "customer_name": order.customer_name,
        "own_product_id": order.own_product_id,
        "product_code": product.product_code if product else None,
        "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
        "trace_enabled": bool(product.trace_enabled) if product else False,
        "status": _enum_val(order.status),
    }


def quality_trace_lookup(
    db: Session,
    *,
    tenant_id: int,
    q: str,
    unit_page: int = 1,
    unit_page_size: int = 20,
) -> dict:
    """B2g 门面：解析单号/捆码/不良 ID，编排现网详情，不复制流水查询。"""
    raw = (q or "").strip()
    if not raw:
        raise TraceError("query_required", "请输入生产单号、捆标码或不良 ID")

    focus_unit: TraceUnit | None = None
    order: Order | None = None
    focus_defect: DefectEvent | None = None

    if raw.isdigit():
        did = int(raw)
        focus_defect = db.get(DefectEvent, did)
        if focus_defect and focus_defect.tenant_id == tenant_id:
            order = db.get(Order, focus_defect.order_id)
            if focus_defect.trace_unit_id:
                focus_unit = db.get(TraceUnit, focus_defect.trace_unit_id)
        else:
            focus_defect = None

    if order is None:
        unit = get_unit_by_code(db, raw)
        if unit and unit.tenant_id == tenant_id:
            focus_unit = unit
            order = db.get(Order, unit.order_id)

    if order is None:
        order = db.scalar(
            select(Order).where(Order.tenant_id == tenant_id, Order.order_no == raw)
        )

    if order is None or order.tenant_id != tenant_id:
        raise TraceError("not_found", "未找到匹配的生产单、捆标或不良事件")

    unit_q = (
        select(TraceUnit)
        .where(TraceUnit.tenant_id == tenant_id, TraceUnit.order_id == order.id)
        .order_by(TraceUnit.id.desc())
    )
    unit_total = db.scalar(select(func.count()).select_from(unit_q.subquery())) or 0
    units = list(
        db.scalars(
            unit_q.offset((unit_page - 1) * unit_page_size).limit(unit_page_size)
        ).all()
    )

    defects_rows = list(
        db.scalars(
            select(DefectEvent)
            .where(DefectEvent.tenant_id == tenant_id, DefectEvent.order_id == order.id)
            .order_by(DefectEvent.id.desc())
            .limit(50)
        ).all()
    )
    if focus_unit:
        defects_for_focus = [e for e in defects_rows if e.trace_unit_id == focus_unit.id]
    else:
        defects_for_focus = defects_rows

    focus_detail = unit_detail_dict(db, focus_unit) if focus_unit else None

    return {
        "query": raw,
        "order": _order_header(db, order),
        "units_summary": {
            "items": [_unit_summary(db, u) for u in units],
            "total": int(unit_total),
            "page": unit_page,
            "page_size": unit_page_size,
        },
        "focus_unit_id": focus_unit.id if focus_unit else None,
        "focus_unit": focus_detail,
        "focus_defect_id": focus_defect.id if focus_defect else None,
        "defects_summary": [defect_out(db, e) for e in defects_for_focus],
        "order_defects_summary": [defect_out(db, e) for e in defects_rows],
    }