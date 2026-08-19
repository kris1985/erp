"""班组管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal, get_current_employee, get_principal, require_roles
from app.db import get_db
from app.models import Employee
from app.schemas.common import ok
from app.services import team_service
from app.services.team_service import TeamError

router = APIRouter(prefix="/teams", tags=["teams"])


class TeamCreate(BaseModel):
    name: str
    # 工序段重构（13.1/B1）：组长可空（无组长默认组）；segment_id 可选（未传从部门继承）
    leader_worker_id: int | None = None
    worker_ids: list[int] = Field(default_factory=list)
    department_id: int | None = None
    segment_id: int | None = None
    production_line_id: int | None = None


class TeamUpdate(BaseModel):
    name: str | None = None
    leader_worker_id: int | None = None
    department_id: int | None = None
    segment_id: int | None = None
    production_line_id: int | None = None
    is_active: bool | None = None


class TeamMembersPut(BaseModel):
    worker_ids: list[int] = Field(default_factory=list)


class TeamMemberIn(BaseModel):
    worker_id: int
    team_id: int | None = None


def _http_team_error(e: TeamError) -> HTTPException:
    status = 404 if e.code in ("not_found",) else 400
    if e.code in ("not_leader", "not_your_team"):
        status = 403
    return HTTPException(status_code=status, detail=e.message)


def _require_leader_worker(db: Session, principal: Principal) -> Employee:
    if not principal.employee:
        raise HTTPException(status_code=403, detail="请登录后操作")
    try:
        team_service.assert_leader_role(db, principal.employee)
    except TeamError as e:
        raise _http_team_error(e) from e
    return principal.employee


@router.get("")
def api_list_teams(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    # 组长只看自己带的班组；主管/管理员看全部
    leader_only = None
    if team_service.is_team_scoped(db, user):
        leader_only = team_service.resolve_leader_worker_id(db, user) or -1
    items = team_service.list_teams(
        db,
        user.tenant_id,
        include_inactive=include_inactive and not team_service.is_team_scoped(db, user),
        leader_worker_id=leader_only,
    )
    return ok({"items": items, "total": len(items)})


@router.get("/leader-candidates")
def api_leader_candidates(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    rows = db.scalars(
        select(Employee)
        .where(Employee.tenant_id == user.tenant_id, Employee.is_active.is_(True))
        .order_by(Employee.id.desc())
    ).all()
    return ok(
        {
            "items": [
                {
                    "id": w.id,
                    "name": w.name,
                    "mobile": w.mobile,
                }
                for w in rows
            ]
        }
    )


@router.get("/worker-map")
def api_worker_team_map(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    return ok({"map": team_service.worker_team_map(db, user.tenant_id)})


@router.get("/mine")
def api_my_teams(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    leader = _require_leader_worker(db, principal)
    items = team_service.list_teams(
        db, leader.tenant_id, leader_worker_id=leader.id
    )
    return ok({"items": items, "total": len(items)})


@router.get("/mine/candidates")
def api_search_my_candidates(
    q: str = "",
    team_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    leader = _require_leader_worker(db, principal)
    try:
        team = team_service.resolve_led_team(db, leader.tenant_id, leader.id, team_id)
        items = team_service.search_join_candidates(
            db, leader.tenant_id, team_id=team.id, q=q
        )
    except TeamError as e:
        raise _http_team_error(e) from e
    return ok({"items": items, "team_id": team.id, "team_name": team.name})


@router.post("/mine/members")
def api_add_my_member(
    body: TeamMemberIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    leader = _require_leader_worker(db, principal)
    try:
        team = team_service.resolve_led_team(
            db, leader.tenant_id, leader.id, body.team_id
        )
        return ok(
            team_service.add_team_member(
                db,
                leader.tenant_id,
                team.id,
                body.worker_id,
                actor_worker_id=leader.id,
            )
        )
    except TeamError as e:
        raise _http_team_error(e) from e


@router.delete("/mine/members/{worker_id}")
def api_remove_my_member(
    worker_id: int,
    team_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    leader = _require_leader_worker(db, principal)
    try:
        team = team_service.resolve_led_team(db, leader.tenant_id, leader.id, team_id)
        return ok(
            team_service.remove_team_member(
                db,
                leader.tenant_id,
                team.id,
                worker_id,
                actor_worker_id=leader.id,
            )
        )
    except TeamError as e:
        raise _http_team_error(e) from e


@router.post("")
def api_create_team(
    body: TeamCreate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    try:
        return ok(
            team_service.create_team(
                db,
                user.tenant_id,
                name=body.name,
                leader_worker_id=body.leader_worker_id,
                worker_ids=body.worker_ids,
                department_id=body.department_id,
                segment_id=body.segment_id,
                production_line_id=body.production_line_id,
            )
        )
    except TeamError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.patch("/{team_id}")
def api_update_team(
    team_id: int,
    body: TeamUpdate,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    try:
        return ok(
            team_service.update_team(
                db,
                user.tenant_id,
                team_id,
                name=body.name,
                leader_worker_id=body.leader_worker_id,
                department_id=body.department_id,
                segment_id=body.segment_id,
                production_line_id=body.production_line_id,
                is_active=body.is_active,
            )
        )
    except TeamError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.put("/{team_id}/members")
def api_set_members(
    team_id: int,
    body: TeamMembersPut,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles("admin", "manager")),
):
    try:
        return ok(team_service.set_team_members(db, user.tenant_id, team_id, body.worker_ids))
    except TeamError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/{team_id}")
def api_get_team(
    team_id: int,
    db: Session = Depends(get_db),
    user: Employee = Depends(get_current_employee),
):
    try:
        team = team_service.get_team(db, user.tenant_id, team_id)
    except TeamError as e:
        raise HTTPException(status_code=404, detail=e.message)
    if team_service.is_team_scoped(db, user):
        wid = team_service.resolve_leader_worker_id(db, user)
        if not wid or team.leader_worker_id != wid:
            raise HTTPException(status_code=403, detail="只能查看自己的班组")
    return ok(team_service._team_out(db, team))
