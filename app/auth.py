from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User, Worker

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user: User) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "role": user.role.value if hasattr(user.role, "value") else user.role,
        "typ": "user",
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_worker_token(worker: Worker) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(worker.id),
        "tenant_id": worker.tenant_id,
        "role": worker.role.value if hasattr(worker.role, "value") else str(worker.role),
        "typ": "worker",
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def _decode(creds: Optional[HTTPAuthorizationCredentials]) -> dict:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    settings = get_settings()
    try:
        return jwt.decode(creds.credentials, settings.secret_key, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    payload = _decode(creds)
    if payload.get("typ", "user") != "user":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请使用后台账号登录")
    try:
        user_id = int(payload.get("sub", 0))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    return user


def get_current_worker(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Worker:
    payload = _decode(creds)
    if payload.get("typ") != "worker":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请使用员工账号登录")
    try:
        worker_id = int(payload.get("sub", 0))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")
    worker = db.get(Worker, worker_id)
    if not worker or not worker.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="员工不可用")
    return worker


class Principal:
    def __init__(self, *, kind: str, tenant_id: int, user: User | None = None, worker: Worker | None = None):
        self.kind = kind
        self.tenant_id = tenant_id
        self.user = user
        self.worker = worker


def get_principal(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Principal:
    """后台用户或员工均可。"""
    payload = _decode(creds)
    typ = payload.get("typ", "user")
    try:
        sub = int(payload.get("sub", 0))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")
    if typ == "worker":
        worker = db.get(Worker, sub)
        if not worker or not worker.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="员工不可用")
        return Principal(kind="worker", tenant_id=worker.tenant_id, worker=worker)
    user = db.get(User, sub)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    return Principal(kind="user", tenant_id=user.tenant_id, user=user)


def require_roles(*roles: str):
    """依赖：有效基础角色须在 roles 内（admin 始终放行）。

    自定义角色按 tenant_roles.base_role 参与判断，从而兼容现有接口鉴权。
    """

    def _dep(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        from app.services.rbac_service import effective_base_role

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        base = effective_base_role(db, user.tenant_id, role)
        if base == "admin" or role == "admin" or base in roles or role in roles:
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

    return _dep