"""班组管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.models import User, Worker
from app.schemas.common import ok
from app.services import team_service
from app.services.team_service import TeamError

router = APIRouter(prefix="/teams", tags=["teams"])


class TeamCreate(BaseModel):
    name: str
    leader_worker_id: int
    worker_ids: list[int] = Field(default_factory=list)


class TeamUpdate(BaseModel):
    name: str | None = None
    leader_worker_id: int | None = None
    is_active: bool | None = None


class TeamMembersPut(BaseModel):
    worker_ids: list[int] = Field(default_factory=list)


@router.get("")
def api_list_teams(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
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
    user: User = Depends(require_roles("admin", "manager")),
):
    rows = db.scalars(
        select(Worker)
        .where(Worker.tenant_id == user.tenant_id, Worker.is_active.is_(True))
        .order_by(Worker.id.desc())
    ).all()
    return ok(
        {
            "items": [
                {
                    "id": w.id,
                    "name": w.name,
                    "mobile": w.mobile,
                    "role": w.role.value if hasattr(w.role, "value") else str(w.role),
                }
                for w in rows
            ]
        }
    )


@router.get("/worker-map")
def api_worker_team_map(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    return ok({"map": team_service.worker_team_map(db, user.tenant_id)})


@router.post("")
def api_create_team(
    body: TeamCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    try:
        return ok(
            team_service.create_team(
                db,
                user.tenant_id,
                name=body.name,
                leader_worker_id=body.leader_worker_id,
                worker_ids=body.worker_ids,
            )
        )
    except TeamError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.patch("/{team_id}")
def api_update_team(
    team_id: int,
    body: TeamUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    try:
        return ok(
            team_service.update_team(
                db,
                user.tenant_id,
                team_id,
                name=body.name,
                leader_worker_id=body.leader_worker_id,
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
    user: User = Depends(require_roles("admin", "manager")),
):
    try:
        return ok(team_service.set_team_members(db, user.tenant_id, team_id, body.worker_ids))
    except TeamError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/{team_id}")
def api_get_team(
    team_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
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
