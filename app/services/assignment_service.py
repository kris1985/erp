"""派工配额：已报量、剩余可报、报工匹配。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import OrderProcessAssignment, ReportType, WorkLog, WorkLogStatus


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
