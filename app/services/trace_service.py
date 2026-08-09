"""捆标追溯单元 + 不良事件。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    DefectDisposition,
    DefectEvent,
    DefectEventStatus,
    Order,
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


def get_unit_by_code(db: Session, code: str) -> TraceUnit | None:
    c = (code or "").strip()
    if not c:
        return None
    unit = db.scalar(select(TraceUnit).where(TraceUnit.code == c))
    if unit:
        return unit
    return db.scalar(select(TraceUnit).where(TraceUnit.code == c.upper()))


def suggest_responsible_worker(
    db: Session,
    *,
    tenant_id: int,
    trace_unit_id: int,
    responsible_process_id: int | None,
) -> int | None:
    """默认责任人：该捆最近一次 report 且工序=责任工序的工人；集体工序返回 None。"""
    if not responsible_process_id:
        return None
    process = db.get(ProcessDefinition, responsible_process_id)
    if process and process.tenant_id == tenant_id:
        pt = _enum_val(process.type)
        if pt == ProcessType.group.value:
            return None

    log = db.scalar(
        select(TraceUnitLog)
        .where(
            TraceUnitLog.tenant_id == tenant_id,
            TraceUnitLog.trace_unit_id == trace_unit_id,
            TraceUnitLog.action == TraceUnitAction.report,
            TraceUnitLog.process_id == responsible_process_id,
            TraceUnitLog.worker_id.is_not(None),
        )
        .order_by(TraceUnitLog.id.desc())
        .limit(1)
    )
    return log.worker_id if log else None


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


def update_defect(
    db: Session,
    *,
    tenant_id: int,
    defect_id: int,
    status: str | None = None,
    disposition: str | None = None,
    responsible_worker_id: int | None = None,
    note: str | None = None,
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
        if responsible_worker_id == 0:
            e.responsible_worker_id = None
        else:
            w = db.get(Worker, responsible_worker_id)
            if not w or w.tenant_id != tenant_id:
                raise TraceError("worker_not_found", "责任人不存在")
            e.responsible_worker_id = responsible_worker_id
    if note is not None:
        e.note = note
    db.commit()
    db.refresh(e)
    return e
