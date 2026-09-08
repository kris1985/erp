"""H5 首页概览：员工看本人，班组长看本班组；任务按工序段隔离。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Color,
    Department,
    Employee,
    ExecutionHeader,
    OrderProcess,
    OrderProcessAssignment,
    OrderProcessStatus,
    OwnProduct,
    ProcessSegment,
    ReportType,
    SpecExecutionOrder,
    SpecExecutionStatus,
    Team,
    TeamMember,
    WorkLog,
    WorkLogStatus,
)
from app.services import salary_service, team_service

_ACTIVE_HEADER_STATUSES = (
    SpecExecutionStatus.confirmed,
    SpecExecutionStatus.cut,
    SpecExecutionStatus.in_progress,
)


def _worker_segments(db: Session, tenant_id: int, worker: Employee) -> list[ProcessSegment]:
    """员工可见工序段：部门归属 ∪ 所在班组段。"""
    seg_ids: set[int] = set()
    if worker.department_id:
        dep = db.get(Department, worker.department_id)
        if dep and dep.tenant_id == tenant_id and dep.process_segment_id:
            seg_ids.add(int(dep.process_segment_id))

    team_ids = set(
        db.scalars(
            select(TeamMember.team_id).where(
                TeamMember.tenant_id == tenant_id,
                TeamMember.worker_id == worker.id,
            )
        ).all()
    )
    team_rows = db.scalars(
        select(Team).where(
            Team.tenant_id == tenant_id,
            Team.is_active.is_(True),
            or_(
                Team.leader_worker_id == worker.id,
                Team.id.in_(list(team_ids) or [-1]),
            ),
        )
    ).all()
    for team in team_rows:
        if team.segment_id:
            seg_ids.add(int(team.segment_id))

    if not seg_ids:
        return []
    return list(
        db.scalars(
            select(ProcessSegment)
            .where(
                ProcessSegment.tenant_id == tenant_id,
                ProcessSegment.id.in_(list(seg_ids)),
                ProcessSegment.is_active.is_(True),
            )
            .order_by(ProcessSegment.sort_order, ProcessSegment.id)
        ).all()
    )


def _worker_home_tasks(db: Session, tenant_id: int, worker: Employee) -> list[dict]:
    """首页当前任务只显示本人已领取的；数量是领取双数，完工是本人报工。"""
    segments = _worker_segments(db, tenant_id, worker)
    if not segments:
        return []
    segment_ids = [int(seg.id) for seg in segments]
    segment_by_id = {int(seg.id): seg for seg in segments}

    claimed_rows = db.execute(
        select(
            ExecutionHeader.id.label("header_id"),
            ExecutionHeader.header_no,
            ExecutionHeader.total_qty,
            ExecutionHeader.delivery_date,
            ExecutionHeader.color_id,
            ExecutionHeader.parent_header_id,
            OwnProduct.product_code,
            OrderProcess.id.label("process_id"),
            OrderProcess.segment_id,
            OrderProcess.plan_qty,
            OrderProcess.status,
            OrderProcessAssignment.quota_qty,
        )
        .select_from(OrderProcessAssignment)
        .join(OrderProcess, OrderProcess.id == OrderProcessAssignment.order_process_id)
        .join(
            ExecutionHeader,
            (ExecutionHeader.id == OrderProcess.header_id)
            & (ExecutionHeader.tenant_id == tenant_id),
        )
        .outerjoin(OwnProduct, OwnProduct.id == ExecutionHeader.own_product_id)
        .where(
            OrderProcessAssignment.tenant_id == tenant_id,
            OrderProcessAssignment.worker_id == worker.id,
            OrderProcess.tenant_id == tenant_id,
            OrderProcess.header_id.is_not(None),
            OrderProcess.segment_id.in_(segment_ids),
            ExecutionHeader.status.in_(_ACTIVE_HEADER_STATUSES),
        )
        .order_by(
            ExecutionHeader.delivery_date.is_(None),
            ExecutionHeader.delivery_date.asc(),
            ExecutionHeader.id.desc(),
            OrderProcess.id.asc(),
        )
    ).all()

    grouped: dict[tuple[int, int], list] = {}
    for row in claimed_rows:
        key = (int(row.header_id), int(row.segment_id or 0))
        grouped.setdefault(key, []).append(row)

    process_ids = [int(row.process_id) for row in claimed_rows]
    reported_by_process: dict[int, int] = {}
    if process_ids:
        for process_id, qty in db.execute(
            select(
                WorkLog.order_process_id,
                func.coalesce(func.sum(WorkLog.qualified_qty), 0),
            ).where(
                WorkLog.tenant_id == tenant_id,
                WorkLog.worker_id == worker.id,
                WorkLog.order_process_id.in_(process_ids),
                WorkLog.status == WorkLogStatus.valid,
                WorkLog.report_type != ReportType.rework,
            ).group_by(WorkLog.order_process_id)
        ).all():
            reported_by_process[int(process_id)] = int(qty or 0)

    selected: list[tuple[object, int, int]] = []
    for items in grouped.values():
        open_items = [
            item for item in items
            if str(getattr(item.status, "value", item.status)) != OrderProcessStatus.completed.value
        ]
        if not open_items:
            continue
        quotas = [int(item.quota_qty) for item in open_items if item.quota_qty is not None]
        qty = quotas[0] if quotas else int(open_items[0].plan_qty or open_items[0].total_qty or 0)
        if quotas and qty > 0 and all(
            reported_by_process.get(int(item.process_id), 0) >= qty for item in open_items
        ):
            continue
        current = open_items[0]
        selected.append((current, qty, reported_by_process.get(int(current.process_id), 0)))
        if len(selected) >= 50:
            break

    header_ids = [int(row.header_id) for row, _qty, _done in selected]
    parent_ids = {int(row.parent_header_id) for row, _qty, _done in selected if row.parent_header_id}
    parent_no_by_id = {
        int(header.id): header.header_no
        for header in db.scalars(
            select(ExecutionHeader).where(
                ExecutionHeader.tenant_id == tenant_id,
                ExecutionHeader.id.in_(list(parent_ids) or [-1]),
            )
        ).all()
    }
    color_ids = {int(row.color_id) for row, _qty, _done in selected if row.color_id}
    # 头上无色时，回退到码明细上的颜色
    line_color_by_header: dict[int, int] = {}
    if header_ids:
        for header_id, color_id in db.execute(
            select(SpecExecutionOrder.header_id, SpecExecutionOrder.color_id)
            .where(
                SpecExecutionOrder.tenant_id == tenant_id,
                SpecExecutionOrder.header_id.in_(header_ids),
                SpecExecutionOrder.color_id.is_not(None),
            )
            .order_by(SpecExecutionOrder.id)
        ).all():
            hid = int(header_id or 0)
            if hid and hid not in line_color_by_header:
                line_color_by_header[hid] = int(color_id)
                color_ids.add(int(color_id))

    colors = {
        int(c.id): c.name
        for c in db.scalars(select(Color).where(Color.id.in_(list(color_ids) or [-1]))).all()
    } if color_ids else {}

    tasks: list[dict] = []
    for row, qty, completed_qty in selected:
        seg = segment_by_id.get(int(row.segment_id or 0))
        if not seg:
            continue
        color_id = int(row.color_id) if row.color_id else line_color_by_header.get(int(row.header_id))
        tasks.append(
            {
                "header_id": int(row.header_id),
                "header_no": row.header_no,
                "is_recut": bool(row.parent_header_id),
                "parent_header_no": parent_no_by_id.get(int(row.parent_header_id)) if row.parent_header_id else None,
                "product_code": row.product_code,
                "color_name": colors.get(color_id) if color_id else None,
                "qty": qty,
                "completed_qty": completed_qty,
                "task_name": seg.name,
                "segment_code": seg.code,
                "segment_id": int(seg.id),
                "delivery_date": row.delivery_date.isoformat() if row.delivery_date else None,
            }
        )
    return tasks


def worker_home_overview(db: Session, tenant_id: int, worker: Employee) -> dict:
    """返回员工或其所带班组的今日概览，金额仅限员工本人模式。"""
    team = None
    if team_service.is_leader(db, worker):
        teams = team_service.list_teams(db, tenant_id, leader_worker_id=worker.id)
        team = teams[0] if teams else None

    member_ids = {worker.id}
    if team:
        member_ids.update(int(member["id"]) for member in team.get("members", []) if member.get("id"))

    today = datetime.now().date()
    base_filters = [
        WorkLog.tenant_id == tenant_id,
        WorkLog.worker_id.in_(member_ids),
        WorkLog.status == WorkLogStatus.valid,
        func.date(WorkLog.created_at) == today,
    ]
    qualified, defects, record_count, reporter_count = db.execute(
        select(
            func.coalesce(func.sum(WorkLog.qualified_qty), 0),
            func.coalesce(func.sum(WorkLog.defect_qty), 0),
            func.count(WorkLog.id),
            func.count(func.distinct(WorkLog.worker_id)),
        ).where(*base_filters)
    ).one()

    is_leader = team is not None
    result = {
        "mode": "leader" if is_leader else "worker",
        "team_name": team.get("name") if team else None,
        "team_member_count": int(team.get("member_count", len(team.get("members", [])))) if team else 0,
        "today": {
            "qualified": int(qualified or 0),
            "defects": int(defects or 0),
            "record_count": int(record_count or 0),
            "reporter_count": int(reporter_count or 0),
        },
        "tasks": _worker_home_tasks(db, tenant_id, worker),
    }
    if not is_leader:
        salary = salary_service.month_salary(db, tenant_id, worker.id)
        result["month"] = {
            "amount": salary.get("total_wage", salary.get("total_piece_wage", 0)),
            "is_locked": bool(salary.get("is_locked")),
        }
    return result
