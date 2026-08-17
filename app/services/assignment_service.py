"""派工配额：已报量、剩余可报、报工匹配；整工序派工写入。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    OrderProcess,
    OrderProcessAssignment,
    ReportType,
    WorkLog,
    WorkLogStatus,
    Employee,
)


class AssignmentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def split_equal_qty(total: int, n: int) -> list[int]:
    """整数均分；余数分给前若干人。"""
    if n <= 0:
        return []
    total = max(0, int(total))
    base, rem = divmod(total, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def is_bundle_scope(a: OrderProcessAssignment) -> bool:
    return a.trace_unit_id is not None


def is_sku_scope(a: OrderProcessAssignment) -> bool:
    return a.trace_unit_id is None and (a.color_id is not None or a.size_id is not None)


def is_process_scope(a: OrderProcessAssignment) -> bool:
    return a.trace_unit_id is None and a.color_id is None and a.size_id is None


def effective_share_weight(a: OrderProcessAssignment | None) -> int:
    if a is None or a.share_weight is None or int(a.share_weight) <= 0:
        return 1
    return int(a.share_weight)


def worker_reported_qty(
    db: Session,
    order_process_id: int,
    worker_id: int,
    *,
    color_id: int | None = None,
    size_id: int | None = None,
    trace_unit_id: int | None = None,
    scope: str = "process",
) -> int:
    """有效正常/集体报工合格累计（不含返修）。

    scope=process：该人该工序全部已报。
    scope=sku：仅匹配 color_id / size_id 的已报。
    scope=bundle：仅匹配 trace_unit_id 的已报。
    """
    q = select(func.coalesce(func.sum(WorkLog.qualified_qty), 0)).where(
        WorkLog.order_process_id == order_process_id,
        WorkLog.worker_id == worker_id,
        WorkLog.status == WorkLogStatus.valid,
        WorkLog.report_type.in_(
            (ReportType.normal, ReportType.group, ReportType.supplement, ReportType.tail)
        ),
    )
    if scope == "sku":
        if color_id is None:
            q = q.where(WorkLog.color_id.is_(None))
        else:
            q = q.where(WorkLog.color_id == color_id)
        if size_id is None:
            q = q.where(WorkLog.size_id.is_(None))
        else:
            q = q.where(WorkLog.size_id == size_id)
    elif scope == "bundle":
        q = q.where(WorkLog.trace_unit_id == trace_unit_id)
    return int(db.scalar(q) or 0)


def reported_for_assignment(db: Session, a: OrderProcessAssignment) -> int:
    if is_bundle_scope(a):
        return worker_reported_qty(
            db,
            a.order_process_id,
            a.worker_id,
            trace_unit_id=a.trace_unit_id,
            scope="bundle",
        )
    if is_process_scope(a):
        return worker_reported_qty(db, a.order_process_id, a.worker_id, scope="process")
    return worker_reported_qty(
        db,
        a.order_process_id,
        a.worker_id,
        color_id=a.color_id,
        size_id=a.size_id,
        scope="sku",
    )


def list_assignments(db: Session, order_process_id: int) -> list[OrderProcessAssignment]:
    return list(
        db.scalars(
            select(OrderProcessAssignment).where(
                OrderProcessAssignment.order_process_id == order_process_id
            )
        ).all()
    )


def worker_can_report_remaining(
    db: Session,
    order_process_id: int,
    worker_id: int,
) -> tuple[bool, int | None]:
    """扫码候选：该人在该工序是否还有可报配额。

    返回 (can_report, remaining_quota)。
    remaining_quota=None 表示不限（或存在不限行）。
    """
    rows = [
        a
        for a in list_assignments(db, order_process_id)
        if a.worker_id == worker_id
    ]
    if not rows:
        return False, 0

    if any(a.quota_qty is None for a in rows):
        return True, None

    remaining = 0
    for a in rows:
        used = reported_for_assignment(db, a)
        remaining += max(0, int(a.quota_qty) - used)
    return remaining > 0, remaining


def match_assignment_for_quota(
    rows: list[OrderProcessAssignment],
    worker_id: int,
    color_id: int | None,
    size_id: int | None,
    trace_unit_id: int | None = None,
) -> OrderProcessAssignment | None:
    """报工扣配额：优先精确捆/色码行，否则回落整工序行。

    若工序存在捆派工行且报工未带捆/未命中，不回落整工序。
    """
    worker_rows = [a for a in rows if a.worker_id == worker_id]
    if not worker_rows:
        return None

    bundle_mode = any(is_bundle_scope(a) for a in rows)
    if bundle_mode:
        if trace_unit_id is None:
            return None
        for a in worker_rows:
            if is_bundle_scope(a) and a.trace_unit_id == trace_unit_id:
                return a
        return None

    for a in worker_rows:
        if is_sku_scope(a) and a.color_id == color_id and a.size_id == size_id:
            return a
    for a in worker_rows:
        if is_process_scope(a):
            return a
    return None


def replace_process_assignments(
    db: Session,
    *,
    tenant_id: int,
    order_id: int | None,
    process: OrderProcess,
    items: list[tuple[int, int | None, int | None]],
    commit: bool = False,
) -> list[OrderProcessAssignment]:
    """整工序派工全量替换（色码/捆请走订单派工 API）。

    items: [(worker_id, quota_qty, share_weight), ...]
    quota_qty=None 表示不限；commit=False 时由调用方提交。
    order_id 可空（K4-D 无壳执行单仅挂 header_id）。
    """
    seen: set[int] = set()
    cleaned: list[tuple[int, int | None, int | None]] = []
    for wid, quota, weight in items:
        if wid in seen:
            continue
        seen.add(wid)
        if quota is not None and int(quota) < 0:
            raise AssignmentError("invalid_quota", "配额不能为负")
        if weight is not None and int(weight) < 0:
            raise AssignmentError("invalid_weight", "分账权重不能为负")
        worker = db.get(Employee, wid)
        if not worker or worker.tenant_id != tenant_id or not worker.is_active:
            raise AssignmentError("worker_not_found", f"工人不存在或未启用：{wid}")
        reported = worker_reported_qty(db, process.id, wid, scope="process")
        if quota is not None and int(quota) < reported:
            raise AssignmentError(
                "quota_below_reported",
                f"{worker.name}已报{reported}，配额不能低于已报",
            )
        cleaned.append((wid, quota, weight))

    allocated = [q for _, q, _ in cleaned if q is not None]
    has_unlimited = any(q is None for _, q, _ in cleaned)
    if cleaned and not has_unlimited:
        total_quota = sum(int(q) for q in allocated)
        if total_quota > int(process.plan_qty):
            raise AssignmentError(
                "over_plan_quota",
                f"{process.process_name}已派配额{total_quota}超过计划{process.plan_qty}",
            )

    existing = list_assignments(db, process.id)
    if any(is_bundle_scope(a) or is_sku_scope(a) for a in existing):
        raise AssignmentError(
            "scope_conflict",
            f"{process.process_name}已按色码/捆派工，请在订单里改派，排产草稿仅支持整工序",
        )
    for row in existing:
        db.delete(row)
    db.flush()

    out: list[OrderProcessAssignment] = []
    for wid, quota, weight in cleaned:
        row = OrderProcessAssignment(
            tenant_id=tenant_id,
            order_id=order_id,
            header_id=getattr(process, "header_id", None),
            order_process_id=process.id,
            worker_id=wid,
            color_id=None,
            size_id=None,
            trace_unit_id=None,
            quota_qty=quota,
            share_weight=weight,
        )
        db.add(row)
        out.append(row)
    process.assigned_worker_id = cleaned[0][0] if cleaned else None
    if commit:
        db.commit()
    else:
        db.flush()
    return out


def assign_bundles_for_basket(
    db: Session,
    tenant_id: int,
    *,
    basket_id: int,
    process_id: int,
    items: list[dict],
    worker_id_for_receive: int | None = None,
) -> dict:
    """针车：按筐下扎捆分活。K4-F 认 header_id（无壳）。"""
    from app.models import OrderProcess, TraceUnit, TraceUnitType, Employee
    from app.services.shop_floor_gates import (
        ShopFloorGateError,
        assert_basket_received_if_required,
        maybe_auto_receive,
    )

    process = db.get(OrderProcess, process_id)
    if not process or process.tenant_id != tenant_id:
        raise AssignmentError("process_not_found", "工序不存在")

    basket = db.get(TraceUnit, basket_id)
    if not basket or basket.tenant_id != tenant_id:
        raise AssignmentError("basket_not_found", "流转卡不存在")
    bt = basket.unit_type.value if hasattr(basket.unit_type, "value") else str(basket.unit_type)
    if bt != TraceUnitType.basket.value:
        raise AssignmentError("not_basket", "basket_id 须为流转卡(筐)")

    proc_header = getattr(process, "header_id", None)
    basket_header = getattr(basket, "header_id", None)
    if process.order_id:
        if basket.order_id and basket.order_id != process.order_id:
            raise AssignmentError("basket_mismatch", "流转卡不属于该工序")
    elif proc_header:
        if basket_header and int(basket_header) != int(proc_header):
            raise AssignmentError("basket_mismatch", "流转卡不属于该生产单")
    else:
        raise AssignmentError("process_unlinked", "工序未关联生产单")

    try:
        maybe_auto_receive(
            db,
            tenant_id=tenant_id,
            basket=basket,
            worker_id=worker_id_for_receive,
            note="分活自动收料",
        )
        assert_basket_received_if_required(db, tenant_id=tenant_id, basket=basket)
    except ShopFloorGateError as e:
        raise AssignmentError(e.code, e.message) from e

    children = {
        c.id: c
        for c in db.scalars(
            select(TraceUnit).where(
                TraceUnit.parent_id == basket.id,
                TraceUnit.tenant_id == tenant_id,
            )
        ).all()
    }
    old = list(
        db.scalars(
            select(OrderProcessAssignment).where(
                OrderProcessAssignment.order_process_id == process.id,
                OrderProcessAssignment.trace_unit_id.in_(list(children.keys()) or [0]),
            )
        ).all()
    )
    for a in old:
        db.delete(a)
    db.flush()

    created = []
    for item in items:
        unit = children.get(int(item["bundle_id"]))
        if not unit:
            raise AssignmentError("bundle_mismatch", f"捆不属于该筐：{item.get('bundle_id')}")
        worker = db.get(Employee, int(item["worker_id"]))
        if not worker or worker.tenant_id != tenant_id or not worker.is_active:
            raise AssignmentError("worker_invalid", f"工人无效：{item.get('worker_id')}")
        quota = item.get("quota_qty")
        quota = int(quota) if quota is not None else int(unit.qty)
        row = OrderProcessAssignment(
            tenant_id=tenant_id,
            order_id=process.order_id,
            header_id=proc_header,
            order_process_id=process.id,
            worker_id=worker.id,
            trace_unit_id=unit.id,
            quota_qty=quota,
        )
        db.add(row)
        created.append(
            {
                "bundle_id": unit.id,
                "code": unit.code,
                "worker_id": worker.id,
                "worker_name": worker.name,
                "quota_qty": quota,
            }
        )
    db.commit()
    return {"basket_id": basket.id, "process_id": process.id, "items": created}
