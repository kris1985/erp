from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password, require_roles
from app.db import get_db
from app.models import User, Worker
from app.schemas.api import UserCreate, UserOut, UserUpdate
from app.schemas.common import normalize_page, ok, page_payload
from app.services import rbac_service
from app.services.rbac_service import RbacError

router = APIRouter(prefix="/users", tags=["users"])


def _validate_worker_link(db: Session, tenant_id: int, worker_id: int | None, *, exclude_user_id: int | None = None) -> None:
    if worker_id is None:
        return
    worker = db.scalar(
        select(Worker).where(Worker.tenant_id == tenant_id, Worker.id == worker_id, Worker.is_active.is_(True))
    )
    if not worker:
        raise HTTPException(status_code=400, detail="关联员工无效")
    q = select(User).where(User.tenant_id == tenant_id, User.worker_id == worker_id)
    if exclude_user_id is not None:
        q = q.where(User.id != exclude_user_id)
    if db.scalar(q):
        raise HTTPException(status_code=400, detail="该员工已关联其他用户")


def _user_out(db: Session, u: User) -> dict:
    worker_name = None
    if u.worker_id:
        w = db.get(Worker, u.worker_id)
        worker_name = w.name if w else None
    roles = rbac_service.list_user_role_codes(db, u)
    role_names = []
    for code in roles:
        row = rbac_service.get_tenant_role(db, u.tenant_id, code)
        role_names.append(row.name if row else code)
    primary = u.role.value if hasattr(u.role, "value") else str(u.role)
    return UserOut(
        id=u.id,
        username=u.username,
        display_name=u.display_name,
        role=primary,
        roles=roles,
        role_names=role_names,
        is_active=u.is_active,
        worker_id=u.worker_id,
        worker_name=worker_name,
    ).model_dump()


@router.get("")
def list_users(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    page, page_size, offset = normalize_page(page, page_size, max_size=500)
    base = select(User).where(User.tenant_id == user.tenant_id)
    total = int(db.scalar(select(func.count()).select_from(User).where(User.tenant_id == user.tenant_id)) or 0)
    rows = db.scalars(base.order_by(User.id).offset(offset).limit(page_size)).all()
    return ok(page_payload([_user_out(db, u) for u in rows], total, page, page_size))


@router.post("")
def create_user(body: UserCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    exists = db.scalar(
        select(User).where(User.tenant_id == user.tenant_id, User.username == body.username)
    )
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")
    role_codes = list(body.roles or [])
    if body.role and body.role not in role_codes:
        role_codes.insert(0, body.role)
    if not role_codes:
        raise HTTPException(status_code=400, detail="请至少选择一个角色")
    _validate_worker_link(db, user.tenant_id, body.worker_id)
    u = User(
        tenant_id=user.tenant_id,
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=role_codes[0],
        worker_id=body.worker_id,
    )
    db.add(u)
    db.flush()
    try:
        rbac_service.set_user_roles(db, u, role_codes)
    except RbacError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message) from e
    db.commit()
    db.refresh(u)
    return ok(_user_out(db, u))


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    target = db.get(User, user_id)
    if not target or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = body.model_dump(exclude_unset=True)
    if "password" in data:
        target.password_hash = hash_password(data.pop("password"))
    if "is_active" in data and target.id == user.id and data["is_active"] is False:
        raise HTTPException(status_code=400, detail="不能停用自己")
    if "worker_id" in data:
        _validate_worker_link(db, user.tenant_id, data["worker_id"], exclude_user_id=target.id)
        target.worker_id = data.pop("worker_id")
    roles = data.pop("roles", None)
    # 兼容旧字段 role
    single = data.pop("role", None)
    for k, v in data.items():
        setattr(target, k, v)
    if roles is not None or single is not None:
        role_codes = list(roles) if roles is not None else []
        if single and single not in role_codes:
            role_codes.append(single)
        try:
            rbac_service.set_user_roles(db, target, role_codes)
        except RbacError as e:
            raise HTTPException(status_code=400, detail=e.message) from e
    db.commit()
    db.refresh(target)
    return ok(_user_out(db, target))
