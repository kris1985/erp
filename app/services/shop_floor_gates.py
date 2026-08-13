"""AU-I0 车间闸门：载体×阶段、收料认领、齐套检查。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models import (
    OwnProductLabor,
    OwnProductPart,
    OrderProcess,
    TraceUnit,
    TraceUnitAction,
    TraceUnitLog,
    TraceUnitStatus,
    TraceUnitType,
    WorkLog,
    WorkLogStatus,
    Worker,
    WorkerRole,
)
from app.services import shop_floor_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ShopFloorGateError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _unit_type_value(tu: TraceUnit) -> str:
    ut = tu.unit_type
    return ut.value if hasattr(ut, "value") else str(ut)


def find_kit_order_process(db: "Session", *, tenant_id: int, order_id: int, product_id: int) -> OrderProcess | None:
    labor = db.scalar(
        select(OwnProductLabor).where(
            OwnProductLabor.tenant_id == tenant_id,
            OwnProductLabor.own_product_id == product_id,
            OwnProductLabor.is_kit_checkpoint.is_(True),
            OwnProductLabor.process_id.is_not(None),
        )
    )
    if not labor or not labor.process_id:
        return None
    return db.scalar(
        select(OrderProcess).where(
            OrderProcess.tenant_id == tenant_id,
            OrderProcess.order_id == order_id,
            OrderProcess.process_id == labor.process_id,
            OrderProcess.part_id.is_(None),
        )
    )


def process_index(processes: list[OrderProcess], process: OrderProcess) -> int:
    for i, p in enumerate(processes):
        if p.id == process.id:
            return i
    return -1


def is_personal_piecework_before_kit(
    processes: list[OrderProcess],
    process: OrderProcess,
    kit: OrderProcess | None,
) -> bool:
    """合帮前个人段：有 kit 时 index < kit；无 kit 时凡带 part_id 的工序。"""
    ptype = process.process_type
    ptype_v = ptype.value if hasattr(ptype, "value") else str(ptype)
    if ptype_v == "group":
        return False
    idx = process_index(processes, process)
    if kit is None:
        return process.part_id is not None
    kit_idx = process_index(processes, kit)
    if kit_idx < 0 or idx < 0:
        return process.part_id is not None
    return idx < kit_idx


def is_at_or_after_kit(
    processes: list[OrderProcess],
    process: OrderProcess,
    kit: OrderProcess | None,
) -> bool:
    if kit is None:
        return process.part_id is None
    idx = process_index(processes, process)
    kit_idx = process_index(processes, kit)
    if idx < 0 or kit_idx < 0:
        return process.part_id is None
    return idx >= kit_idx


def assert_parts_ready(
    db: "Session",
    *,
    tenant_id: int,
    basket: TraceUnit,
    product_id: int,
    kit_ready_qty_ratio: float = 1.0,
) -> None:
    parts = list(
        db.scalars(
            select(OwnProductPart).where(
                OwnProductPart.tenant_id == tenant_id,
                OwnProductPart.own_product_id == product_id,
            )
        ).all()
    )
    if not parts:
        return
    children = list(
        db.scalars(
            select(TraceUnit).where(
                TraceUnit.tenant_id == tenant_id,
                TraceUnit.parent_id == basket.id,
                TraceUnit.unit_type == TraceUnitType.bundle,
                TraceUnit.status != TraceUnitStatus.scrapped,
            )
        ).all()
    )
    need = max(0.0, float(kit_ready_qty_ratio or 1.0))
    plan = int(basket.qty or 0)
    threshold = int(plan * need) if plan > 0 else 0
    for part in parts:
        part_bundles = [c for c in children if c.part_id == part.part_id]
        if not part_bundles:
            raise ShopFloorGateError(
                "kit_parts_not_ready",
                f"齐套未就绪：缺少部件捆（part_id={part.part_id}）",
            )
        ready = False
        for b in part_bundles:
            st = b.status.value if hasattr(b.status, "value") else str(b.status)
            if st in (TraceUnitStatus.in_process.value, TraceUnitStatus.done.value):
                ready = True
                break
            reported = (
                db.scalar(
                    select(func.coalesce(func.sum(WorkLog.qualified_qty), 0)).where(
                        WorkLog.tenant_id == tenant_id,
                        WorkLog.trace_unit_id == b.id,
                        WorkLog.status == WorkLogStatus.valid,
                    )
                )
                or 0
            )
            if int(reported) >= max(1, threshold or 1):
                ready = True
                break
        if not ready:
            raise ShopFloorGateError(
                "kit_parts_not_ready",
                f"齐套未就绪：部件 {part.part_id} 尚未完成合帮前工序",
            )


def mark_basket_received(
    db: "Session",
    *,
    tenant_id: int,
    basket: TraceUnit,
    worker_id: int | None,
    note: str | None = None,
    force: bool = False,
) -> bool:
    """幂等收料。返回是否本次新写入。"""
    if _unit_type_value(basket) != TraceUnitType.basket.value:
        raise ShopFloorGateError("not_basket", "仅流转卡(筐)可收料")
    if basket.received_at is not None and not force:
        return False
    basket.received_at = datetime.utcnow()
    basket.received_by_worker_id = worker_id
    db.add(
        TraceUnitLog(
            tenant_id=tenant_id,
            trace_unit_id=basket.id,
            action=TraceUnitAction.receive,
            worker_id=worker_id,
            qty=basket.qty,
            note=note or "收料认领",
        )
    )
    return True


def maybe_auto_receive(
    db: "Session",
    *,
    tenant_id: int,
    basket: TraceUnit,
    worker_id: int | None,
    note: str | None = None,
) -> bool:
    sf = shop_floor_settings.get_shop_floor_by_tenant_id(db, tenant_id)
    if not sf.get("auto_basket_receive_on_first_action", True):
        return False
    return mark_basket_received(
        db, tenant_id=tenant_id, basket=basket, worker_id=worker_id, note=note or "自动收料"
    )


def assert_basket_received_if_required(db: "Session", *, tenant_id: int, basket: TraceUnit) -> None:
    sf = shop_floor_settings.get_shop_floor_by_tenant_id(db, tenant_id)
    if not sf.get("require_basket_receive_before_stitch", False):
        return
    if basket.received_at is None:
        raise ShopFloorGateError("basket_not_received", "流转卡尚未收料，请先收料再分活/报工")


def operator_is_leader(worker: Worker) -> bool:
    role = worker.role
    role_v = role.value if hasattr(role, "value") else str(role)
    return role_v in (WorkerRole.leader.value, "leader", "admin", "manager")


def assert_report_carrier(
    db: "Session",
    *,
    tenant_id: int,
    order_processes: list[OrderProcess],
    process: OrderProcess,
    product_id: int,
    trace_unit: TraceUnit | None,
    pay_worker_id: int,
    operator: Worker,
    is_leader_proxy: bool,
    beneficiary_worker_id: int | None,
) -> None:
    """载体×阶段闸门。无 trace_unit 时不拦（兼容旧报工）。"""
    if trace_unit is None:
        return

    sf = shop_floor_settings.get_shop_floor_by_tenant_id(db, tenant_id)
    kit = find_kit_order_process(
        db, tenant_id=tenant_id, order_id=process.order_id, product_id=product_id
    )
    ut = _unit_type_value(trace_unit)

    if ut == TraceUnitType.bundle.value:
        if is_at_or_after_kit(order_processes, process, kit):
            raise ShopFloorGateError("need_basket", "合帮后请扫流转卡(筐)")
        if is_leader_proxy:
            if not sf.get("stitch_leader_proxy_report", True):
                raise ShopFloorGateError("proxy_disabled", "未开启组长代报")
            if not operator_is_leader(operator):
                raise ShopFloorGateError("proxy_not_leader", "仅组长可代报")
            if not beneficiary_worker_id:
                raise ShopFloorGateError("proxy_need_beneficiary", "代报须指定工人")
        elif not sf.get("allow_unassigned_bundle_report", False):
            # 未按捆派工时仍允许走原有工序派工逻辑；仅在已有捆派时由 report_service 校验
            # 这里额外：若筐强制收料，要求父筐已收
            if trace_unit.parent_id:
                parent = db.get(TraceUnit, trace_unit.parent_id)
                if parent and _unit_type_value(parent) == TraceUnitType.basket.value:
                    assert_basket_received_if_required(db, tenant_id=tenant_id, basket=parent)
        if is_leader_proxy and trace_unit.parent_id:
            parent = db.get(TraceUnit, trace_unit.parent_id)
            if parent and _unit_type_value(parent) == TraceUnitType.basket.value:
                maybe_auto_receive(
                    db,
                    tenant_id=tenant_id,
                    basket=parent,
                    worker_id=operator.id,
                    note="代报触发自动收料",
                )
                assert_basket_received_if_required(db, tenant_id=tenant_id, basket=parent)
        return

    if ut == TraceUnitType.basket.value:
        if is_personal_piecework_before_kit(order_processes, process, kit):
            raise ShopFloorGateError("need_bundle", "针车个人/代报请扫扎捆码")
        if kit and process.id == kit.id:
            assert_parts_ready(
                db,
                tenant_id=tenant_id,
                basket=trace_unit,
                product_id=product_id,
                kit_ready_qty_ratio=float(sf.get("kit_ready_qty_ratio") or 1.0),
            )
        return

    raise ShopFloorGateError("invalid_trace_type", f"不支持的追溯单元类型：{ut}")
