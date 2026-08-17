from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_employee, require_roles
from app.db import get_db
from app.models import Department, Employee, ProductionLine, Team
from app.schemas.api import ProductionLineCreate, ProductionLineOut, ProductionLineUpdate
from app.schemas.common import ok
from app.services import org_settings

router = APIRouter(prefix="/production-lines", tags=["production-lines"])


def _line_out(db: Session, line: ProductionLine, team_count: int = 0) -> dict:
    department_name = None
    if line.department_id:
        dep = db.get(Department, line.department_id)
        department_name = dep.name if dep and dep.tenant_id == line.tenant_id else None
    return ProductionLineOut(
        id=line.id,
        name=line.name,
        department_id=line.department_id,
        department_name=department_name,
        sort_order=line.sort_order,
        is_active=line.is_active,
        team_count=team_count,
    ).model_dump(mode="json")


@router.get("/config")
def get_config(
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    return ok({"enable_production_lines": org_settings.enable_production_lines(db, employee.tenant_id)})


@router.put("/config")
def set_config(
    body: dict,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_roles("admin", "manager")),
):
    enabled = bool(body.get("enable_production_lines", False))
    data = org_settings.set_enable_production_lines(db, employee.tenant_id, enabled)
    return ok(data)


@router.get("")
def list_production_lines(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    q = select(ProductionLine).where(ProductionLine.tenant_id == employee.tenant_id)
    if not include_inactive:
        q = q.where(ProductionLine.is_active.is_(True))
    lines = db.scalars(q.order_by(ProductionLine.sort_order, ProductionLine.id)).all()
    counts = dict(
        db.execute(
            select(Team.production_line_id, func.count())
            .where(
                Team.tenant_id == employee.tenant_id,
                Team.production_line_id.isnot(None),
                Team.is_active.is_(True),
            )
            .group_by(Team.production_line_id)
        ).all()
    )
    items = [_line_out(db, ln, int(counts.get(ln.id, 0))) for ln in lines]
    return ok({"items": items, "total": len(items)})


@router.post("")
def create_production_line(
    body: ProductionLineCreate,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_roles("admin", "manager")),
):
    tenant_id = employee.tenant_id
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写产线名称")
    if db.scalar(select(ProductionLine).where(ProductionLine.tenant_id == tenant_id, ProductionLine.name == name)):
        raise HTTPException(status_code=400, detail="产线名称已存在")
    if body.department_id is not None:
        dep = db.get(Department, body.department_id)
        if not dep or dep.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="所属部门无效")
    line = ProductionLine(
        tenant_id=tenant_id,
        name=name,
        department_id=body.department_id,
        sort_order=body.sort_order,
        is_active=True,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return ok(_line_out(db, line))


@router.patch("/{line_id}")
def update_production_line(
    line_id: int,
    body: ProductionLineUpdate,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_roles("admin", "manager")),
):
    tenant_id = employee.tenant_id
    line = db.get(ProductionLine, line_id)
    if not line or line.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="产线不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请填写产线名称")
        dup = db.scalar(
            select(ProductionLine).where(
                ProductionLine.tenant_id == tenant_id,
                ProductionLine.name == name,
                ProductionLine.id != line_id,
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail="产线名称已存在")
        data["name"] = name
    if "department_id" in data and data["department_id"] is not None:
        dep = db.get(Department, data["department_id"])
        if not dep or dep.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="所属部门无效")
    for k, v in data.items():
        setattr(line, k, v)
    db.commit()
    db.refresh(line)
    return ok(_line_out(db, line))


@router.delete("/{line_id}")
def delete_production_line(
    line_id: int,
    db: Session = Depends(get_db),
    employee: Employee = Depends(require_roles("admin", "manager")),
):
    tenant_id = employee.tenant_id
    line = db.get(ProductionLine, line_id)
    if not line or line.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="产线不存在")
    teams = db.scalar(
        select(func.count())
        .select_from(Team)
        .where(Team.tenant_id == tenant_id, Team.production_line_id == line_id)
    ) or 0
    if teams:
        raise HTTPException(status_code=400, detail=f"该产线下仍有 {teams} 个班组，请先移出或删除")
    db.delete(line)
    db.commit()
    return ok({"message": "产线已删除", "id": line_id})
