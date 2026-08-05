from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password, require_roles
from app.db import get_db
from app.models import User
from app.schemas.api import UserCreate, UserOut, UserUpdate
from app.schemas.common import ok
from app.services.rbac_service import RbacError, assert_assignable_role

router = APIRouter(prefix="/users", tags=["users"])


def _user_out(u: User) -> dict:
    return UserOut(
        id=u.id,
        username=u.username,
        display_name=u.display_name,
        role=u.role.value if hasattr(u.role, "value") else str(u.role),
        is_active=u.is_active,
    ).model_dump()


@router.get("")
def list_users(db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    rows = db.scalars(select(User).where(User.tenant_id == user.tenant_id).order_by(User.id)).all()
    return ok({"items": [_user_out(u) for u in rows], "total": len(rows)})


@router.post("")
def create_user(body: UserCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    exists = db.scalar(
        select(User).where(User.tenant_id == user.tenant_id, User.username == body.username)
    )
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")
    try:
        assert_assignable_role(db, user.tenant_id, body.role)
    except RbacError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    u = User(
        tenant_id=user.tenant_id,
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return ok(_user_out(u))


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
    if "role" in data:
        try:
            assert_assignable_role(db, user.tenant_id, data["role"])
        except RbacError as e:
            raise HTTPException(status_code=400, detail=e.message) from e
    if "is_active" in data and target.id == user.id and data["is_active"] is False:
        raise HTTPException(status_code=400, detail="不能停用自己")
    for k, v in data.items():
        setattr(target, k, v)
    db.commit()
    db.refresh(target)
    return ok(_user_out(target))
