"""班组：组长绑 User；工人一人一组；组长数据范围解析。"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import OrderProcessAssignment, Team, TeamMember, User, Worker
from app.services import rbac_service


class TeamError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def is_team_scoped(db: Session, user: User) -> bool:
    """base_role=leader（含自定义天花板为 leader）启用班组隔离。"""
    base = rbac_service.effective_base_role(db, user.tenant_id, user.role)
    return base == "leader"


def leader_worker_ids(db: Session, user: User) -> set[int] | None:
    """None=不限制（admin/manager）；set=组长可见工员（可空）。"""
    if not is_team_scoped(db, user):
        return None
    team_ids = db.scalars(
        select(Team.id).where(
            Team.tenant_id == user.tenant_id,
            Team.leader_user_id == user.id,
            Team.is_active.is_(True),
        )
    ).all()
    if not team_ids:
        return set()
    rows = db.scalars(
        select(TeamMember.worker_id).where(
            TeamMember.tenant_id == user.tenant_id,
            TeamMember.team_id.in_(team_ids),
        )
    ).all()
    return set(int(x) for x in rows)


def leader_order_ids(db: Session, user: User, worker_ids: set[int] | None = None) -> set[int] | None:
    """经派工反查相关订单。None=不限制；set 可空。"""
    if worker_ids is None:
        worker_ids = leader_worker_ids(db, user)
    if worker_ids is None:
        return None
    if not worker_ids:
        return set()
    rows = db.scalars(
        select(OrderProcessAssignment.order_id)
        .where(
            OrderProcessAssignment.tenant_id == user.tenant_id,
            OrderProcessAssignment.worker_id.in_(worker_ids),
        )
        .distinct()
    ).all()
    return set(int(x) for x in rows)


def assert_workers_in_scope(db: Session, user: User, worker_ids: list[int] | set[int]) -> None:
    allowed = leader_worker_ids(db, user)
    if allowed is None:
        return
    bad = [wid for wid in worker_ids if int(wid) not in allowed]
    if bad:
        raise TeamError("out_of_team", "只能派工给本班组成员")


def assert_work_log_in_scope(db: Session, user: User, worker_id: int) -> None:
    allowed = leader_worker_ids(db, user)
    if allowed is None:
        return
    if int(worker_id) not in allowed:
        raise TeamError("out_of_team", "只能操作本班组报工")


def _team_out(db: Session, team: Team) -> dict:
    leader = db.get(User, team.leader_user_id)
    members = db.scalars(
        select(TeamMember).where(TeamMember.team_id == team.id).order_by(TeamMember.id)
    ).all()
    worker_ids = [m.worker_id for m in members]
    workers = []
    if worker_ids:
        wrows = db.scalars(select(Worker).where(Worker.id.in_(worker_ids))).all()
        by_id = {w.id: w for w in wrows}
        for wid in worker_ids:
            w = by_id.get(wid)
            if w:
                workers.append({"id": w.id, "name": w.name, "mobile": w.mobile})
    return {
        "id": team.id,
        "name": team.name,
        "leader_user_id": team.leader_user_id,
        "leader_name": leader.display_name if leader else None,
        "leader_username": leader.username if leader else None,
        "is_active": bool(team.is_active),
        "member_count": len(workers),
        "members": workers,
        "created_at": team.created_at.isoformat() if team.created_at else None,
    }


def list_teams(
    db: Session,
    tenant_id: int,
    *,
    include_inactive: bool = False,
    leader_user_id: int | None = None,
) -> list[dict]:
    q = select(Team).where(Team.tenant_id == tenant_id)
    if not include_inactive:
        q = q.where(Team.is_active.is_(True))
    if leader_user_id is not None:
        q = q.where(Team.leader_user_id == leader_user_id)
    rows = db.scalars(q.order_by(Team.id.desc())).all()
    return [_team_out(db, t) for t in rows]


def get_team(db: Session, tenant_id: int, team_id: int) -> Team:
    team = db.scalar(select(Team).where(Team.tenant_id == tenant_id, Team.id == team_id))
    if not team:
        raise TeamError("not_found", "班组不存在")
    return team


def create_team(
    db: Session,
    tenant_id: int,
    *,
    name: str,
    leader_user_id: int,
    worker_ids: list[int] | None = None,
) -> dict:
    name = (name or "").strip()
    if not name:
        raise TeamError("invalid_name", "请填写班组名称")
    leader = db.scalar(
        select(User).where(User.tenant_id == tenant_id, User.id == leader_user_id, User.is_active.is_(True))
    )
    if not leader:
        raise TeamError("invalid_leader", "组长账号无效")
    exists = db.scalar(select(Team).where(Team.tenant_id == tenant_id, Team.name == name))
    if exists:
        raise TeamError("duplicate_name", "班组名称已存在")
    team = Team(tenant_id=tenant_id, name=name, leader_user_id=leader_user_id, is_active=True)
    db.add(team)
    db.flush()
    if worker_ids:
        _set_members(db, tenant_id, team, worker_ids)
    db.commit()
    db.refresh(team)
    return _team_out(db, team)


def update_team(
    db: Session,
    tenant_id: int,
    team_id: int,
    *,
    name: str | None = None,
    leader_user_id: int | None = None,
    is_active: bool | None = None,
) -> dict:
    team = get_team(db, tenant_id, team_id)
    if name is not None:
        name = name.strip()
        if not name:
            raise TeamError("invalid_name", "请填写班组名称")
        clash = db.scalar(
            select(Team).where(
                Team.tenant_id == tenant_id,
                Team.name == name,
                Team.id != team_id,
            )
        )
        if clash:
            raise TeamError("duplicate_name", "班组名称已存在")
        team.name = name
    if leader_user_id is not None:
        leader = db.scalar(
            select(User).where(
                User.tenant_id == tenant_id, User.id == leader_user_id, User.is_active.is_(True)
            )
        )
        if not leader:
            raise TeamError("invalid_leader", "组长账号无效")
        team.leader_user_id = leader_user_id
    if is_active is not None:
        team.is_active = bool(is_active)
    db.commit()
    db.refresh(team)
    return _team_out(db, team)


def _set_members(db: Session, tenant_id: int, team: Team, worker_ids: list[int]) -> None:
    ids = sorted({int(x) for x in worker_ids if x})
    if ids:
        found = db.scalars(
            select(Worker.id).where(Worker.tenant_id == tenant_id, Worker.id.in_(ids))
        ).all()
        found_set = set(int(x) for x in found)
        missing = [i for i in ids if i not in found_set]
        if missing:
            raise TeamError("invalid_worker", f"工人不存在：{missing}")
        # 已在其他组
        conflicts = db.scalars(
            select(TeamMember).where(
                TeamMember.tenant_id == tenant_id,
                TeamMember.worker_id.in_(ids),
                TeamMember.team_id != team.id,
            )
        ).all()
        if conflicts:
            names = []
            for c in conflicts:
                w = db.get(Worker, c.worker_id)
                names.append(w.name if w else str(c.worker_id))
            raise TeamError("worker_in_other_team", f"以下工人已在其他班组：{'、'.join(names)}")

    db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    for wid in ids:
        db.add(TeamMember(tenant_id=tenant_id, team_id=team.id, worker_id=wid))
    db.flush()


def set_team_members(db: Session, tenant_id: int, team_id: int, worker_ids: list[int]) -> dict:
    team = get_team(db, tenant_id, team_id)
    _set_members(db, tenant_id, team, worker_ids)
    db.commit()
    db.refresh(team)
    return _team_out(db, team)


def worker_team_map(db: Session, tenant_id: int) -> dict[int, dict]:
    """worker_id -> {team_id, team_name}，供管理端勾选禁用。"""
    rows = db.execute(
        select(TeamMember.worker_id, Team.id, Team.name)
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.tenant_id == tenant_id, Team.is_active.is_(True))
    ).all()
    return {int(wid): {"team_id": int(tid), "team_name": name} for wid, tid, name in rows}
