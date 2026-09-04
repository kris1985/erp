"""员工可报工序（多选）。"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Employee, EmployeeProcessAssignment, ProcessDefinition


def list_ids(db: Session, employee: Employee) -> list[int]:
    return list(db.scalars(
        select(EmployeeProcessAssignment.process_id)
        .where(
            EmployeeProcessAssignment.tenant_id == employee.tenant_id,
            EmployeeProcessAssignment.employee_id == employee.id,
        )
        .order_by(EmployeeProcessAssignment.process_id)
    ).all())


def list_names(db: Session, employee: Employee) -> list[str]:
    ids = list_ids(db, employee)
    if not ids:
        return []
    rows = db.scalars(
        select(ProcessDefinition.name)
        .where(
            ProcessDefinition.tenant_id == employee.tenant_id,
            ProcessDefinition.id.in_(ids),
        )
        .order_by(ProcessDefinition.sort_order, ProcessDefinition.id)
    ).all()
    return list(rows)


def resolve_process_ids(db: Session, tenant_id: int, process_ids: list[int]) -> list[int]:
    cleaned = sorted({int(pid) for pid in process_ids if int(pid) > 0})
    if not cleaned:
        return []
    found = set(db.scalars(
        select(ProcessDefinition.id).where(
            ProcessDefinition.tenant_id == tenant_id,
            ProcessDefinition.id.in_(cleaned),
            ProcessDefinition.is_active.is_(True),
        )
    ).all())
    missing = [pid for pid in cleaned if pid not in found]
    if missing:
        raise ValueError("工序不存在或未启用")
    return cleaned


def set_ids(db: Session, employee: Employee, process_ids: list[int]) -> list[int]:
    cleaned = resolve_process_ids(db, employee.tenant_id, process_ids)
    db.execute(delete(EmployeeProcessAssignment).where(
        EmployeeProcessAssignment.tenant_id == employee.tenant_id,
        EmployeeProcessAssignment.employee_id == employee.id,
    ))
    for pid in cleaned:
        db.add(EmployeeProcessAssignment(
            tenant_id=employee.tenant_id,
            employee_id=employee.id,
            process_id=pid,
        ))
    db.flush()
    return cleaned


def tenant_has_assignments(db: Session, tenant_id: int) -> bool:
    return bool(db.scalar(
        select(func.count()).select_from(EmployeeProcessAssignment).where(
            EmployeeProcessAssignment.tenant_id == tenant_id
        )
    ))
