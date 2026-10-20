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
    department_id: int | None = None,
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
            return _limit_department(
                db, tenant_id, list(db.scalars(assigned.order_by(Employee.id)).all()), department_id
            )
        # 冷启动：租户尚未配置员工工序时，按工序段部门兜底
        seg_id = proc.segment_id
        if seg_id is None:
            return _limit_department(db, tenant_id, list(db.scalars(base.order_by(Employee.id)).all()), department_id)
        seg = db.get(ProcessSegment, seg_id)
        code = seg.code if seg and seg.tenant_id == tenant_id else segment_code
        if code:
            return _limit_department(db, tenant_id, _filter_by_segment_code(db, tenant_id, base, code), department_id)
        return _limit_department(db, tenant_id, list(db.scalars(base.order_by(Employee.id)).all()), department_id)

    code = (segment_code or "").strip()
    if code:
        return _limit_department(db, tenant_id, _filter_by_segment_code(db, tenant_id, base, code), department_id)
    return _limit_department(db, tenant_id, list(db.scalars(base.order_by(Employee.id)).all()), department_id)


def list_segment_department_workers(db: Session, tenant_id: int) -> list[Employee]:
    """责任人候选：挂了工序段的部门，以及这些部门下级里的全部在职人员。"""
    departments = list(
        db.scalars(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.is_active.is_(True),
            )
        ).all()
    )
    rooted = [dep for dep in departments if dep.process_segment_id]
    if not rooted:
        return []
    from app.services.department_scope import employee_ids_in_departments

    allowed = employee_ids_in_departments(db, tenant_id, [int(dep.id) for dep in rooted])
    if not allowed:
        return []
    workers = list(
        db.scalars(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.is_active.is_(True),
                Employee.id.in_(list(allowed)),
            )
        ).all()
    )
    by_id = {int(dep.id): dep for dep in departments}
    segment_ids = {int(dep.process_segment_id) for dep in departments if dep.process_segment_id}
    segment_sorts = {
        int(segment.id): int(segment.sort_order or 0)
        for segment in db.scalars(
            select(ProcessSegment).where(ProcessSegment.id.in_(list(segment_ids)))
        ).all()
    } if segment_ids else {}

    def _sort_key(worker: Employee) -> tuple:
        dep = by_id.get(int(worker.department_id or 0))
        seen: set[int] = set()
        segment_sort = 10**9
        department_name = ""
        while dep is not None and int(dep.id) not in seen:
            seen.add(int(dep.id))
            department_name = department_name or (dep.name or "")
            if dep.process_segment_id:
                segment_sort = segment_sorts.get(int(dep.process_segment_id), 10**9)
                break
            dep = by_id.get(int(dep.parent_id)) if dep.parent_id else None
        return (segment_sort, department_name, worker.name or "", int(worker.id))

    workers.sort(key=_sort_key)
    return workers


def _limit_department(
    db: Session,
    tenant_id: int,
    workers: list[Employee],
    department_id: int | None,
) -> list[Employee]:
    """派到某个部门时，只留这个部门及其下级的在职人员。"""
    if not department_id:
        return workers
    from app.services.department_scope import employee_ids_in_departments

    allowed = employee_ids_in_departments(db, tenant_id, [int(department_id)])
    return [worker for worker in workers if int(worker.id) in allowed]


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
