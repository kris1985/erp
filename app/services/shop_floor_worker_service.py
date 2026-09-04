"""现场报工可选工人名单。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Department,
    Employee,
    EmployeeProcessAssignment,
    ProcessDefinition,
    ProcessSegment,
    Team,
)
from app.services import employee_process_service


def list_shop_floor_workers(
    db: Session,
    tenant_id: int,
    *,
    process_id: int | None = None,
    segment_code: str | None = None,
) -> list[Employee]:
    base = select(Employee).where(
        Employee.tenant_id == tenant_id,
        Employee.is_active.is_(True),
    )
    if process_id is not None:
        proc = db.get(ProcessDefinition, process_id)
        if not proc or proc.tenant_id != tenant_id or not proc.is_active:
            return []
        has_any = employee_process_service.tenant_has_assignments(db, tenant_id)
        if has_any:
            assigned = base.join(
                EmployeeProcessAssignment,
                EmployeeProcessAssignment.employee_id == Employee.id,
            ).where(
                EmployeeProcessAssignment.tenant_id == tenant_id,
                EmployeeProcessAssignment.process_id == process_id,
            )
            return list(db.scalars(assigned.order_by(Employee.id)).all())
        # 冷启动：租户尚未配置员工工序时，按工序段部门兜底
        seg_id = proc.segment_id
        if seg_id is None:
            return list(db.scalars(base.order_by(Employee.id)).all())
        seg = db.get(ProcessSegment, seg_id)
        code = seg.code if seg and seg.tenant_id == tenant_id else segment_code
        if code:
            return _filter_by_segment_code(db, tenant_id, base, code)
        return list(db.scalars(base.order_by(Employee.id)).all())

    code = (segment_code or "").strip()
    if code:
        return _filter_by_segment_code(db, tenant_id, base, code)
    return list(db.scalars(base.order_by(Employee.id)).all())


def _filter_by_segment_code(
    db: Session,
    tenant_id: int,
    base,
    segment_code: str,
) -> list[Employee]:
    query = (
        base
        .join(Department, Department.id == Employee.department_id)
        .join(ProcessSegment, ProcessSegment.id == Department.process_segment_id)
        .where(
            Department.tenant_id == tenant_id,
            ProcessSegment.tenant_id == tenant_id,
            ProcessSegment.code == segment_code,
            ProcessSegment.is_active.is_(True),
        )
    )
    return list(db.scalars(query.order_by(Employee.id)).all())


def leader_role_map(db: Session, tenant_id: int, worker_ids: list[int]) -> dict[int, str]:
    if not worker_ids:
        return {}
    leader_ids = set(
        db.scalars(
            select(Team.leader_worker_id).where(
                Team.tenant_id == tenant_id,
                Team.is_active.is_(True),
                Team.leader_worker_id.in_(worker_ids),
            )
        ).all()
    )
    return {wid: ("组长" if wid in leader_ids else "员工") for wid in worker_ids}
