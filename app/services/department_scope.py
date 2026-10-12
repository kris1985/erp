"""挂了工序段的叶子部门：工艺路线展示和派工候选。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Department, Employee, ProcessSegment


def list_segment_leaf_departments(db: Session, tenant_id: int) -> list[dict]:
    """启用部门里，没有启用子部门、且挂了启用工序段的结点。"""
    departments = list(
        db.scalars(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.is_active.is_(True),
            )
        ).all()
    )
    parent_ids = {int(dep.parent_id) for dep in departments if dep.parent_id is not None}
    leaves = [
        dep
        for dep in departments
        if dep.process_segment_id is not None and int(dep.id) not in parent_ids
    ]
    if not leaves:
        return []
    segments = {
        int(seg.id): seg
        for seg in db.scalars(
            select(ProcessSegment).where(
                ProcessSegment.tenant_id == tenant_id,
                ProcessSegment.id.in_([int(dep.process_segment_id) for dep in leaves]),
                ProcessSegment.is_active.is_(True),
            )
        ).all()
    }
    rows = []
    for dep in leaves:
        seg = segments.get(int(dep.process_segment_id))
        if seg is None:
            continue
        rows.append(
            {
                "id": int(dep.id),
                "name": dep.name,
                "parent_id": int(dep.parent_id) if dep.parent_id is not None else None,
                "process_segment_id": int(seg.id),
                "segment_name": seg.name,
                "segment_code": seg.code,
                "segment_sort_order": int(seg.sort_order or 0),
                "segment_is_optional": bool(seg.is_optional),
                "sort_order": int(dep.sort_order or 0),
            }
        )
    rows.sort(
        key=lambda row: (
            row["segment_sort_order"],
            row["process_segment_id"],
            row["sort_order"],
            row["id"],
        )
    )
    return rows


def department_tree_ids(db: Session, tenant_id: int, root_ids: list[int]) -> set[int]:
    """根部门及其启用后代。"""
    if not root_ids:
        return set()
    departments = db.execute(
        select(Department.id, Department.parent_id).where(
            Department.tenant_id == tenant_id,
            Department.is_active.is_(True),
        )
    ).all()
    children: dict[int, list[int]] = {}
    for dep_id, parent_id in departments:
        if parent_id is None:
            continue
        children.setdefault(int(parent_id), []).append(int(dep_id))
    scope: set[int] = set()
    stack = [int(dep_id) for dep_id in root_ids]
    while stack:
        current = stack.pop()
        if current in scope:
            continue
        scope.add(current)
        stack.extend(children.get(current, []))
    return scope


def employee_ids_in_departments(db: Session, tenant_id: int, department_ids: list[int]) -> set[int]:
    scope = department_tree_ids(db, tenant_id, department_ids)
    if not scope:
        return set()
    return {
        int(worker_id)
        for worker_id in db.scalars(
            select(Employee.id).where(
                Employee.tenant_id == tenant_id,
                Employee.is_active.is_(True),
                Employee.department_id.in_(list(scope)),
            )
        ).all()
    }
