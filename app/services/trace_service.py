"""框码追溯单元 + 不良事件。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    DefectDisposition,
    DefectEvent,
    DefectResponsibility,
    DefectEventStatus,
    Department,
    Order,
    OrderItem,
    OrderMaterialRequirement,
    OrderProcess,
    OwnProduct,
    OwnProductLabor,
    ProcessDefinition,
    ProcessType,
    ReworkTask,
    ReworkTaskStatus,
    Partner,
    SalesOrder,
    SalesOrderLine,
    Size,
    StockDoc,
    SubcontractOrder,
    SubcontractOrderStatus,
    StockDocStatus,
    StockDocType,
    Team,
    TraceUnit,
    TraceUnitAction,
    TraceUnitLog,
    TraceUnitStatus,
    TraceUnitType,
    WorkLog,
    WorkLogStatus,
    Employee,
    ExecutionHeader,
)

ACTIVE_BUNDLE_STATUSES = (TraceUnitStatus.open, TraceUnitStatus.in_process)


def calculate_defect_loss_quote(
    db: Session,
    *,
    tenant_id: int,
    header_id: int,
    order_process_id: int,
) -> dict:
    """累计首道至发现工序的段级物料成本和工序工资，并折算到每只。"""
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise TraceError("header_not_found", "生产单不存在")
    scope_filter = OrderProcess.header_id == header.id
    if header.shop_order_id:
        scope_filter = or_(scope_filter, OrderProcess.order_id == int(header.shop_order_id))
    processes = list(
        db.scalars(
            select(OrderProcess)
            .where(OrderProcess.tenant_id == tenant_id, scope_filter)
            .order_by(OrderProcess.id)
        ).all()
    )
    target_index = next(
        (index for index, row in enumerate(processes) if int(row.id) == order_process_id),
        None,
    )
    if target_index is None:
        raise TraceError("process_not_found", "发现工序不在当前生产单中")
    found_process = processes[target_index]
    cumulative_processes = processes[: target_index + 1]
    cumulative_segment_ids = {
        int(row.segment_id) for row in cumulative_processes if row.segment_id
    }

    from app.services import material_service

    # 确保生产单 BOM 快照已生成，再按工序段筛选。
    material_service.get_header_kit(db, tenant_id, header.id)
    req_filter = OrderMaterialRequirement.header_id == header.id
    if header.shop_order_id:
        req_filter = or_(
            req_filter,
            OrderMaterialRequirement.order_id == int(header.shop_order_id),
        )
    requirements = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                req_filter,
            )
        ).all()
    )
    scoped = [
        row
        for row in requirements
        if row.consume_segment_id is None
        or int(row.consume_segment_id) in cumulative_segment_ids
    ]
    generic_material_per_pair = Decimal("0")
    material_per_pair_by_size: dict[int, Decimal] = {}
    for row in scoped:
        usage = Decimal(row.qty_per_pair or 0)
        if getattr(row, "usage_by_size", False):
            usage *= Decimal(getattr(row, "size_coeff", 1) or 1)
        cost = usage * Decimal(row.unit_price or 0)
        if getattr(row, "usage_by_size", False) and row.size_id:
            material_per_pair_by_size[int(row.size_id)] = (
                material_per_pair_by_size.get(int(row.size_id), Decimal("0")) + cost
            )
        else:
            generic_material_per_pair += cost

    labors = list(
        db.scalars(
            select(OwnProductLabor)
            .where(
                OwnProductLabor.tenant_id == tenant_id,
                OwnProductLabor.own_product_id == header.own_product_id,
            )
            .order_by(OwnProductLabor.id)
        ).all()
    )
    labor_per_pair = Decimal("0")
    labor_before_process_per_pair = Decimal("0")
    for process in cumulative_processes:
        labor = next(
            (
                row for row in labors
                if int(row.process_id or 0) == int(process.process_id)
                and (int(row.part_id) if row.part_id else None)
                == (int(process.part_id) if process.part_id else None)
            ),
            None,
        )
        if not labor:
            labor = next(
                (
                    row for row in labors
                    if int(row.process_id or 0) == int(process.process_id) and row.part_id is None
                ),
                None,
            )
        process_def = db.get(ProcessDefinition, int(process.process_id))
        process_labor = Decimal(labor.unit_price or 0) if labor else Decimal(
            process_def.default_price or 0 if process_def else 0
        )
        if process is not found_process:
            labor_before_process_per_pair += process_labor
        labor_per_pair += process_labor
    labor_per_piece = (labor_per_pair / Decimal("2")).quantize(Decimal("0.0001"))
    labor_before_process_per_piece = (
        labor_before_process_per_pair / Decimal("2")
    ).quantize(Decimal("0.0001"))
    size_ids = {int(line.size_id) for line in header.size_lines if line.size_id}
    size_ids.update(material_per_pair_by_size)
    by_size = {
        str(size_id): {
            "material_per_piece": float(
                ((generic_material_per_pair + material_per_pair_by_size.get(size_id, Decimal("0"))) / Decimal("2")).quantize(Decimal("0.0001"))
            ),
            "labor_per_piece": float(labor_per_piece),
        }
        for size_id in size_ids
    }
    default_material = (generic_material_per_pair / Decimal("2")).quantize(Decimal("0.0001"))
    return {
        "header_id": header.id,
        "order_process_id": found_process.id,
        "process_id": found_process.process_id,
        "segment_id": found_process.segment_id,
        "cumulative_segment_ids": sorted(cumulative_segment_ids),
        "material_per_piece": float(default_material),
        "labor_per_piece": float(labor_per_piece),
        "labor_before_process_per_piece": float(labor_before_process_per_piece),
        "by_size": by_size,
    }


def get_defect_material_kit(db: Session, *, tenant_id: int, defect_id: int) -> dict:
    """按单条不良的补做数量与工艺范围计算齐套情况。"""
    event = db.get(DefectEvent, defect_id)
    if not event or event.tenant_id != tenant_id:
        raise TraceError("not_found", "不良记录不存在")
    if not event.header_id:
        raise TraceError("header_required", "该不良未关联生产单")
    if not event.found_process_id:
        raise TraceError("process_required", "该不良未指定发现工序")

    header = db.get(ExecutionHeader, int(event.header_id))
    if not header or header.tenant_id != tenant_id:
        raise TraceError("header_not_found", "生产单不存在")
    scope_filter = OrderProcess.header_id == header.id
    if header.shop_order_id:
        scope_filter = or_(scope_filter, OrderProcess.order_id == int(header.shop_order_id))
    processes = list(
        db.scalars(
            select(OrderProcess)
            .where(OrderProcess.tenant_id == tenant_id, scope_filter)
            .order_by(OrderProcess.id)
        ).all()
    )
    target_index = next(
        (
            index
            for index, process in enumerate(processes)
            if int(process.process_id) == int(event.found_process_id)
        ),
        None,
    )
    if target_index is None:
        raise TraceError("process_not_found", "发现工序不在当前生产单路线中")
    cumulative_processes = processes[: target_index + 1]
    cumulative_segment_ids = {
        int(process.segment_id) for process in cumulative_processes if process.segment_id
    }

    from app.services import material_service

    kit = material_service.get_header_kit(db, tenant_id, header.id)
    pieces = Decimal(int(event.qty or 0))
    lines: list[dict] = []
    for source in kit.get("lines", []):
        if source.get("is_customer_supplied"):
            continue
        segment_id = source.get("consume_segment_id")
        if segment_id is not None and int(segment_id) not in cumulative_segment_ids:
            continue
        if source.get("usage_by_size") and int(source.get("size_id") or 0) != int(event.size_id or 0):
            continue
        usage = Decimal(source.get("qty_per_pair") or 0)
        if source.get("usage_by_size"):
            usage *= Decimal(source.get("size_coeff") or 1)
        usage *= Decimal("1") + Decimal(source.get("loss_rate") or 0)
        required = (usage * pieces / Decimal("2")).quantize(Decimal("0.0001"))
        if required <= 0:
            continue
        own_available = max(
            Decimal("0"),
            Decimal(source.get("arrived_qty") or 0) - Decimal(source.get("issued_qty") or 0),
        )
        pool_available = Decimal(source.get("pool_qty") or 0)
        available = (own_available + pool_available).quantize(Decimal("0.0001"))
        shortage = max(Decimal("0"), required - available).quantize(Decimal("0.0001"))
        line = dict(source)
        line.update(
            {
                "original_required_qty": source.get("required_qty"),
                "required_qty": required,
                "available_qty": available,
                "shortage_qty": shortage,
                "kit_ok": shortage <= 0,
            }
        )
        lines.append(line)

    size = db.get(Size, int(event.size_id)) if event.size_id else None
    empty_bom = len(lines) == 0
    return {
        "defect_id": event.id,
        "header_id": header.id,
        "header_no": header.header_no,
        "qty": int(event.qty or 0),
        "left_qty": int(event.left_qty or 0),
        "right_qty": int(event.right_qty or 0),
        "size_id": event.size_id,
        "size_value": size.size_value if size else None,
        "process_start_name": cumulative_processes[0].process_name if cumulative_processes else None,
        "process_end_name": cumulative_processes[-1].process_name if cumulative_processes else None,
        "lines": lines,
        "empty_bom": empty_bom,
        "kit_ok": (not empty_bom) and all(line["kit_ok"] for line in lines),
        "shortage_lines": sum(1 for line in lines if not line["kit_ok"]),
    }


def create_defect_material_replenishment(
    db: Session,
    *,
    tenant_id: int,
    defect_ids: list[int],
    created_by: int | None = None,
) -> dict:
    """将同一生产单的多条不良按码数和发现工序汇总为一张待确认补料单。"""
    normalized_ids = sorted({int(value) for value in defect_ids if int(value) > 0})
    if not normalized_ids:
        raise TraceError("defects_required", "请至少选择一条不良记录")
    events = list(
        db.scalars(
            select(DefectEvent)
            .where(
                DefectEvent.tenant_id == tenant_id,
                DefectEvent.id.in_(normalized_ids),
            )
            .order_by(DefectEvent.id)
        ).all()
    )
    if len(events) != len(normalized_ids):
        raise TraceError("defect_not_found", "部分不良记录不存在")
    header_ids = {int(event.header_id or 0) for event in events}
    if 0 in header_ids:
        raise TraceError("header_required", "所选不良必须关联生产单")
    if len(header_ids) != 1:
        raise TraceError("different_headers", "只能合并同一生产单的不良记录")
    header_id = next(iter(header_ids))
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise TraceError("header_not_found", "生产单不存在")
    if any(not event.size_id for event in events):
        raise TraceError("size_required", "所选不良存在未指定码数的记录")
    if any(not event.found_process_id for event in events):
        raise TraceError("process_required", "所选不良存在未指定发现工序的记录")

    prior_docs = db.scalars(
        select(StockDoc).where(
            StockDoc.tenant_id == tenant_id,
            StockDoc.doc_type == StockDocType.issue,
            StockDoc.status != StockDocStatus.void,
        )
    ).all()
    already_linked = {
        int(value)
        for doc in prior_docs
        for value in (getattr(doc, "defect_event_ids", None) or [])
    }.intersection(normalized_ids)
    if already_linked:
        joined = "、".join(f"#{value}" for value in sorted(already_linked))
        raise TraceError("already_replenished", f"不良 {joined} 已生成补料单")

    scope_filter = OrderProcess.header_id == header.id
    if header.shop_order_id:
        scope_filter = or_(scope_filter, OrderProcess.order_id == int(header.shop_order_id))
    processes = list(
        db.scalars(
            select(OrderProcess)
            .where(OrderProcess.tenant_id == tenant_id, scope_filter)
            .order_by(OrderProcess.id)
        ).all()
    )
    from app.services import material_service, stock_doc_service

    material_service.get_header_kit(db, tenant_id, header.id)
    req_filter = OrderMaterialRequirement.header_id == header.id
    if header.shop_order_id:
        req_filter = or_(
            req_filter,
            OrderMaterialRequirement.order_id == int(header.shop_order_id),
        )
    requirements = list(
        db.scalars(
            select(OrderMaterialRequirement).where(
                OrderMaterialRequirement.tenant_id == tenant_id,
                req_filter,
            )
        ).all()
    )
    quantities: dict[int, Decimal] = {}
    for event in events:
        target_index = next(
            (
                index
                for index, process in enumerate(processes)
                if int(process.process_id) == int(event.found_process_id)
            ),
            None,
        )
        if target_index is None:
            raise TraceError("process_not_found", f"不良 #{event.id} 的发现工序不在生产单路线中")
        cumulative_segment_ids = {
            int(process.segment_id)
            for process in processes[: target_index + 1]
            if process.segment_id
        }
        pieces = Decimal(int(event.qty or 0))
        for requirement in requirements:
            if requirement.is_customer_supplied:
                continue
            if requirement.consume_segment_id is not None and int(requirement.consume_segment_id) not in cumulative_segment_ids:
                continue
            if getattr(requirement, "usage_by_size", False) and int(requirement.size_id or 0) != int(event.size_id):
                continue
            usage = Decimal(requirement.qty_per_pair or 0)
            if getattr(requirement, "usage_by_size", False):
                usage *= Decimal(getattr(requirement, "size_coeff", 1) or 1)
            usage *= Decimal("1") + Decimal(requirement.loss_rate or 0)
            qty = (usage * pieces / Decimal("2")).quantize(Decimal("0.0001"))
            if qty > 0:
                quantities[int(requirement.id)] = quantities.get(int(requirement.id), Decimal("0")) + qty
    lines = [
        {"requirement_id": requirement_id, "qty": qty.quantize(Decimal("0.0001"))}
        for requirement_id, qty in sorted(quantities.items())
        if qty > 0
    ]
    if not lines:
        raise TraceError("materials_empty", "所选不良在发现工序前没有可补物料")
    try:
        return stock_doc_service.submit_stock_doc(
            db,
            tenant_id,
            doc_type="issue",
            header_id=header.id,
            lines=lines,
            notes=("不良补料：" + "、".join(f"#{value}" for value in normalized_ids))[:255],
            user_id=created_by,
            defect_event_ids=normalized_ids,
        )
    except material_service.MaterialError as exc:
        raise TraceError(exc.code, exc.message) from exc


def get_defect_detail(db: Session, *, tenant_id: int, defect_id: int) -> dict:
    event = db.get(DefectEvent, defect_id)
    if not event or event.tenant_id != tenant_id:
        raise TraceError("not_found", "不良记录不存在")
    result = defect_out(db, event)
    # 多码登记在存储层是一条码数一条事件。旧数据没有登记组 ID，按同一次提交
    # 的稳定公共字段和相邻创建时间还原，供编辑页一次展示全部码数。
    candidates = list(
        db.scalars(
            select(DefectEvent).where(
                DefectEvent.tenant_id == tenant_id,
                DefectEvent.header_id == event.header_id,
                DefectEvent.order_id == event.order_id,
                DefectEvent.found_by_worker_id == event.found_by_worker_id,
                DefectEvent.found_by_user_id == event.found_by_user_id,
            )
        ).all()
    )
    signature = (
        event.defect_type,
        event.found_process_id,
        event.brand_name or "",
        event.note or "",
        _enum_val(event.disposition),
        tuple(event.photo_urls or []),
    )
    grouped: list[DefectEvent] = []
    for candidate in candidates:
        candidate_signature = (
            candidate.defect_type,
            candidate.found_process_id,
            candidate.brand_name or "",
            candidate.note or "",
            _enum_val(candidate.disposition),
            tuple(candidate.photo_urls or []),
        )
        seconds_apart = abs((candidate.created_at - event.created_at).total_seconds())
        if candidate_signature == signature and seconds_apart <= 3:
            grouped.append(candidate)
    if not grouped:
        grouped = [event]
    result["registration_items"] = [
        defect_out(db, item)
        for item in sorted(grouped, key=lambda item: (str(db.get(Size, item.size_id).size_value) if item.size_id and db.get(Size, item.size_id) else "", item.id))
    ]
    from app.services import stock_doc_service

    result["material_docs"] = stock_doc_service.list_defect_material_docs(db, tenant_id, event.id)
    return result


def carrier_available_qty(db: Session, unit: TraceUnit) -> int:
    """合帮/入库可用数：载体 qty − 未关闭返修冻结；报废已扣减 qty 或整卡作废。"""
    st = _enum_val(unit.status)
    if st in (
        TraceUnitStatus.scrapped.value,
        TraceUnitStatus.split.value,
        TraceUnitStatus.warehoused.value,
        TraceUnitStatus.shipped.value,
    ):
        return 0
    base = int(unit.qty or 0)
    frozen = (
        db.scalar(
            select(func.coalesce(func.sum(DefectEvent.qty), 0)).where(
                DefectEvent.trace_unit_id == unit.id,
                DefectEvent.status == DefectEventStatus.open,
                DefectEvent.disposition == DefectDisposition.rework,
            )
        )
        or 0
    )
    return max(0, base - int(frozen))


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
    order_id: int | None = None,
    qty: int,
    color_id: int | None = None,
    size_id: int | None = None,
    worker_id: int | None = None,
    process_id: int | None = None,
    work_log_id: int | None = None,
    station_id: int | None = None,
    note: str | None = None,
    parent_id: int | None = None,
    part_id: int | None = None,
    unit_type: TraceUnitType = TraceUnitType.bundle,
    execution_id: int | None = None,
    header_id: int | None = None,
    sales_order_id: int | None = None,
    batch_id: int | None = None,
    commit: bool = True,
) -> TraceUnit:
    if qty <= 0:
        raise TraceError("invalid_qty", "数量必须大于 0")
    if order_id is None and header_id is None:
        raise TraceError("order_or_header_required", "须指定生产单")

    order = None
    own_product_id: int | None = None
    if order_id is not None:
        order = db.get(Order, order_id)
        if not order or order.tenant_id != tenant_id:
            raise TraceError("order_not_found", "订单不存在")
        own_product_id = order.own_product_id
    else:
        from app.models import ExecutionHeader

        header = db.get(ExecutionHeader, int(header_id))
        if not header or header.tenant_id != tenant_id:
            raise TraceError("header_not_found", "生产单不存在")
        own_product_id = header.own_product_id

    product = db.get(OwnProduct, own_product_id)
    if not product or product.tenant_id != tenant_id:
        raise TraceError("product_not_found", "产品不存在")

    if worker_id is not None:
        w = db.get(Employee, worker_id)
        if not w or w.tenant_id != tenant_id:
            raise TraceError("worker_not_found", "工人不存在")

    if parent_id is not None:
        parent = db.get(TraceUnit, parent_id)
        if not parent or parent.tenant_id != tenant_id:
            raise TraceError("parent_not_found", "所属筐卡不存在")
        if order is not None and parent.order_id != order.id:
            raise TraceError("parent_not_found", "所属筐卡不存在")
        if order is None and int(parent.header_id or 0) != int(header_id):
            raise TraceError("parent_not_found", "所属筐卡不存在")
        if parent.unit_type != TraceUnitType.basket:
            raise TraceError("invalid_parent", "父单元须为流转卡(筐)")

    from app.services.material_service import resolve_header_id_for_write

    resolved_header_id = resolve_header_id_for_write(
        db,
        tenant_id,
        order_id=order.id if order else None,
        execution_id=execution_id,
        header_id=header_id,
    )

    unit = TraceUnit(
        tenant_id=tenant_id,
        code=f"TMP-{tenant_id}",  # flush 前占位，随后覆盖
        unit_type=unit_type,
        qty=qty,
        parent_id=parent_id,
        part_id=part_id,
        order_id=order.id if order else None,
        execution_id=execution_id,
        header_id=resolved_header_id,
        sales_order_id=sales_order_id,
        batch_id=batch_id,
        own_product_id=own_product_id,
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

    action_note = note
    if not action_note:
        if unit_type == TraceUnitType.basket:
            action_note = "开裁流转卡"
        else:
            action_note = "打捆"

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
            note=action_note,
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
    log_header_id = getattr(log, "header_id", None)
    if not log.order_id and not log_header_id:
        raise TraceError("order_not_found", "报工无桥接单/生产单，暂无法打捆")

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
        header_id=log_header_id,
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


def _active_units_for_header(db: Session, *, tenant_id: int, header_id: int) -> list[TraceUnit]:
    return list(
        db.scalars(
            select(TraceUnit).where(
                TraceUnit.tenant_id == tenant_id,
                TraceUnit.header_id == header_id,
                TraceUnit.status != TraceUnitStatus.scrapped,
            )
        ).all()
    )


def preview_or_create_cut_cards(
    db: Session,
    *,
    tenant_id: int,
    order_id: int | None = None,
    header_id: int | None = None,
    dry_run: bool = True,
    bundle_size: int | None = None,
    only_missing: bool = True,
    mode: str | None = None,
    execution_id: int | None = None,
    batch_qtys: list[int] | None = None,
    target_qty_by_size: dict[int, int] | None = None,
    force_new_batch: bool = False,
    commit: bool = True,
) -> dict:
    """开裁打卡生码。

    mode:
      - bundles：一码一捆
      - basket_bundles：有部件清单时 1 筐 N 捆；无部件且开追溯回退 bundles；关追溯回退仅筐
      - basket：仅流转卡、不打扎捆。开追溯禁止。

    execution_id：AU-I1 规格执行单；未传时若桥接生产单有未取消执行单则自动挂上。
    header_id：K4-B 认执行单头色码明细（无桥接壳）。
    batch_qtys：D25/P7 开裁分批。空/None=不分批（自动一个默认批次号，复用活动批次）；
      非空=按每批双数拆多个批次号，本批生成的筐按顺序挂批。
    """
    from types import SimpleNamespace

    from app.models import (
        ExecutionHeader,
        OwnProductPart,
        PartDefinition,
        SpecExecutionOrder,
        SpecExecutionStatus,
    )
    from app.services import shop_floor_settings

    if header_id is None and order_id is None:
        raise TraceError("order_or_header_required", "须指定生产单")

    order = None
    header: ExecutionHeader | None = None
    if header_id is not None:
        header = db.get(ExecutionHeader, int(header_id))
        if not header or header.tenant_id != tenant_id:
            raise TraceError("header_not_found", "生产单不存在")
        if order_id is not None:
            order = db.get(Order, order_id)
            if not order or order.tenant_id != tenant_id:
                raise TraceError("order_not_found", "生产单不存在")
        elif header.shop_order_id:
            order = db.get(Order, header.shop_order_id)
    else:
        order = db.get(Order, order_id)
        if not order or order.tenant_id != tenant_id:
            raise TraceError("order_not_found", "生产单不存在")

    resolved_execution_id = execution_id
    execution_no = None
    allocation_sources: list[dict] = []
    shop_size_execution_map: dict[int, int] = {}
    if header is not None:
        exe_rows = list(
            db.scalars(
                select(SpecExecutionOrder)
                .where(
                    SpecExecutionOrder.tenant_id == tenant_id,
                    SpecExecutionOrder.header_id == header.id,
                    SpecExecutionOrder.status != SpecExecutionStatus.cancelled,
                )
                .order_by(SpecExecutionOrder.id)
            ).all()
        )
        for exe_row in exe_rows:
            if exe_row.size_id:
                shop_size_execution_map[int(exe_row.size_id)] = int(exe_row.id)
        if resolved_execution_id is None and len(exe_rows) == 1:
            resolved_execution_id = exe_rows[0].id
        execution_no = header.header_no
        items = [
            SimpleNamespace(
                color_id=exe_row.color_id or header.color_id,
                size_id=exe_row.size_id,
                qty=(
                    min(
                        int(exe_row.total_qty or 0),
                        max(0, int(target_qty_by_size[int(exe_row.size_id)])),
                    )
                    if target_qty_by_size is not None
                    and exe_row.size_id is not None
                    and int(exe_row.size_id) in target_qty_by_size
                    else (0 if target_qty_by_size is not None else int(exe_row.total_qty or 0))
                ),
            )
            for exe_row in exe_rows
        ]
        product = db.get(OwnProduct, header.own_product_id)
    else:
        if resolved_execution_id is None:
            exe_rows = list(
                db.scalars(
                    select(SpecExecutionOrder)
                    .where(
                        SpecExecutionOrder.tenant_id == tenant_id,
                        SpecExecutionOrder.shop_order_id == order.id,
                        SpecExecutionOrder.status != SpecExecutionStatus.cancelled,
                    )
                    .order_by(SpecExecutionOrder.id)
                ).all()
            )
            for exe_row in exe_rows:
                if exe_row.size_id:
                    shop_size_execution_map[int(exe_row.size_id)] = int(exe_row.id)
            if len(exe_rows) == 1:
                resolved_execution_id = exe_rows[0].id
        items = list(
            db.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
            ).all()
        )
        product = db.get(OwnProduct, order.own_product_id)

    if resolved_execution_id is not None:
        from app.services.execution_service import allocation_sources_for_execution

        exe = db.get(SpecExecutionOrder, resolved_execution_id)
        if not exe or exe.tenant_id != tenant_id:
            raise TraceError("execution_not_found", "规格生产单不存在")
        if exe.status == SpecExecutionStatus.cancelled:
            raise TraceError("execution_cancelled", "生产单已取消，不能开裁")
        if order is not None and exe.shop_order_id and int(exe.shop_order_id) != int(order.id):
            raise TraceError("execution_order_mismatch", "生产单与生产单不匹配")
        if header is not None and exe.header_id and int(exe.header_id) != int(header.id):
            raise TraceError("execution_header_mismatch", "码明细与生产单不匹配")
        execution_no = exe.execution_no if header is None else (header.header_no or exe.execution_no)
        allocation_sources = allocation_sources_for_execution(db, exe.id)
    elif shop_size_execution_map:
        # 多码明细：开裁按尺码挂对应码明细
        from app.services.execution_service import allocation_sources_for_execution

        first_eid = next(iter(shop_size_execution_map.values()))
        first_exe = db.get(SpecExecutionOrder, first_eid)
        if header is not None:
            execution_no = header.header_no
        elif first_exe and first_exe.header_id:
            hdr = db.get(ExecutionHeader, first_exe.header_id)
            execution_no = hdr.header_no if hdr else first_exe.execution_no
        elif first_exe:
            execution_no = first_exe.execution_no
        # 汇总各码来源（预览用）
        seen_so: set[int] = set()
        for eid in shop_size_execution_map.values():
            for src in allocation_sources_for_execution(db, eid):
                key = int(src.get("sales_order_id") or 0)
                if key in seen_so:
                    continue
                seen_so.add(key)
                allocation_sources.append(src)

    def _eid_for_size(size_id: int | None) -> int | None:
        if resolved_execution_id is not None:
            return resolved_execution_id
        if size_id is None:
            return None
        return shop_size_execution_map.get(int(size_id))

    if not product or product.tenant_id != tenant_id:
        raise TraceError("product_not_found", "产品不存在")

    if not items:
        raise TraceError(
            "no_items",
            "生产单无色码明细，请先维护色码后再开裁"
            if header is not None
            else "生产单无色码明细，请先维护色码后再开裁",
        )

    if bundle_size is not None and bundle_size <= 0:
        raise TraceError("invalid_bundle_size", "捆量/筐量须为正整数")

    parts = list(
        db.scalars(
            select(OwnProductPart)
            .where(
                OwnProductPart.tenant_id == tenant_id,
                OwnProductPart.own_product_id == product.id,
            )
            .order_by(OwnProductPart.sort_order, OwnProductPart.id)
        ).all()
    )
    # AU-I0 M2 开裁收敛：历史 bundles / basket_bundles mode 一律按筐处理，
    # 只出流转卡（筐）、不再打扎捆码、不再有 trace_requires_bundle 报错。
    resolved_mode = "basket"
    if bundle_size is None:
        sf = shop_floor_settings.get_shop_floor_by_tenant_id(db, tenant_id)
        bundle_size = int(sf.get("basket_pairs_cutting") or 40)

    if header is not None:
        existing = _active_units_for_header(db, tenant_id=tenant_id, header_id=header.id)
    else:
        existing = _active_units_for_order(db, tenant_id=tenant_id, order_id=order.id)
    cut_header_id = header.id if header is not None else None
    cut_order_id = order.id if order is not None else None
    lines: list[dict] = []
    # basket: (item, qty, sales_order_id)
    planned_creates: list[tuple] = []

    # 合单分筐：有执行分配时按销售订单拆独立筐（各筐打 sales_order_id 戳）
    so_splits: list[dict] = []
    if allocation_sources:
        so_splits = [
            {"sales_order_id": int(a["sales_order_id"]), "qty": int(a.get("qty") or 0)}
            for a in allocation_sources
            if a.get("sales_order_id") and int(a.get("qty") or 0) > 0
        ]

    def _so_targets(item_qty: int) -> list[tuple[int | None, int]]:
        """把 item_qty 按执行分配比例拆到各销售订单；无分配 → [(None, item_qty)]。"""
        if not so_splits:
            return [(None, item_qty)]
        total = sum(s["qty"] for s in so_splits)
        if total <= 0:
            return [(None, item_qty)]
        bases = [(s["sales_order_id"], item_qty * s["qty"] // total) for s in so_splits]
        assigned = sum(b for _, b in bases)
        rem = item_qty - assigned
        order = sorted(
            range(len(so_splits)),
            key=lambda i: (item_qty * so_splits[i]["qty"] % total, -i),
            reverse=True,
        )
        for i in order[:rem]:
            bases[i] = (bases[i][0], bases[i][1] + 1)
        return [(so_id, q) for so_id, q in bases if q > 0]

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

        for so_id, so_qty in _so_targets(int(item.qty or 0)):
            same = [
                u
                for u in existing
                if u.color_id == item.color_id
                and u.size_id == item.size_id
                and u.unit_type == TraceUnitType.basket
                and int(u.sales_order_id or 0) == int(so_id or 0)
            ]
            covered = sum(int(u.qty or 0) for u in same)
            line_base = {
                **base,
                "existing_unit_ids": [u.id for u in same],
                "sales_order_id": so_id,
            }

            if only_missing and covered >= so_qty:
                lines.append(
                    {
                        **line_base,
                        "action": "skip_exists",
                        "reason": f"已有活跃筐合计 {covered} 双，已覆盖本行",
                        "planned_units": [],
                    }
                )
                continue
            remain = so_qty - covered if only_missing else so_qty
            if remain <= 0:
                lines.append(
                    {
                        **line_base,
                        "action": "skip_exists",
                        "reason": "已覆盖",
                        "planned_units": [],
                    }
                )
                continue

            qtys = _plan_bundle_qtys(remain, bundle_size)
            planned = [{"qty": q, "unit_type": "basket"} for q in qtys]
            lines.append({**line_base, "action": "create", "planned_units": planned, "reason": None})
            for q in qtys:
                planned_creates.append((item, q, so_id))

    to_create = len(planned_creates)
    created: list[dict] = []
    batches: list[dict] = []
    batch_rows: list = []
    assigned: list[int] = []
    material_consumption: list[dict] = []

    # D25/P7：开裁建批。dry_run 只算批次号/筐数；落库时建批（复用活动批），筐按顺序挂批。
    from app.services import batch_service

    if planned_creates:
        if dry_run:
            batches = batch_service.batches_preview(
                db,
                tenant_id,
                header_id=cut_header_id,
                order_id=cut_order_id,
                planned=planned_creates,
                batch_qtys=batch_qtys,
                force_new=force_new_batch,
            )
        else:
            batch_rows, assigned = batch_service.ensure_batches_for_cut(
                db,
                tenant_id,
                header_id=cut_header_id,
                order_id=cut_order_id,
                product_id=product.id,
                batch_qtys=batch_qtys,
                planned=planned_creates,
                force_new=force_new_batch,
            )
            batches = [
                {"batch_no": b.batch_no, "qty": b.qty or 0, "unit_count": assigned.count(i)}
                for i, b in enumerate(batch_rows)
            ]
            for i, batch in enumerate(batch_rows):
                size_qtys: dict[int, int] = {}
                for idx, (item, qty, _so_id) in enumerate(planned_creates):
                    if idx >= len(assigned) or assigned[idx] != i or not item.size_id:
                        continue
                    sid = int(item.size_id)
                    size_qtys[sid] = size_qtys.get(sid, 0) + int(qty)
                snapshots = batch_service.snapshot_batch_material_consumption(
                    db,
                    tenant_id,
                    batch=batch,
                    size_qtys=size_qtys,
                )
                material_consumption.extend(
                    {
                        "batch_id": batch.id,
                        "batch_no": batch.batch_no,
                        "requirement_id": row.requirement_id,
                        "supplier_product_id": row.supplier_product_id,
                        "size_id": row.size_id,
                        "batch_pairs": row.batch_pairs,
                        "theoretical_qty": float(row.theoretical_qty),
                    }
                    for row in snapshots
                )
    # 无新筐：本次不涉及批次

    if not dry_run and planned_creates:
        touched_execution_ids: set[int] = set()
        for idx, (item, q, so_id) in enumerate(planned_creates):
            eid = _eid_for_size(item.size_id)
            if eid is not None:
                touched_execution_ids.add(int(eid))
            bid = (
                batch_rows[assigned[idx]].id
                if batch_rows and assigned and idx < len(assigned)
                else None
            )
            basket = create_bundle(
                db,
                tenant_id=tenant_id,
                order_id=cut_order_id,
                qty=q,
                color_id=item.color_id,
                size_id=item.size_id,
                unit_type=TraceUnitType.basket,
                execution_id=eid,
                header_id=cut_header_id,
                sales_order_id=so_id,
                batch_id=bid,
                note="开裁流转卡",
                commit=False,
            )
            created.append(
                {
                    "id": basket.id,
                    "code": basket.code,
                    "qty": basket.qty,
                    "color_id": basket.color_id,
                    "size_id": basket.size_id,
                    "unit_type": "basket",
                    "execution_id": eid,
                    "sales_order_id": so_id,
                    "batch_id": bid,
                    "children": None,
                }
            )
        for eid in touched_execution_ids:
            exe = db.get(SpecExecutionOrder, eid)
            if exe and exe.status == SpecExecutionStatus.confirmed:
                exe.status = SpecExecutionStatus.cut
            if exe and exe.header_id:
                from app.models import ExecutionHeader

                hdr = db.get(ExecutionHeader, exe.header_id)
                if hdr and hdr.status in (
                    SpecExecutionStatus.confirmed,
                    SpecExecutionStatus.cut,
                ):
                    hdr.status = SpecExecutionStatus.cut
                    from app.services.execution_service import sync_sales_order_line_status_from_header

                    sync_sales_order_line_status_from_header(db, hdr)
        if commit:
            db.commit()
            for c in created:
                u = db.get(TraceUnit, c["id"])
                if u:
                    db.refresh(u)
                    c["code"] = u.code
                for ch in c.get("children") or []:
                    cu = db.get(TraceUnit, ch["id"])
                    if cu:
                        db.refresh(cu)
                        ch["code"] = cu.code

    # 开裁后默认打开框码标签页（标签打印机）；流转卡另入口打印
    print_path = (
        f"/admin/executions/print/{header.id}?mode=basket-labels"
        if header is not None
        else f"/admin/orders/print/{order.id}?mode=basket-labels"
    )
    return {
        "order_id": order.id if order else None,
        "order_no": order.order_no if order else None,
        "header_id": header.id if header else cut_header_id,
        "header_no": header.header_no if header else None,
        "execution_id": resolved_execution_id,
        "execution_no": execution_no,
        "allocation_sources": allocation_sources,
        "mode": resolved_mode,
        "strategy": {"bundle_size": bundle_size, "parts": len(parts)},
        "lines": lines,
        "to_create": to_create,
        "created": created,
        "batches": batches,
        "batch_ids": [b.id for b in batch_rows],
        "material_consumption": material_consumption,
        "print_path": print_path,
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
        raise TraceError("trace_not_found", "框码不存在")

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
        empty["basis"] = "框码不存在"
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
        w = db.get(Employee, wid)
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


def header_has_active_bundles(db: Session, *, tenant_id: int, header_id: int) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(TraceUnit)
            .where(
                TraceUnit.tenant_id == tenant_id,
                TraceUnit.header_id == header_id,
                TraceUnit.status.in_(list(ACTIVE_BUNDLE_STATUSES)),
            )
        )
        or 0
    ) > 0


def _resolve_defect_header_id(
    db: Session,
    *,
    unit: TraceUnit | None,
    order_id: int | None,
) -> int | None:
    """K4-E：从捆/码明细/订单桥接解析执行单头。"""
    if unit is not None:
        hid = getattr(unit, "header_id", None)
        if hid:
            return int(hid)
        eid = getattr(unit, "execution_id", None)
        if eid:
            from app.models import SpecExecutionOrder

            exe = db.get(SpecExecutionOrder, int(eid))
            if exe and exe.header_id:
                return int(exe.header_id)
    if order_id:
        from app.models import SpecExecutionOrder

        hid = db.scalar(
            select(SpecExecutionOrder.header_id)
            .where(
                SpecExecutionOrder.shop_order_id == order_id,
                SpecExecutionOrder.header_id.is_not(None),
            )
            .order_by(SpecExecutionOrder.id.desc())
            .limit(1)
        )
        if hid:
            return int(hid)
    return None


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
    # 框码只服务裁断→针车。最后一道针车工序报工后结束线上流转；
    # 成型改扫生产流转卡汇总报工，空框随货到线后直接线下回收。
    process_row = db.get(OrderProcess, work_log.order_process_id)
    if process_row and process_row.segment_id:
        from app.models import ProcessSegment

        segment = db.get(ProcessSegment, process_row.segment_id)
        if segment and segment.code == "stitch":
            ref_clause = (
                OrderProcess.header_id == process_row.header_id
                if process_row.header_id
                else OrderProcess.order_id == process_row.order_id
            )
            later_stitch = db.scalar(
                select(func.count())
                .select_from(OrderProcess)
                .where(
                    OrderProcess.tenant_id == tenant_id,
                    ref_clause,
                    OrderProcess.segment_id == process_row.segment_id,
                    OrderProcess.id > process_row.id,
                )
            )
            if not later_stitch:
                unit.status = TraceUnitStatus.done
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


def _normalize_photo_urls(photo_urls: list[str] | None) -> list[str] | None:
    if not photo_urls:
        return None
    cleaned = [url.strip() for url in photo_urls if isinstance(url, str) and url.strip()]
    return cleaned or None


DEFECT_SOURCE_VALUES = {"internal", "subcontract"}
RESPONSIBLE_PARTY_VALUES = {"employee", "subcontractor"}


def _validate_defect_sources(scrap_source: str, replacement_source: str) -> None:
    if scrap_source not in DEFECT_SOURCE_VALUES:
        raise TraceError("invalid_scrap_source", "报废类型无效")
    if replacement_source not in DEFECT_SOURCE_VALUES:
        raise TraceError("invalid_replacement_source", "后续生产方式无效")
    if scrap_source != "subcontract" and replacement_source == "subcontract":
        raise TraceError("invalid_replacement_source", "只有外加工报废才能选择外加工生产")


def _header_has_open_subcontract_orders(db: Session, tenant_id: int, header_id: int | None) -> bool:
    if not header_id:
        return False
    return db.scalar(
        select(SubcontractOrder.id).where(
            SubcontractOrder.tenant_id == tenant_id,
            SubcontractOrder.header_id == int(header_id),
            SubcontractOrder.status != SubcontractOrderStatus.cancelled,
        ).limit(1)
    ) is not None


def _normalize_responsible_party_type(
    value: str | None,
    *,
    subcontract_order_id: int | None = None,
) -> str:
    party = (value or "").strip() or ("subcontractor" if subcontract_order_id else "employee")
    if party not in RESPONSIBLE_PARTY_VALUES:
        raise TraceError("invalid_responsible_party", "责任人类型无效")
    return party


def _subcontract_first_process_id(db: Session, order: SubcontractOrder | None) -> int | None:
    if not order:
        return None
    route_ids = [int(value) for value in (order.order_process_ids or []) if int(value or 0) > 0]
    if route_ids:
        route = db.get(OrderProcess, route_ids[0])
        if route and route.process_id:
            return int(route.process_id)
    if order.process_id:
        return int(order.process_id)
    return None


def _bind_subcontract_order_for_defect(
    db: Session,
    *,
    tenant_id: int,
    header_id: int | None,
    scrap_source: str,
    subcontract_order_id: int | None,
    responsible_party_type: str = "employee",
) -> int | None:
    order_id = int(subcontract_order_id) if subcontract_order_id else None
    if order_id:
        order = db.get(SubcontractOrder, order_id)
        if not order or order.tenant_id != tenant_id:
            raise TraceError("subcontract_order_not_found", "外发单不存在")
        if order.status == SubcontractOrderStatus.cancelled:
            raise TraceError("subcontract_order_cancelled", "已取消的外发单不能登记报废")
        if header_id and order.header_id and int(order.header_id) != int(header_id):
            raise TraceError("subcontract_order_mismatch", "外发单不属于当前生产单")
        return order.id
    if responsible_party_type == "subcontractor":
        raise TraceError("subcontract_order_required", "请选择对应的外发单")
    if scrap_source == "subcontract" and _header_has_open_subcontract_orders(db, tenant_id, header_id):
        raise TraceError("subcontract_order_required", "请选择对应的外发单")
    return None


def _calculate_defect_loss(
    db: Session,
    *,
    tenant_id: int,
    header_id: int,
    found_process_id: int,
    size_id: int | None,
    qty: int,
    scrap_source: str,
    responsible_party_type: str = "employee",
    subcontract_order_id: int | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    if (responsible_party_type or "employee") == "subcontractor":
        order = db.get(SubcontractOrder, int(subcontract_order_id)) if subcontract_order_id else None
        if not order or order.tenant_id != tenant_id:
            raise TraceError("subcontract_order_required", "请选择对应的外发单")
        unit = (Decimal(str(order.material_unit_price or 0)) / Decimal("2")).quantize(Decimal("0.0001"))
        material = (unit * Decimal(qty)).quantize(Decimal("0.01"))
        zero = Decimal("0.00")
        return material, zero, material
    header = db.get(ExecutionHeader, header_id)
    if not header or header.tenant_id != tenant_id:
        raise TraceError("header_not_found", "生产单不存在")
    owner_filters = [OrderProcess.header_id == header.id]
    if header.shop_order_id:
        owner_filters.append(OrderProcess.order_id == int(header.shop_order_id))
    route = db.scalar(
        select(OrderProcess)
        .where(
            OrderProcess.tenant_id == tenant_id,
            or_(*owner_filters),
            OrderProcess.process_id == found_process_id,
        )
        .order_by(OrderProcess.id)
    )
    if not route:
        raise TraceError("process_not_found", "发现工序不在当前生产单路线中")
    quote = calculate_defect_loss_quote(
        db,
        tenant_id=tenant_id,
        header_id=header.id,
        order_process_id=route.id,
    )
    size_quote = quote.get("by_size", {}).get(str(size_id), {}) if size_id else {}
    material_unit = Decimal(
        str(size_quote.get("material_per_piece", quote.get("material_per_piece", 0)))
    )
    labor_unit = Decimal(
        str(
            quote.get("labor_before_process_per_piece", 0)
            if scrap_source == "subcontract"
            else quote.get("labor_per_piece", 0)
        )
    )
    material = (material_unit * Decimal(qty)).quantize(Decimal("0.01"))
    labor = (labor_unit * Decimal(qty)).quantize(Decimal("0.01"))
    return material, labor, (material + labor).quantize(Decimal("0.01"))


def create_defect_event(
    db: Session,
    *,
    tenant_id: int,
    defect_type: str,
    qty: int,
    order_id: int | None = None,
    header_id: int | None = None,
    trace_unit_id: int | None = None,
    color_id: int | None = None,
    size_id: int | None = None,
    found_process_id: int | None = None,
    responsible_process_id: int | None = None,
    responsible_worker_id: int | None = None,
    brand_name: str | None = None,
    left_qty: int = 0,
    right_qty: int = 0,
    disposition: str = "rework",
    scrap_source: str | None = None,
    subcontract_order_id: int | None = None,
    responsible_party_type: str | None = None,
    replacement_source: str | None = None,
    found_by_worker_id: int | None = None,
    found_by_user_id: int | None = None,
    note: str | None = None,
    auto_suggest_worker: bool = True,
    batch_id: int | None = None,
    photo_urls: list[str] | None = None,
    loss_amount: Decimal | float | int | None = None,
    company_share_percent: int | None = None,
    responsibilities: list[dict] | None = None,
) -> DefectEvent:
    if qty <= 0:
        raise TraceError("invalid_qty", "不良数量必须大于 0")
    if left_qty < 0 or right_qty < 0:
        raise TraceError("invalid_side_qty", "左脚、右脚数量不能小于 0")
    if (left_qty or right_qty) and qty != left_qty + right_qty:
        raise TraceError("invalid_side_total", "不良数量必须等于左脚与右脚数量合计")
    if defect_type not in DEFECT_TYPE_CODES:
        raise TraceError("invalid_defect_type", f"不支持的缺陷类型：{defect_type}")

    unit: TraceUnit | None = None
    if trace_unit_id is not None:
        unit = db.get(TraceUnit, trace_unit_id)
        if not unit or unit.tenant_id != tenant_id:
            raise TraceError("trace_not_found", "框码不存在")
        order_id = order_id or unit.order_id
        color_id = color_id if color_id is not None else unit.color_id
        size_id = size_id if size_id is not None else unit.size_id

    header_id = header_id or _resolve_defect_header_id(db, unit=unit, order_id=order_id)
    if header_id:
        header = db.get(ExecutionHeader, header_id)
        if not header or header.tenant_id != tenant_id:
            raise TraceError("header_not_found", "生产单不存在")
        # 兼容旧桥接订单；业务主关联仍是 header_id。
        order_id = order_id or header.shop_order_id

    if not order_id and not header_id:
        raise TraceError("order_required", "请选择生产单/订单或扫框码")

    order = None
    if order_id:
        order = db.get(Order, order_id)
        if not order or order.tenant_id != tenant_id:
            raise TraceError("order_not_found", "订单不存在")

    if unit is None:
        if order is not None and order_has_active_bundles(
            db, tenant_id=tenant_id, order_id=order.id
        ):
            raise TraceError(
                "trace_unit_required",
                "本单有进行中框码，请选择框码后再登记",
            )
        if order is None and header_id is not None and header_has_active_bundles(
            db, tenant_id=tenant_id, header_id=header_id
        ):
            raise TraceError(
                "trace_unit_required",
                "本单有进行中框码，请选择框码后再登记",
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
        w = db.get(Employee, responsible_worker_id)
        if not w or w.tenant_id != tenant_id:
            raise TraceError("worker_not_found", "责任人不存在")

    normalized_scrap_source = scrap_source or "internal"
    if subcontract_order_id:
        normalized_scrap_source = "subcontract"
    party_type = _normalize_responsible_party_type(
        responsible_party_type,
        subcontract_order_id=subcontract_order_id,
    )
    if party_type == "subcontractor":
        normalized_scrap_source = "subcontract"
    normalized_replacement_source = replacement_source or "internal"
    _validate_defect_sources(normalized_scrap_source, normalized_replacement_source)
    linked_subcontract_order_id = _bind_subcontract_order_for_defect(
        db,
        tenant_id=tenant_id,
        header_id=header_id,
        scrap_source=normalized_scrap_source,
        subcontract_order_id=subcontract_order_id,
        responsible_party_type=party_type,
    )
    if party_type == "subcontractor" and linked_subcontract_order_id:
        first_process_id = _subcontract_first_process_id(
            db, db.get(SubcontractOrder, linked_subcontract_order_id)
        )
        if first_process_id:
            found_process_id = first_process_id
    event = DefectEvent(
        tenant_id=tenant_id,
        trace_unit_id=unit.id if unit else None,
        order_id=order.id if order else None,
        header_id=header_id,
        color_id=color_id,
        size_id=size_id,
        found_process_id=found_process_id,
        responsible_process_id=responsible_process_id,
        responsible_worker_id=responsible_worker_id,
        brand_name=(brand_name or "").strip() or None,
        defect_type=defect_type,
        qty=qty,
        left_qty=left_qty,
        right_qty=right_qty,
        disposition=disp,
        scrap_source=normalized_scrap_source,
        subcontract_order_id=linked_subcontract_order_id,
        responsible_party_type=party_type,
        replacement_source=normalized_replacement_source,
        found_by_worker_id=found_by_worker_id,
        found_by_user_id=found_by_user_id,
        note=note,
        batch_id=batch_id,
        photo_urls=_normalize_photo_urls(photo_urls),
        status=DefectEventStatus.open,
    )
    db.add(event)
    db.flush()

    effective_loss_amount = loss_amount
    if scrap_source is not None:
        if not header_id or not found_process_id:
            raise TraceError("loss_basis_required", "自动计算损失需要生产单和发现工序")
        material_loss, labor_loss, effective_loss_amount = _calculate_defect_loss(
            db,
            tenant_id=tenant_id,
            header_id=int(header_id),
            found_process_id=int(found_process_id),
            size_id=size_id,
            qty=qty,
            scrap_source=normalized_scrap_source,
            responsible_party_type=party_type,
            subcontract_order_id=linked_subcontract_order_id,
        )
        event.material_loss_amount = material_loss
        event.labor_loss_amount = labor_loss
    if effective_loss_amount is not None or company_share_percent is not None or responsibilities is not None:
        apply_defect_loss_allocation(
            db,
            tenant_id=tenant_id,
            event=event,
            loss_amount=effective_loss_amount if effective_loss_amount is not None else 0,
            company_share_percent=company_share_percent if company_share_percent is not None else 100,
            responsibilities=responsibilities,
            responsible_party_type=party_type,
        )

    _auto_close_factory_defect(event)

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
        # 报废必须先开补开裁；实物扣减由 confirm_defect_scrap 完成。

    db.commit()
    db.refresh(event)
    return event


def create_defect_events_batch(
    db: Session,
    *,
    tenant_id: int,
    defect_type: str,
    size_lines: list[dict],
    order_id: int | None = None,
    header_id: int | None = None,
    trace_unit_id: int | None = None,
    color_id: int | None = None,
    found_process_id: int | None = None,
    responsible_process_id: int | None = None,
    responsible_worker_id: int | None = None,
    brand_name: str | None = None,
    disposition: str = "rework",
    scrap_source: str | None = None,
    subcontract_order_id: int | None = None,
    responsible_party_type: str | None = None,
    replacement_source: str | None = None,
    found_by_worker_id: int | None = None,
    found_by_user_id: int | None = None,
    note: str | None = None,
    auto_suggest_worker: bool = True,
    batch_id: int | None = None,
    photo_urls: list[str] | None = None,
    loss_amount: Decimal | float | int | None = None,
    company_share_percent: int | None = None,
    responsibilities: list[dict] | None = None,
) -> list[DefectEvent]:
    if not size_lines:
        raise TraceError("size_lines_required", "请至少填写一个码数")
    seen_sizes: set[int] = set()
    events: list[DefectEvent] = []
    for line in size_lines:
        size_id = int(line.get("size_id") or 0)
        if size_id <= 0:
            raise TraceError("size_required", "请选择码数")
        if size_id in seen_sizes:
            raise TraceError("duplicate_size", "同一码数请勿重复登记")
        seen_sizes.add(size_id)
        left_qty = int(line.get("left_qty") or 0)
        right_qty = int(line.get("right_qty") or 0)
        qty = left_qty + right_qty
        if qty <= 0:
            raise TraceError("invalid_qty", "不良数量必须大于 0")
        event = create_defect_event(
            db,
            tenant_id=tenant_id,
            defect_type=defect_type,
            qty=qty,
            order_id=order_id,
            header_id=header_id,
            trace_unit_id=trace_unit_id,
            color_id=color_id,
            size_id=size_id,
            found_process_id=found_process_id,
            responsible_process_id=responsible_process_id,
            responsible_worker_id=responsible_worker_id,
            brand_name=brand_name,
            left_qty=left_qty,
            right_qty=right_qty,
            disposition=disposition,
            scrap_source=scrap_source,
            subcontract_order_id=subcontract_order_id,
            responsible_party_type=responsible_party_type,
            replacement_source=replacement_source,
            found_by_worker_id=found_by_worker_id,
            found_by_user_id=found_by_user_id,
            note=note,
            auto_suggest_worker=auto_suggest_worker,
            batch_id=batch_id,
            photo_urls=photo_urls,
            loss_amount=(
                Decimal(str(line["loss_amount"]))
                if line.get("loss_amount") is not None
                else loss_amount
            ),
            company_share_percent=company_share_percent,
            responsibilities=responsibilities,
        )
        events.append(event)
    return events


def add_defect_size_lines(
    db: Session,
    *,
    tenant_id: int,
    defect_id: int,
    size_lines: list[dict],
) -> list[DefectEvent]:
    """Add sizes to an existing multi-size defect registration."""
    source = db.get(DefectEvent, defect_id)
    if not source or source.tenant_id != tenant_id:
        raise TraceError("not_found", "报废记录不存在")

    detail = get_defect_detail(db, tenant_id=tenant_id, defect_id=defect_id)
    existing_size_ids = {
        int(item["size_id"])
        for item in detail.get("registration_items") or []
        if item.get("size_id")
    }
    requested_size_ids = [int(line.get("size_id") or 0) for line in size_lines]
    if any(size_id in existing_size_ids for size_id in requested_size_ids):
        raise TraceError("duplicate_size", "同一码数不能重复")

    responsibilities = [
        {"worker_id": int(row.worker_id), "share_percent": int(row.share_percent)}
        for row in db.scalars(
            select(DefectResponsibility).where(
                DefectResponsibility.tenant_id == tenant_id,
                DefectResponsibility.defect_event_id == source.id,
            )
        ).all()
    ]
    effective_party_type = source.responsible_party_type
    if source.scrap_source == "subcontract" and source.subcontract_order_id and not responsibilities:
        # Older edit flows could persist the external order before the party type.
        # With no employee allocation, the external order is the responsible party.
        effective_party_type = "subcontractor"
        for item in detail.get("registration_items") or []:
            grouped_event = db.get(DefectEvent, int(item.get("id") or 0))
            if grouped_event and grouped_event.tenant_id == tenant_id:
                grouped_event.responsible_party_type = effective_party_type
                _auto_close_factory_defect(grouped_event)
    can_recalculate_loss = bool(source.header_id and source.found_process_id)
    events = create_defect_events_batch(
        db,
        tenant_id=tenant_id,
        defect_type=source.defect_type,
        size_lines=size_lines,
        order_id=source.order_id,
        header_id=source.header_id,
        trace_unit_id=source.trace_unit_id,
        color_id=source.color_id,
        found_process_id=source.found_process_id,
        responsible_process_id=source.responsible_process_id,
        responsible_worker_id=source.responsible_worker_id,
        brand_name=source.brand_name,
        disposition=_enum_val(source.disposition),
        scrap_source=source.scrap_source if can_recalculate_loss else None,
        subcontract_order_id=source.subcontract_order_id,
        responsible_party_type=effective_party_type,
        replacement_source=source.replacement_source,
        found_by_worker_id=source.found_by_worker_id,
        found_by_user_id=source.found_by_user_id,
        note=source.note,
        auto_suggest_worker=False,
        batch_id=source.batch_id,
        photo_urls=source.photo_urls,
        company_share_percent=int(source.company_share_percent or 100),
        responsibilities=responsibilities,
    )
    for event in events:
        # Keep the new rows in the same logical registration returned by
        # get_defect_detail, including for legacy records without a group id.
        event.created_at = source.created_at
        event.status = source.status
        event.scrap_confirmed_at = source.scrap_confirmed_at
        if source.scrap_confirmed_at is not None:
            apply_defect_loss_allocation(
                db,
                tenant_id=tenant_id,
                event=event,
                loss_amount=event.loss_amount or 0,
                company_share_percent=int(source.company_share_percent or 100),
                responsibilities=responsibilities,
                responsible_party_type=effective_party_type,
            )
    db.commit()
    for event in events:
        db.refresh(event)
    return events


def unit_detail_dict(db: Session, unit: TraceUnit) -> dict:
    from app.models import PartDefinition

    order = db.get(Order, unit.order_id) if unit.order_id else None
    product = db.get(OwnProduct, unit.own_product_id)
    color = db.get(Color, unit.color_id) if unit.color_id else None
    size = db.get(Size, unit.size_id) if unit.size_id else None
    creator = db.get(Employee, unit.created_by_worker_id) if unit.created_by_worker_id else None
    process = db.get(ProcessDefinition, unit.current_process_id) if unit.current_process_id else None
    part = db.get(PartDefinition, unit.part_id) if getattr(unit, "part_id", None) else None
    parent = db.get(TraceUnit, unit.parent_id) if unit.parent_id else None
    receiver = (
        db.get(Employee, unit.received_by_worker_id) if getattr(unit, "received_by_worker_id", None) else None
    )
    reported_log = db.scalar(
        select(WorkLog)
        .where(
            WorkLog.tenant_id == unit.tenant_id,
            WorkLog.trace_unit_id == unit.id,
            WorkLog.status != WorkLogStatus.void,
        )
        .order_by(WorkLog.id.desc())
        .limit(1)
    )
    reported_worker = db.get(Employee, reported_log.worker_id) if reported_log else None
    reported_process = db.get(ProcessDefinition, reported_log.process_id) if reported_log else None

    logs = db.scalars(
        select(TraceUnitLog)
        .where(TraceUnitLog.trace_unit_id == unit.id)
        .order_by(TraceUnitLog.id.desc())
        .limit(50)
    ).all()
    log_items = []
    for lg in logs:
        w = db.get(Employee, lg.worker_id) if lg.worker_id else None
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
    execution_no = None
    header_no = None
    allocation_sources: list[dict] = []
    eid = getattr(unit, "execution_id", None)
    hid = getattr(unit, "header_id", None)
    if eid:
        from app.models import SpecExecutionOrder
        from app.services.execution_service import allocation_sources_for_execution

        exe = db.get(SpecExecutionOrder, eid)
        execution_no = exe.execution_no if exe else None
        allocation_sources = allocation_sources_for_execution(db, int(eid))
        if not hid and exe and exe.header_id:
            hid = exe.header_id
    if hid:
        from app.models import ExecutionHeader

        hdr = db.get(ExecutionHeader, int(hid))
        header_no = hdr.header_no if hdr else None

    # 合单分筐：本筐只显示自己的销售来源（按 sales_order_id 过滤）
    unit_so_id = getattr(unit, "sales_order_id", None)
    if unit_so_id:
        allocation_sources = [s for s in allocation_sources if int(s.get("sales_order_id") or 0) == int(unit_so_id)]

    work_requirements: dict[str, Any] = {}
    if unit_so_id:
        from app.services.execution_service import work_requirements_for_sales_order

        work_requirements = work_requirements_for_sales_order(db, int(unit_so_id))
    elif hid:
        from app.services.execution_service import work_requirements_for_header
        from app.models import ExecutionHeader as _EH

        _hdr = db.get(_EH, int(hid))
        if _hdr:
            wr_list = work_requirements_for_header(db, _hdr)
            work_requirements = wr_list[0] if wr_list else {}

    if order:
        for p in order.processes or []:
            processes.append(
                {
                    "id": p.id,
                    "order_process_id": p.id,
                    "process_id": p.process_id,
                    "process_name": p.process_name,
                    "process_type": _enum_val(p.process_type) if hasattr(p, "process_type") else None,
                    "part_id": getattr(p, "part_id", None),
                    "status": _enum_val(p.status),
                    "plan_qty": p.plan_qty,
                    "completed_qty": p.completed_qty,
                }
            )
    elif hid:
        from app.services.material_service import list_header_processes

        for p in list_header_processes(db, unit.tenant_id, int(hid)):
            processes.append(
                {
                    "id": p.id,
                    "order_process_id": p.id,
                    "process_id": p.process_id,
                    "process_name": p.process_name,
                    "process_type": _enum_val(p.process_type) if hasattr(p, "process_type") else None,
                    "part_id": getattr(p, "part_id", None),
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
        "parent_code": parent.code if parent else None,
        "part_id": getattr(unit, "part_id", None),
        "part_name": part.name if part else None,
        "part_code": part.code if part else None,
        "serial_no": unit.serial_no,
        "order_id": unit.order_id,
        "order_no": order.order_no if order else None,
        "header_id": hid,
        "header_no": header_no,
        "execution_id": eid,
        "execution_no": execution_no,
        "sales_order_id": unit_so_id,
        "batch_id": getattr(unit, "batch_id", None),
        "allocation_sources": allocation_sources,
        "work_requirements": work_requirements,
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
        "reported": reported_log is not None,
        "reported_work_log_id": reported_log.id if reported_log else None,
        "reported_at": reported_log.created_at.isoformat() if reported_log and reported_log.created_at else None,
        "reported_worker_name": reported_worker.name if reported_worker else None,
        "reported_process_name": reported_process.name if reported_process else None,
        "reported_qty": (
            int(reported_log.rework_qty or 0)
            if reported_log and _enum_val(reported_log.report_type) == "rework"
            else int(reported_log.qualified_qty or 0) if reported_log else 0
        ),
        "received_at": unit.received_at.isoformat() if getattr(unit, "received_at", None) else None,
        "received_by_worker_id": getattr(unit, "received_by_worker_id", None),
        "received_by_worker_name": receiver.name if receiver else None,
        "created_from_work_log_id": unit.created_from_work_log_id,
        "created_by_worker_id": unit.created_by_worker_id,
        "created_by_worker_name": creator.name if creator else None,
        "created_at": unit.created_at.isoformat() if unit.created_at else None,
        "scan_path": f"/trace/{unit.code}",
        "logs": log_items,
        "defects": [defect_out(db, d) for d in defects],
        "order_processes": processes,
        "children": [
            {
                "id": c.id,
                "code": c.code,
                "qty": c.qty,
                "part_id": c.part_id,
                "unit_type": _enum_val(c.unit_type),
                "status": _enum_val(c.status),
            }
            for c in db.scalars(
                select(TraceUnit)
                .where(TraceUnit.parent_id == unit.id, TraceUnit.status != TraceUnitStatus.scrapped)
                .order_by(TraceUnit.id)
            ).all()
        ]
        if _enum_val(unit.unit_type) == TraceUnitType.basket.value
        else [],
    }


def defect_out(db: Session, e: DefectEvent) -> dict:
    order = db.get(Order, e.order_id) if e.order_id else None
    header = db.get(ExecutionHeader, e.header_id) if getattr(e, "header_id", None) else None
    product_id = header.own_product_id if header else (order.own_product_id if order else None)
    product = db.get(OwnProduct, product_id) if product_id else None
    sales_order = (
        db.get(SalesOrder, header.sales_order_id)
        if header and getattr(header, "sales_order_id", None)
        else None
    )
    sales_line = (
        db.get(SalesOrderLine, header.sales_order_line_id)
        if header and getattr(header, "sales_order_line_id", None)
        else None
    )
    unit = db.get(TraceUnit, e.trace_unit_id) if e.trace_unit_id else None
    color = db.get(Color, e.color_id) if e.color_id else None
    size = db.get(Size, e.size_id) if e.size_id else None
    found_p = db.get(ProcessDefinition, e.found_process_id) if e.found_process_id else None
    resp_p = db.get(ProcessDefinition, e.responsible_process_id) if e.responsible_process_id else None
    resp_w = db.get(Employee, e.responsible_worker_id) if e.responsible_worker_id else None
    found_w = db.get(Employee, e.found_by_worker_id) if e.found_by_worker_id else None
    found_user = db.get(Employee, e.found_by_user_id) if e.found_by_user_id else None
    responsibilities = list(
        db.scalars(
            select(DefectResponsibility)
            .where(
                DefectResponsibility.tenant_id == e.tenant_id,
                DefectResponsibility.defect_event_id == e.id,
            )
            .order_by(DefectResponsibility.id)
        ).all()
    )
    pending_task = db.scalar(
        select(ReworkTask)
        .where(
            ReworkTask.defect_event_id == e.id,
            ReworkTask.status == ReworkTaskStatus.pending,
        )
        .order_by(ReworkTask.id.desc())
        .limit(1)
    )
    pending_worker = db.get(Employee, pending_task.worker_id) if pending_task else None
    recut_header = None
    if e.recut_header_id:
        recut_header = db.get(ExecutionHeader, e.recut_header_id)
    subcontract_order = (
        db.get(SubcontractOrder, e.subcontract_order_id)
        if getattr(e, "subcontract_order_id", None)
        else None
    )
    subcontract_partner = (
        db.get(Partner, subcontract_order.partner_id) if subcontract_order else None
    )
    employee_share_percent = max(0, 100 - int(getattr(e, "company_share_percent", 100) or 0))
    delivery_date = None
    if header and header.delivery_date:
        delivery_date = header.delivery_date.isoformat()
    elif sales_line and sales_line.delivery_date:
        delivery_date = sales_line.delivery_date.isoformat()
    elif order and getattr(order, "delivery_date", None):
        delivery_date = order.delivery_date.isoformat()
    return {
        "id": e.id,
        "trace_unit_id": e.trace_unit_id,
        "trace_code": unit.code if unit else None,
        "order_id": e.order_id,
        "header_id": getattr(e, "header_id", None),
        # 新不良事件的主关联是生产单；旧订单关联保留兼容展示。
        "order_no": header.header_no if header else (order.order_no if order else None),
        "sales_order_no": sales_order.order_no if sales_order else None,
        "customer_name": (
            sales_order.customer_name
            if sales_order
            else (order.customer_name if order else None)
        ),
        "customer_sku": sales_line.customer_sku if sales_line else None,
        "delivery_date": delivery_date,
        "product_code": product.product_code if product else None,
        "product_image_url": product.image_url if product else None,
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
        "brand_name": getattr(e, "brand_name", None) or (sales_line.brand_name if sales_line else None),
        "defect_type": e.defect_type,
        "defect_type_name": DEFECT_TYPE_NAMES.get(e.defect_type, e.defect_type),
        "qty": e.qty,
        "left_qty": int(getattr(e, "left_qty", 0) or 0),
        "right_qty": int(getattr(e, "right_qty", 0) or 0),
        "disposition": _enum_val(e.disposition),
        "scrap_source": getattr(e, "scrap_source", "internal") or "internal",
        "scrap_source_name": (
            "外加工报废" if getattr(e, "scrap_source", "internal") == "subcontract" else "本厂报废"
        ),
        "subcontract_order_id": getattr(e, "subcontract_order_id", None),
        "subcontract_no": subcontract_order.subcontract_no if subcontract_order else None,
        "subcontract_partner_id": subcontract_order.partner_id if subcontract_order else None,
        "subcontract_partner_name": (
            (subcontract_partner.short_name or subcontract_partner.name)
            if subcontract_partner
            else None
        ),
        "responsible_party_type": getattr(e, "responsible_party_type", "employee") or "employee",
        "responsible_party_type_name": (
            "外发厂"
            if (getattr(e, "responsible_party_type", "employee") or "employee") == "subcontractor"
            else "员工"
        ),
        "replacement_source": getattr(e, "replacement_source", "internal") or "internal",
        "replacement_source_name": (
            "外加工" if getattr(e, "replacement_source", "internal") == "subcontract" else "本厂生产"
        ),
        "found_by_worker_id": e.found_by_worker_id,
        "found_by_worker_name": found_w.name if found_w else None,
        "found_by_user_id": e.found_by_user_id,
        "found_by_user_name": found_user.name if found_user else None,
        "note": e.note,
        "photo_urls": list(getattr(e, "photo_urls", None) or []),
        "status": _enum_val(e.status),
        "recut_header_id": e.recut_header_id,
        "recut_header_no": recut_header.header_no if recut_header else None,
        "recut_qty": int(recut_header.total_qty or 0) if recut_header else 0,
        "scrap_confirmed_at": e.scrap_confirmed_at.isoformat() if e.scrap_confirmed_at else None,
        "loss_amount": float(e.loss_amount or 0),
        "material_loss_amount": float(getattr(e, "material_loss_amount", 0) or 0),
        "labor_loss_amount": float(getattr(e, "labor_loss_amount", 0) or 0),
        "company_share_percent": int(getattr(e, "company_share_percent", 100) or 0),
        "employee_share_percent": employee_share_percent,
        "company_loss_amount": round(
            float(e.loss_amount or 0) * int(getattr(e, "company_share_percent", 100) or 0) / 100,
            2,
        ),
        "employee_loss_amount": round(float(e.loss_amount or 0) * employee_share_percent / 100, 2),
        "factory_loss_amount": (
            round(float(e.loss_amount or 0) * employee_share_percent / 100, 2)
            if (getattr(e, "responsible_party_type", "employee") or "employee") == "subcontractor"
            else 0
        ),
        "wage_deduction_from_event": bool(getattr(e, "wage_deduction_from_event", False)),
        "responsibilities": (
            [
                {
                    "party_type": "subcontractor",
                    "worker_id": None,
                    "worker_name": None,
                    "partner_id": subcontract_order.partner_id if subcontract_order else None,
                    "partner_name": (
                        (subcontract_partner.short_name or subcontract_partner.name)
                        if subcontract_partner
                        else None
                    ),
                    "share_percent": employee_share_percent,
                    "deduction_amount": round(
                        float(e.loss_amount or 0) * employee_share_percent / 100,
                        2,
                    ),
                }
            ]
            if (getattr(e, "responsible_party_type", "employee") or "employee") == "subcontractor"
            and employee_share_percent > 0
            else [
                {
                    "party_type": "employee",
                    "worker_id": item.worker_id,
                    "worker_name": (
                        db.get(Employee, item.worker_id).name if db.get(Employee, item.worker_id) else None
                    ),
                    "partner_id": None,
                    "partner_name": None,
                    "share_percent": item.share_percent,
                    "deduction_amount": round(
                        float(e.loss_amount or 0) * int(item.share_percent or 0) / 100,
                        2,
                    ),
                }
                for item in responsibilities
            ]
        ),
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
    header_id: int | None = None,
    responsible_worker_id: int | None = None,
    responsible_process_id: int | None = None,
    reported_by_employee_id: int | None = None,
    defect_type: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    pending_rework: bool | None = None,
    trace_quality: str | None = None,
    page: int = 1,
    page_size: int = 20,
    viewer: Employee | None = None,
    viewer_is_tenant_wide: bool = False,
    scope_to_managed_departments: bool = False,
) -> dict:
    q = select(DefectEvent).where(DefectEvent.tenant_id == tenant_id)
    order_ids: list[int] | None = None
    managed_ids: set[int] = set()
    involved_defect_ids: set[int] | None = None
    if scope_to_managed_departments:
        managed_ids = managed_department_ids(db, viewer)
        involved_defect_ids = defect_ids_involving_departments(
            db, tenant_id=tenant_id, department_ids=managed_ids
        )
        if not involved_defect_ids:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "summary": {
                    "total_qty": 0,
                    "total_loss_amount": 0.0,
                    "company_loss_amount": 0.0,
                    "employee_loss_amount": 0.0,
                    "by_worker": [],
                    "by_type": [],
                },
            }
        q = q.where(DefectEvent.id.in_(involved_defect_ids))
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
                "summary": {
                    "total_qty": 0,
                    "total_loss_amount": 0.0,
                    "company_loss_amount": 0.0,
                    "employee_loss_amount": 0.0,
                    "by_worker": [],
                    "by_type": [],
                },
            }
        q = q.where(DefectEvent.order_id.in_(order_ids))
    if header_id:
        q = q.where(DefectEvent.header_id == int(header_id))
    if responsible_worker_id:
        q = q.where(DefectEvent.responsible_worker_id == responsible_worker_id)
    if responsible_process_id:
        q = q.where(DefectEvent.responsible_process_id == responsible_process_id)
    if reported_by_employee_id:
        q = q.where(
            or_(
                DefectEvent.found_by_worker_id == reported_by_employee_id,
                DefectEvent.found_by_user_id == reported_by_employee_id,
            )
        )
    if defect_type:
        q = q.where(DefectEvent.defect_type == defect_type)
    if status and status in DefectEventStatus.__members__:
        q = q.where(DefectEvent.status == DefectEventStatus(status))
    if date_from:
        q = q.where(
            DefectEvent.created_at >= datetime.combine(date_from, time.min) - timedelta(hours=8)
        )
    if date_to:
        q = q.where(
            DefectEvent.created_at < datetime.combine(date_to + timedelta(days=1), time.min) - timedelta(hours=8)
        )
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
    if involved_defect_ids is not None:
        summary_q = summary_q.where(DefectEvent.id.in_(involved_defect_ids))
    if order_ids is not None:
        summary_q = summary_q.where(DefectEvent.order_id.in_(order_ids))
    if header_id:
        summary_q = summary_q.where(DefectEvent.header_id == int(header_id))
    if responsible_worker_id:
        summary_q = summary_q.where(DefectEvent.responsible_worker_id == responsible_worker_id)
    if responsible_process_id:
        summary_q = summary_q.where(DefectEvent.responsible_process_id == responsible_process_id)
    if reported_by_employee_id:
        summary_q = summary_q.where(
            or_(
                DefectEvent.found_by_worker_id == reported_by_employee_id,
                DefectEvent.found_by_user_id == reported_by_employee_id,
            )
        )
    if defect_type:
        summary_q = summary_q.where(DefectEvent.defect_type == defect_type)
    if status and status in DefectEventStatus.__members__:
        summary_q = summary_q.where(DefectEvent.status == DefectEventStatus(status))
    if date_from:
        summary_q = summary_q.where(
            DefectEvent.created_at >= datetime.combine(date_from, time.min) - timedelta(hours=8)
        )
    if date_to:
        summary_q = summary_q.where(
            DefectEvent.created_at < datetime.combine(date_to + timedelta(days=1), time.min) - timedelta(hours=8)
        )
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
    total_qty = sum(int(e.qty or 0) for e in all_for_summary)
    total_loss_amount = sum(
        (Decimal(str(e.loss_amount or 0)) for e in all_for_summary),
        Decimal("0"),
    )
    company_loss_amount = sum(
        (
            Decimal(str(e.loss_amount or 0))
            * Decimal(int(e.company_share_percent if e.company_share_percent is not None else 100))
            / Decimal(100)
            for e in all_for_summary
        ),
        Decimal("0"),
    )
    by_worker: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for e in all_for_summary:
        wname = "未指定"
        if e.responsible_worker_id:
            w = db.get(Employee, e.responsible_worker_id)
            wname = w.name if w else str(e.responsible_worker_id)
        by_worker[wname] = by_worker.get(wname, 0) + int(e.qty or 0)
        tname = DEFECT_TYPE_NAMES.get(e.defect_type, e.defect_type)
        by_type[tname] = by_type.get(tname, 0) + int(e.qty or 0)

    material_doc_by_defect: dict[int, str] = {}
    material_docs = db.scalars(
        select(StockDoc).where(
            StockDoc.tenant_id == tenant_id,
            StockDoc.doc_type == StockDocType.issue,
            StockDoc.status != StockDocStatus.void,
        )
    ).all()
    for doc in material_docs:
        for defect_id in getattr(doc, "defect_event_ids", None) or []:
            material_doc_by_defect[int(defect_id)] = doc.doc_no
    items = [defect_out(db, e) for e in rows]
    for item, event in zip(items, rows):
        item["material_doc_no"] = material_doc_by_defect.get(int(item["id"]))
        item["needs_my_confirm"] = bool(
            viewer is not None
            and can_supervisor_confirm_defect(
                db,
                employee=viewer,
                event=event,
                viewer_is_tenant_wide=viewer_is_tenant_wide,
            )
        )

    return {
        "items": items,
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "summary": {
            "total_qty": total_qty,
            "total_loss_amount": float(total_loss_amount.quantize(Decimal("0.01"))),
            "company_loss_amount": float(company_loss_amount.quantize(Decimal("0.01"))),
            "employee_loss_amount": float(
                (total_loss_amount - company_loss_amount).quantize(Decimal("0.01"))
            ),
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
    defect_type: str | None = None,
    status: str | None = None,
    disposition: str | None = None,
    scrap_source: str | None = None,
    subcontract_order_id: int | None = None,
    responsible_party_type: str | None = None,
    replacement_source: str | None = None,
    responsible_worker_id: int | None = None,
    note: str | None = None,
    brand_name: str | None = None,
    left_qty: int | None = None,
    right_qty: int | None = None,
    qty: int | None = None,
    found_process_id: int | None = None,
    size_id: int | None = None,
    photo_urls: list[str] | None = None,
    loss_amount: Decimal | float | int | None = None,
    company_share_percent: int | None = None,
    responsibilities: list[dict] | None = None,
    updated_by_user_id: int | None = None,
) -> DefectEvent:
    e = db.get(DefectEvent, defect_id)
    if not e or e.tenant_id != tenant_id:
        raise TraceError("not_found", "报废记录不存在")
    if defect_type is not None:
        if defect_type not in DEFECT_TYPE_CODES:
            raise TraceError("invalid_defect_type", f"不支持的缺陷类型：{defect_type}")
        e.defect_type = defect_type
    if status is not None:
        if status not in DefectEventStatus.__members__:
            raise TraceError("invalid_status", f"无效状态：{status}")
        e.status = DefectEventStatus(status)
    if disposition is not None:
        if disposition not in DefectDisposition.__members__:
            raise TraceError("invalid_disposition", f"无效处置：{disposition}")
        e.disposition = DefectDisposition(disposition)
    if brand_name is not None:
        e.brand_name = brand_name.strip() or None
    if found_process_id is not None:
        if found_process_id == 0:
            e.found_process_id = None
        else:
            process = db.get(ProcessDefinition, found_process_id)
            if not process or process.tenant_id != tenant_id:
                raise TraceError("process_not_found", "发现工序不存在")
            e.found_process_id = found_process_id
    if size_id is not None:
        if size_id == 0:
            e.size_id = None
        else:
            size = db.get(Size, size_id)
            if not size or size.tenant_id != tenant_id:
                raise TraceError("size_not_found", "码数不存在")
            e.size_id = size_id
    if photo_urls is not None:
        e.photo_urls = _normalize_photo_urls(photo_urls)

    next_left = int(e.left_qty or 0) if left_qty is None else int(left_qty)
    next_right = int(e.right_qty or 0) if right_qty is None else int(right_qty)
    if left_qty is not None or right_qty is not None:
        if next_left < 0 or next_right < 0:
            raise TraceError("invalid_side_qty", "左脚、右脚数量不能小于 0")
        e.left_qty = next_left
        e.right_qty = next_right
        if qty is None:
            e.qty = next_left + next_right
    if qty is not None:
        if qty <= 0:
            raise TraceError("invalid_qty", "报废数量必须大于 0")
        if (left_qty is not None or right_qty is not None) and qty != next_left + next_right:
            raise TraceError("invalid_side_total", "报废数量必须等于左脚与右脚数量合计")
        e.qty = int(qty)
    elif left_qty is not None or right_qty is not None:
        if e.qty <= 0:
            raise TraceError("invalid_qty", "报废数量必须大于 0")

    if responsible_worker_id is not None:
        old_id = e.responsible_worker_id
        old_name = "空"
        if old_id:
            ow = db.get(Employee, old_id)
            old_name = ow.name if ow else str(old_id)
        if responsible_worker_id == 0:
            e.responsible_worker_id = None
            new_name = "空"
        else:
            w = db.get(Employee, responsible_worker_id)
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

    if scrap_source is not None or replacement_source is not None:
        next_scrap_source = scrap_source or getattr(e, "scrap_source", "internal") or "internal"
        next_replacement_source = replacement_source or getattr(e, "replacement_source", "internal") or "internal"
        _validate_defect_sources(next_scrap_source, next_replacement_source)
        e.scrap_source = next_scrap_source
        e.replacement_source = next_replacement_source

    if subcontract_order_id is not None or scrap_source is not None or responsible_party_type is not None:
        next_party = _normalize_responsible_party_type(
            responsible_party_type if responsible_party_type is not None else getattr(e, "responsible_party_type", None),
            subcontract_order_id=(
                subcontract_order_id
                if subcontract_order_id
                else getattr(e, "subcontract_order_id", None)
            ),
        )
        if responsible_party_type is not None or subcontract_order_id:
            e.responsible_party_type = next_party
        next_scrap_source = getattr(e, "scrap_source", "internal") or "internal"
        if subcontract_order_id or next_party == "subcontractor":
            next_scrap_source = "subcontract"
            e.scrap_source = next_scrap_source
        if next_party == "employee" and next_scrap_source == "internal":
            e.subcontract_order_id = None
        else:
            requested_id = (
                subcontract_order_id
                if subcontract_order_id is not None
                else getattr(e, "subcontract_order_id", None)
            )
            e.subcontract_order_id = _bind_subcontract_order_for_defect(
                db,
                tenant_id=tenant_id,
                header_id=getattr(e, "header_id", None),
                scrap_source=next_scrap_source,
                subcontract_order_id=requested_id,
                responsible_party_type=getattr(e, "responsible_party_type", "employee") or "employee",
            )
        if (getattr(e, "responsible_party_type", "employee") or "employee") == "subcontractor":
            first_process_id = _subcontract_first_process_id(
                db, db.get(SubcontractOrder, e.subcontract_order_id) if e.subcontract_order_id else None
            )
            if first_process_id:
                e.found_process_id = first_process_id

    if (
        scrap_source is not None
        or replacement_source is not None
        or responsible_party_type is not None
        or subcontract_order_id is not None
    ):
        if not e.header_id or not e.found_process_id:
            raise TraceError("loss_basis_required", "自动计算损失需要生产单和发现工序")
        material_loss, labor_loss, loss_amount = _calculate_defect_loss(
            db,
            tenant_id=tenant_id,
            header_id=int(e.header_id),
            found_process_id=int(e.found_process_id),
            size_id=e.size_id,
            qty=int(e.qty or 0),
            scrap_source=getattr(e, "scrap_source", "internal") or "internal",
            responsible_party_type=getattr(e, "responsible_party_type", "employee") or "employee",
            subcontract_order_id=getattr(e, "subcontract_order_id", None),
        )
        e.material_loss_amount = material_loss
        e.labor_loss_amount = labor_loss

    if loss_amount is not None or company_share_percent is not None or responsibilities is not None or responsible_party_type is not None:
        apply_defect_loss_allocation(
            db,
            tenant_id=tenant_id,
            event=e,
            loss_amount=loss_amount if loss_amount is not None else e.loss_amount or 0,
            company_share_percent=(
                company_share_percent
                if company_share_percent is not None
                else int(getattr(e, "company_share_percent", 100) or 100)
            ),
            responsibilities=responsibilities,
            responsible_party_type=getattr(e, "responsible_party_type", None),
        )
        employee_share = 100 - int(e.company_share_percent or 0)
        amount = Decimal(str(e.loss_amount or 0))
        has_responsibilities = db.scalar(
            select(func.count())
            .select_from(DefectResponsibility)
            .where(
                DefectResponsibility.tenant_id == tenant_id,
                DefectResponsibility.defect_event_id == e.id,
            )
        )
        e.wage_deduction_from_event = bool(
            (getattr(e, "responsible_party_type", "employee") or "employee") == "employee"
            and e.scrap_confirmed_at is not None
            and employee_share > 0
            and has_responsibilities
            and amount > 0
        )

    _auto_close_factory_defect(e)

    db.commit()
    db.refresh(e)
    return e


def delete_defect(db: Session, *, tenant_id: int, defect_id: int) -> None:
    event = db.get(DefectEvent, defect_id)
    if not event or event.tenant_id != tenant_id:
        raise TraceError("not_found", "报废记录不存在")

    if event.recut_header_id or db.scalar(
        select(ExecutionHeader.id).where(
            ExecutionHeader.tenant_id == tenant_id,
            ExecutionHeader.recut_defect_event_id == event.id,
        ).limit(1)
    ):
        raise TraceError("recut_exists", "该报废记录已生成补开裁生产单，不能删除")
    if db.scalar(
        select(ReworkTask.id).where(
            ReworkTask.tenant_id == tenant_id,
            ReworkTask.defect_event_id == event.id,
        ).limit(1)
    ):
        raise TraceError("rework_exists", "该报废记录已有返修任务，不能删除")

    stock_docs = db.scalars(
        select(StockDoc).where(
            StockDoc.tenant_id == tenant_id,
            StockDoc.defect_event_ids.is_not(None),
        )
    ).all()
    linked_stock_docs = [
        doc
        for doc in stock_docs
        if event.id in {int(value) for value in (doc.defect_event_ids or [])}
    ]
    posted_doc = next(
        (doc for doc in linked_stock_docs if doc.status == StockDocStatus.posted),
        None,
    )
    if posted_doc:
        raise TraceError(
            "material_doc_posted",
            f"补料单 {posted_doc.doc_no} 已过账，请先退料冲销后再删除报废记录",
        )
    # 待确认/已作废补料单尚未形成库存发料，可与报废来源一起物理删除。
    # StockDoc.lines 配置 delete-orphan，删除单头会同步删除全部明细。
    for doc in linked_stock_docs:
        db.delete(doc)
    db.flush()

    responsibilities = db.scalars(
        select(DefectResponsibility).where(
            DefectResponsibility.tenant_id == tenant_id,
            DefectResponsibility.defect_event_id == event.id,
        )
    ).all()
    for responsibility in responsibilities:
        db.delete(responsibility)
    db.flush()
    db.delete(event)
    db.commit()


def _normalize_defect_responsibilities(
    db: Session,
    *,
    tenant_id: int,
    company_share_percent: int,
    responsibilities: list[dict] | None,
    fallback_worker_id: int | None = None,
    responsible_party_type: str = "employee",
    subcontract_order_id: int | None = None,
) -> list[tuple[int, int]]:
    if not 0 <= int(company_share_percent) <= 100:
        raise TraceError("invalid_company_share", "公司所占百分比须在 0 至 100 之间")
    employee_share = 100 - int(company_share_percent)
    party = _normalize_responsible_party_type(
        responsible_party_type,
        subcontract_order_id=subcontract_order_id,
    )
    if party == "subcontractor":
        if employee_share > 0 and not subcontract_order_id:
            raise TraceError("subcontract_order_required", "请选择对应的外发单")
        return []
    responsibilities_provided = responsibilities is not None
    if responsibilities is None:
        responsibilities = (
            [{"worker_id": fallback_worker_id, "share_percent": employee_share}]
            if fallback_worker_id and employee_share > 0
            else []
        )
    normalized: list[tuple[int, int]] = []
    seen_workers: set[int] = set()
    for item in responsibilities:
        worker_id = int(item.get("worker_id") or 0)
        share_percent = int(item.get("share_percent") or 0)
        if worker_id <= 0 or not 0 <= share_percent <= 100 or worker_id in seen_workers:
            raise TraceError("invalid_responsibilities", "责任员工及分摊比例不正确")
        worker = db.get(Employee, worker_id)
        if not worker or worker.tenant_id != tenant_id:
            raise TraceError("worker_not_found", "责任员工不存在")
        seen_workers.add(worker_id)
        normalized.append((worker_id, share_percent))
    responsibility_total = sum(share for _, share in normalized)
    if normalized and responsibility_total != employee_share:
        raise TraceError("responsibility_total", "公司所占比例与员工分摊比例合计必须为 100%")
    if employee_share > 0 and responsibilities_provided and not normalized:
        raise TraceError("responsibility_required", "请选择责任员工")
    if employee_share == 0:
        return []
    return normalized


def apply_defect_loss_allocation(
    db: Session,
    *,
    tenant_id: int,
    event: DefectEvent,
    loss_amount: Decimal | float | int = 0,
    company_share_percent: int = 100,
    responsibilities: list[dict] | None = None,
    responsible_party_type: str | None = None,
) -> DefectEvent:
    amount = Decimal(str(loss_amount or 0)).quantize(Decimal("0.01"))
    if amount < 0:
        raise TraceError("invalid_loss", "损失金额不能为负")
    party = _normalize_responsible_party_type(
        responsible_party_type if responsible_party_type is not None else getattr(event, "responsible_party_type", None),
        subcontract_order_id=getattr(event, "subcontract_order_id", None),
    )
    event.responsible_party_type = party
    normalized = _normalize_defect_responsibilities(
        db,
        tenant_id=tenant_id,
        company_share_percent=int(company_share_percent),
        responsibilities=responsibilities,
        fallback_worker_id=event.responsible_worker_id,
        responsible_party_type=party,
        subcontract_order_id=getattr(event, "subcontract_order_id", None),
    )
    event.loss_amount = amount
    event.company_share_percent = int(company_share_percent)
    db.query(DefectResponsibility).filter(
        DefectResponsibility.tenant_id == tenant_id,
        DefectResponsibility.defect_event_id == event.id,
    ).delete(synchronize_session=False)
    for worker_id, share_percent in normalized:
        db.add(
            DefectResponsibility(
                tenant_id=tenant_id,
                defect_event_id=event.id,
                worker_id=worker_id,
                share_percent=share_percent,
            )
        )
    employee_share = 100 - int(company_share_percent)
    event.responsible_worker_id = normalized[0][0] if normalized else None
    event.wage_deduction_from_event = bool(
        party == "employee"
        and employee_share > 0
        and normalized
        and amount > 0
        and event.scrap_confirmed_at is not None
    )
    return event


def confirm_defect_scrap(
    db: Session,
    *,
    tenant_id: int,
    defect_id: int,
    loss_amount: Decimal | float | int = 0,
    company_share_percent: int = 100,
    responsibilities: list[dict] | None = None,
    confirmed_by: int | None = None,
) -> DefectEvent:
    """确认报废并写入损失责任。

    硬规则：未先创建关联补开裁子生产单，不允许报废；工资只读取员工承担部分。
    """
    event = db.get(DefectEvent, defect_id)
    if not event or event.tenant_id != tenant_id:
        raise TraceError("not_found", "不良记录不存在")
    disp = _enum_val(event.disposition)
    if disp != DefectDisposition.scrap.value:
        raise TraceError("not_scrap", "请先将处置方式设为报废")
    if not event.recut_header_id:
        raise TraceError("recut_required", "确认报废前必须先开补开裁生产单")
    apply_defect_loss_allocation(
        db,
        tenant_id=tenant_id,
        event=event,
        loss_amount=loss_amount,
        company_share_percent=company_share_percent,
        responsibilities=responsibilities,
    )
    event.scrap_confirmed_at = datetime.now(timezone.utc)
    event.status = DefectEventStatus.closed
    employee_share = 100 - int(event.company_share_percent or 0)
    amount = Decimal(str(event.loss_amount or 0))
    has_responsibilities = db.scalar(
        select(func.count())
        .select_from(DefectResponsibility)
        .where(
            DefectResponsibility.tenant_id == tenant_id,
            DefectResponsibility.defect_event_id == event.id,
        )
    )
    event.wage_deduction_from_event = bool(
        (getattr(event, "responsible_party_type", "employee") or "employee") == "employee"
        and employee_share > 0
        and has_responsibilities
        and amount > 0
    )

    unit = db.get(TraceUnit, event.trace_unit_id) if event.trace_unit_id else None
    if unit and unit.tenant_id == tenant_id:
        uqty = int(unit.qty or 0)
        scrap_qty = min(int(event.qty or 0), uqty)
        if scrap_qty >= uqty:
            unit.status = TraceUnitStatus.scrapped
            unit.qty = 0
        else:
            unit.qty = uqty - scrap_qty
        db.add(
            TraceUnitLog(
                tenant_id=tenant_id,
                trace_unit_id=unit.id,
                action=TraceUnitAction.inspect,
                worker_id=confirmed_by,
                process_id=event.found_process_id,
                qty=scrap_qty,
                note=f"确认报废×{scrap_qty}；补开裁#{event.recut_header_id}",
            )
        )
    db.commit()
    db.refresh(event)
    return event


def managed_department_ids(db: Session, employee: Employee | None) -> set[int]:
    """主管可确认的部门：兼任负责人/主管的部门 ∪ 所带班组部门。"""
    if employee is None:
        return set()
    ids: set[int] = set(
        int(dep_id)
        for dep_id in db.scalars(
            select(Department.id).where(
                Department.tenant_id == employee.tenant_id,
                Department.is_active.is_(True),
                or_(
                    Department.leader_id == employee.id,
                    Department.manager_employee_id == employee.id,
                ),
            )
        ).all()
    )
    led_teams = list(
        db.scalars(
            select(Team).where(
                Team.tenant_id == employee.tenant_id,
                Team.leader_worker_id == employee.id,
                Team.is_active.is_(True),
            )
        ).all()
    )
    for team in led_teams:
        if team.department_id:
            ids.add(int(team.department_id))
    # 所带班组未挂部门时，回退本人归属部门，避免组长无法确认本部门承担人。
    if not ids and led_teams and employee.department_id:
        ids.add(int(employee.department_id))
    return ids


def defect_responsibility_department_ids(db: Session, event: DefectEvent) -> set[int]:
    """损失承担员工所属部门。无分摊行时回退到主责任人。"""
    worker_ids = list(
        db.scalars(
            select(DefectResponsibility.worker_id).where(
                DefectResponsibility.tenant_id == event.tenant_id,
                DefectResponsibility.defect_event_id == event.id,
            )
        ).all()
    )
    if not worker_ids and event.responsible_worker_id:
        worker_ids = [int(event.responsible_worker_id)]
    if not worker_ids:
        return set()
    return {
        int(dep_id)
        for dep_id in db.scalars(
            select(Employee.department_id).where(
                Employee.id.in_([int(wid) for wid in worker_ids]),
                Employee.department_id.is_not(None),
            )
        ).all()
        if dep_id
    }


def defect_ids_involving_departments(
    db: Session,
    *,
    tenant_id: int,
    department_ids: set[int],
) -> set[int]:
    """损失承担人（含无分摊行时的主责任人）落在指定部门内的不良记录。"""
    if not department_ids:
        return set()
    dept_list = list(department_ids)
    from_responsibilities = {
        int(defect_id)
        for defect_id in db.scalars(
            select(DefectResponsibility.defect_event_id)
            .join(Employee, Employee.id == DefectResponsibility.worker_id)
            .where(
                DefectResponsibility.tenant_id == tenant_id,
                Employee.department_id.in_(dept_list),
            )
        ).all()
    }
    has_responsibility_rows = select(DefectResponsibility.defect_event_id).where(
        DefectResponsibility.tenant_id == tenant_id
    )
    from_legacy = {
        int(defect_id)
        for defect_id in db.scalars(
            select(DefectEvent.id)
            .join(Employee, Employee.id == DefectEvent.responsible_worker_id)
            .where(
                DefectEvent.tenant_id == tenant_id,
                Employee.department_id.in_(dept_list),
                ~DefectEvent.id.in_(has_responsibility_rows),
            )
        ).all()
    }
    return from_responsibilities | from_legacy


def _auto_close_factory_defect(event: DefectEvent) -> None:
    if (getattr(event, "responsible_party_type", "employee") or "employee") != "subcontractor":
        return
    event.wage_deduction_from_event = False
    if event.scrap_confirmed_at is not None:
        return
    event.disposition = DefectDisposition.scrap
    event.scrap_confirmed_at = datetime.now(timezone.utc)
    event.status = DefectEventStatus.closed


def can_supervisor_confirm_defect(
    db: Session,
    *,
    employee: Employee | None,
    event: DefectEvent,
    viewer_is_tenant_wide: bool = False,
) -> bool:
    """仅当损失承担人属于主管自己部门时需要/允许其确认；厂级角色可确认全部待确认报废。"""
    if employee is None or event.tenant_id != employee.tenant_id:
        return False
    if (getattr(event, "responsible_party_type", "employee") or "employee") == "subcontractor":
        return False
    if event.scrap_confirmed_at is not None:
        return False
    if _enum_val(event.status) == DefectEventStatus.closed.value:
        return False
    resp_dept_ids = defect_responsibility_department_ids(db, event)
    if not resp_dept_ids:
        # 纯公司承担：部门主管无需确认；厂级管理员可收口关闭。
        return viewer_is_tenant_wide
    if viewer_is_tenant_wide:
        return True
    return bool(managed_department_ids(db, employee) & resp_dept_ids)


def confirm_defect_by_supervisor(
    db: Session,
    *,
    tenant_id: int,
    defect_id: int,
    confirmed_by: int | None = None,
    confirmer: Employee | None = None,
    viewer_is_tenant_wide: bool = False,
) -> DefectEvent:
    """主管确认移动端提交的报废，沿用登记时已保存的损失与分摊。"""
    event = db.get(DefectEvent, defect_id)
    if not event or event.tenant_id != tenant_id:
        raise TraceError("not_found", "报废记录不存在")
    if confirmer is not None and not can_supervisor_confirm_defect(
        db,
        employee=confirmer,
        event=event,
        viewer_is_tenant_wide=viewer_is_tenant_wide,
    ):
        raise TraceError("forbidden", "仅本部门损失承担相关的主管可确认")
    if event.scrap_confirmed_at is not None:
        return event

    event.disposition = DefectDisposition.scrap
    event.scrap_confirmed_at = datetime.now(timezone.utc)
    event.status = DefectEventStatus.closed
    amount = Decimal(str(event.loss_amount or 0))
    has_responsibilities = db.scalar(
        select(func.count())
        .select_from(DefectResponsibility)
        .where(
            DefectResponsibility.tenant_id == tenant_id,
            DefectResponsibility.defect_event_id == event.id,
        )
    )
    employee_share = 100 - int(event.company_share_percent or 0)
    event.wage_deduction_from_event = bool(
        (getattr(event, "responsible_party_type", "employee") or "employee") == "employee"
        and employee_share > 0
        and has_responsibilities
        and amount > 0
    )

    unit = db.get(TraceUnit, event.trace_unit_id) if event.trace_unit_id else None
    if unit and unit.tenant_id == tenant_id:
        unit_qty = int(unit.qty or 0)
        scrap_qty = min(int(event.qty or 0), unit_qty)
        if scrap_qty >= unit_qty:
            unit.status = TraceUnitStatus.scrapped
            unit.qty = 0
        else:
            unit.qty = unit_qty - scrap_qty
        db.add(
            TraceUnitLog(
                tenant_id=tenant_id,
                trace_unit_id=unit.id,
                action=TraceUnitAction.inspect,
                worker_id=confirmed_by,
                process_id=event.found_process_id,
                qty=scrap_qty,
                note=f"主管确认报废×{scrap_qty}",
            )
        )
    db.commit()
    db.refresh(event)
    return event

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
    """B2g 门面：解析单号/框码/不良 ID，编排现网详情，不复制流水查询。"""
    raw = (q or "").strip()
    if not raw:
        raise TraceError("query_required", "请输入生产单号、框码或不良 ID")

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
        raise TraceError("not_found", "未找到匹配的生产单、框码或不良事件")

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
