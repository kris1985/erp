from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_employee
from app.db import get_db
from app.models import Department, Employee
from app.schemas.api import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.schemas.common import ok

router = APIRouter(prefix="/departments", tags=["departments"])


def _department_out(db: Session, dep: Department, employee_count: int = 0) -> dict:
    manager_name = None
    manager_mobile = None
    if dep.manager_employee_id:
        mgr = db.get(Employee, dep.manager_employee_id)
        if mgr and mgr.tenant_id == dep.tenant_id:
            manager_name = mgr.name
            manager_mobile = mgr.mobile
    return DepartmentOut(
        id=dep.id,
        name=dep.name,
        parent_id=dep.parent_id,
        manager_employee_id=dep.manager_employee_id,
        manager_name=manager_name,
        manager_mobile=manager_mobile,
        sort_order=dep.sort_order,
        is_active=dep.is_active,
        employee_count=employee_count,
    ).model_dump(mode="json")


@router.get("")
def list_departments(
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    deps = db.scalars(
        select(Department)
        .where(Department.tenant_id == employee.tenant_id)
        .order_by(Department.sort_order, Department.id)
    ).all()
    counts = dict(
        db.execute(
            select(Employee.department_id, func.count())
            .where(
                Employee.tenant_id == employee.tenant_id,
                Employee.department_id.isnot(None),
                Employee.is_active.is_(True),
            )
            .group_by(Employee.department_id)
        ).all()
    )
    items = [_department_out(db, d, int(counts.get(d.id, 0))) for d in deps]
    return ok({"items": items, "total": len(items)})


@router.post("")
def create_department(
    body: DepartmentCreate,
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    tenant_id = employee.tenant_id
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写部门名称")
    exists = db.scalar(
        select(Department).where(Department.tenant_id == tenant_id, Department.name == name)
    )
    if exists:
        raise HTTPException(status_code=400, detail="部门名称已存在")
    if body.parent_id is not None:
        parent = db.get(Department, body.parent_id)
        if not parent or parent.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="上级部门不存在")
    if body.manager_employee_id is not None:
        mgr = db.get(Employee, body.manager_employee_id)
        if not mgr or mgr.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="主管无效（须为本厂员工）")
    dep = Department(
        tenant_id=tenant_id,
        name=name,
        parent_id=body.parent_id,
        manager_employee_id=body.manager_employee_id,
        sort_order=body.sort_order,
        is_active=True,
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)
    return ok(_department_out(db, dep))


@router.patch("/{department_id}")
def update_department(
    department_id: int,
    body: DepartmentUpdate,
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    tenant_id = employee.tenant_id
    dep = db.get(Department, department_id)
    if not dep or dep.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="部门不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写部门名称")
        dup = db.scalar(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.name == name,
                Department.id != department_id,
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail="部门名称已存在")
        data["name"] = name
    if "parent_id" in data:
        pid = data["parent_id"]
        if pid is not None:
            if pid == department_id:
                raise HTTPException(status_code=400, detail="上级部门不能是自己")
            parent = db.get(Department, pid)
            if not parent or parent.tenant_id != tenant_id:
                raise HTTPException(status_code=400, detail="上级部门不存在")
            # 防环：上级不能是自己的子孙
            node = parent
            while node is not None and node.parent_id is not None:
                if node.parent_id == department_id:
                    raise HTTPException(status_code=400, detail="不能把子部门设为上级")
                node = db.get(Department, node.parent_id)
        data["parent_id"] = pid
    if "manager_employee_id" in data:
        mgr_id = data["manager_employee_id"]
        if mgr_id is not None:
            mgr = db.get(Employee, mgr_id)
            if not mgr or mgr.tenant_id != tenant_id:
                raise HTTPException(status_code=400, detail="主管无效（须为本厂员工）")
        data["manager_employee_id"] = mgr_id
    if "is_active" in data and data["is_active"] is False:
        active_children = db.scalar(
            select(func.count())
            .select_from(Department)
            .where(Department.tenant_id == tenant_id, Department.parent_id == department_id, Department.is_active.is_(True))
        ) or 0
        if active_children:
            raise HTTPException(status_code=400, detail="请先停用子部门")
        active_members = db.scalar(
            select(func.count())
            .select_from(Employee)
            .where(Employee.tenant_id == tenant_id, Employee.department_id == department_id, Employee.is_active.is_(True))
        ) or 0
        if active_members:
            raise HTTPException(status_code=400, detail="请先移除或停用部门内员工")
    for k, v in data.items():
        setattr(dep, k, v)
    db.commit()
    db.refresh(dep)
    return ok(_department_out(db, dep))


@router.delete("/{department_id}")
def delete_department(
    department_id: int,
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    """删除部门：先检查无子部门且无员工（含停用员工），否则拒绝并提示。"""
    tenant_id = employee.tenant_id
    dep = db.get(Department, department_id)
    if not dep or dep.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="部门不存在")
    children = db.scalars(
        select(Department).where(Department.tenant_id == tenant_id, Department.parent_id == department_id)
    ).all()
    if children:
        names = "、".join(c.name for c in children[:5])
        more = " 等" if len(children) > 5 else ""
        raise HTTPException(status_code=400, detail=f"请先删除子部门：{names}{more}")
    members = db.scalar(
        select(func.count())
        .select_from(Employee)
        .where(Employee.tenant_id == tenant_id, Employee.department_id == department_id)
    ) or 0
    if members:
        raise HTTPException(status_code=400, detail=f"该部门下仍有 {members} 名员工，请先移出或删除")
    db.delete(dep)
    db.commit()
    return ok({"message": "部门已删除", "id": department_id})
