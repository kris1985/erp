from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, verify_password
from app.db import get_db
from app.models import User
from app.schemas.api import LoginRequest, TokenData
from app.schemas.common import ok

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username, User.is_active.is_(True)))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token(user)
    data = TokenData(
        access_token=token,
        display_name=user.display_name,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        tenant_id=user.tenant_id,
    )
    return ok(data.model_dump())


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "tenant_id": user.tenant_id,
        }
    )
