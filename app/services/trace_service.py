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
    SalesOrder,
    Size,
    TraceUnit,
    TraceUnitAction,
    TraceUnitLog,
    TraceUnitStatus,
    TraceUnitType,
    WorkLog,
    WorkLogStatus,
    Employee,
)

ACTIVE_BUNDLE_STATUSES = (TraceUnitStatus.open, TraceUnitStatus.in_process)


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
    commit: bool = True,
) -> dict:
    """开裁打卡生码。

    mode:
      - bundles：一码一捆
      - basket_bundles：有部件清单时 1 筐 N 捆；无部件且开追溯回退 bundles；关追溯回退仅筐
      - basket：仅流转卡、不打扎捆。开追溯禁止。

    execution_id：AU-I1 规格执行单；未传时若桥接生产单有未取消执行单则自动挂上。
    header_id：K4-B 认执行单头色码明细（无桥接壳）。
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
                qty=int(exe_row.total_qty or 0),
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

    if not dry_run and planned_creates:
        touched_execution_ids: set[int] = set()
        for item, q, so_id in planned_creates:
            eid = _eid_for_size(item.size_id)
            if eid is not None:
                touched_execution_ids.add(int(eid))
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

    print_path = (
        f"/admin/executions/{header.id}/print?mode=main-codes"
        if header is not None
        else f"/admin/orders/print/{order.id}?mode=main-codes"
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

    header_id = _resolve_defect_header_id(db, unit=unit, order_id=order_id)

    if not order_id and not header_id:
        raise TraceError("order_required", "请选择生产单/订单或扫捆标")

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
                "本单有进行中捆，请选择捆标后再登记",
            )
        if order is None and header_id is not None and header_has_active_bundles(
            db, tenant_id=tenant_id, header_id=header_id
        ):
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
        w = db.get(Employee, responsible_worker_id)
        if not w or w.tenant_id != tenant_id:
            raise TraceError("worker_not_found", "责任人不存在")

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
            uqty = int(unit.qty or 0)
            if qty >= uqty:
                unit.status = TraceUnitStatus.scrapped
                unit.qty = 0
            else:
                # 部分报废：扣减可用数，不整卡作废（与入库勾平）
                unit.qty = uqty - qty

    db.commit()
    db.refresh(event)
    return event


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
        so = db.get(SalesOrder, int(unit_so_id))
        work_requirements["sales_order_no"] = so.order_no if so else None

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
    unit = db.get(TraceUnit, e.trace_unit_id) if e.trace_unit_id else None
    color = db.get(Color, e.color_id) if e.color_id else None
    size = db.get(Size, e.size_id) if e.size_id else None
    found_p = db.get(ProcessDefinition, e.found_process_id) if e.found_process_id else None
    resp_p = db.get(ProcessDefinition, e.responsible_process_id) if e.responsible_process_id else None
    resp_w = db.get(Employee, e.responsible_worker_id) if e.responsible_worker_id else None
    found_w = db.get(Employee, e.found_by_worker_id) if e.found_by_worker_id else None
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
    return {
        "id": e.id,
        "trace_unit_id": e.trace_unit_id,
        "trace_code": unit.code if unit else None,
        "order_id": e.order_id,
        "header_id": getattr(e, "header_id", None),
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
            w = db.get(Employee, e.responsible_worker_id)
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