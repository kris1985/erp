from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import get_current_employee
from app.db import get_db
from app.models import Department, Employee, ProductionLine, Team
from app.schemas.api import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.schemas.common import ok

router = APIRouter(prefix="/departments", tags=["departments"])


def _valid_segment(db: Session, tenant_id: int, segment_id: int | None) -> int | None:
    if segment_id is None:
        return None
    from app.models import ProcessSegment

    seg = db.get(ProcessSegment, segment_id)
    if not seg or seg.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="工序段不存在")
    return seg.id


def _valid_leader(db: Session, tenant_id: int, leader_id: int | None) -> int | None:
    if leader_id is None:
        return None
    ldr = db.get(Employee, leader_id)
    if not ldr or ldr.tenant_id != tenant_id or not ldr.is_active:
        raise HTTPException(status_code=400, detail="负责人无效（须为本厂在职员工）")
    return ldr.id


def _department_out(db: Session, dep: Department, employee_count: int = 0) -> dict:
    manager_name = None
    manager_mobile = None
    if dep.manager_employee_id:
        mgr = db.get(Employee, dep.manager_employee_id)
        if mgr and mgr.tenant_id == dep.tenant_id:
            manager_name = mgr.name
            manager_mobile = mgr.mobile
    # 工序段重构（15.1）：段 + 段负责人
    from app.models import ProcessSegment

    segment_name = None
    if dep.process_segment_id:
        seg = db.get(ProcessSegment, dep.process_segment_id)
        segment_name = seg.name if seg and seg.tenant_id == dep.tenant_id else None
    leader_name = None
    if dep.leader_id:
        ldr = db.get(Employee, dep.leader_id)
        leader_name = ldr.name if ldr and ldr.tenant_id == dep.tenant_id else None
    return DepartmentOut(
        id=dep.id,
        name=dep.name,
        parent_id=dep.parent_id,
        manager_employee_id=dep.manager_employee_id,
        manager_name=manager_name,
        manager_mobile=manager_mobile,
        process_segment_id=dep.process_segment_id,
        segment_name=segment_name,
        leader_id=dep.leader_id,
        leader_name=leader_name,
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
    # 子部门未选工序段时自动继承父部门段（防"未分段"掉出派工候选；生产部门挂段是常态）
    segment_id = body.process_segment_id
    if segment_id is None and body.parent_id is not None and parent is not None:
        segment_id = parent.process_segment_id
    if body.manager_employee_id is not None:
        mgr = db.get(Employee, body.manager_employee_id)
        if not mgr or mgr.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="主管无效（须为本厂员工）")
    dep = Department(
        tenant_id=tenant_id,
        name=name,
        parent_id=body.parent_id,
        manager_employee_id=body.manager_employee_id,
        process_segment_id=_valid_segment(db, tenant_id, segment_id),
        leader_id=_valid_leader(db, tenant_id, body.leader_id),
        sort_order=body.sort_order,
        is_active=True,
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)
    # 15.3：部门负责人 → 默认组 leader 同步
    from app.services.team_service import sync_default_team_leader

    sync_default_team_leader(db, tenant_id, dep)
    # 无班组模式「部门=组」：挂段部门建即补隐身默认组（与员工进部门同步配套）
    if dep.process_segment_id:
        from app.services import org_settings
        from app.services.team_service import ensure_default_team

        if not org_settings.enable_teams(db, tenant_id):
            ensure_default_team(db, tenant_id, dep)
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
    if "process_segment_id" in data:
        data["process_segment_id"] = _valid_segment(db, tenant_id, data["process_segment_id"])
    if "leader_id" in data:
        data["leader_id"] = _valid_leader(db, tenant_id, data["leader_id"])
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
    leader_changed = "leader_id" in data and data["leader_id"] != dep.leader_id
    segment_changed = "process_segment_id" in data and data["process_segment_id"] != dep.process_segment_id
    for k, v in data.items():
        setattr(dep, k, v)
    db.commit()
    db.refresh(dep)
    from app.services.team_service import sync_default_team_leader, sync_teams_segment_for_department

    if leader_changed:
        sync_default_team_leader(db, tenant_id, dep)  # 15.3：负责人→默认组组长
    if segment_changed:
        sync_teams_segment_for_department(db, tenant_id, dep)  # 15.4/B2：部门改段→班组级联
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
    teams = db.scalars(
        select(Team).where(Team.tenant_id == tenant_id, Team.department_id == department_id)
    ).all()
    if teams:
        names = "、".join(t.name for t in teams[:5])
        more = " 等" if len(teams) > 5 else ""
        raise HTTPException(status_code=400, detail=f"请先删除班组：{names}{more}")
    # 产线已废弃：旧行仍挂 department_id，不删会撞 FK。班组若还挂产线先解开再删行。
    old_lines = db.scalars(
        select(ProductionLine).where(
            ProductionLine.tenant_id == tenant_id,
            ProductionLine.department_id == department_id,
        )
    ).all()
    if old_lines:
        db.execute(
            update(Team)
            .where(
                Team.tenant_id == tenant_id,
                Team.production_line_id.in_([ln.id for ln in old_lines]),
            )
            .values(production_line_id=None)
        )
        for ln in old_lines:
            db.delete(ln)
    db.delete(dep)
    db.commit()
    return ok({"message": "部门已删除", "id": department_id})
