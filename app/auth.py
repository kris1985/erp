from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Employee

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(employee: Employee) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(employee.id),
        "tenant_id": employee.tenant_id,
        "typ": "employee",
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


# 兼容别名（合并前遗留的命名）
create_worker_token = create_access_token


def _decode(creds: Optional[HTTPAuthorizationCredentials]) -> dict:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    settings = get_settings()
    try:
        return jwt.decode(creds.credentials, settings.secret_key, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")


def _load_employee(db: Session, payload: dict) -> Employee:
    try:
        employee_id = int(payload.get("sub", 0))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")
    employee = db.get(Employee, employee_id)
    if not employee or not employee.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="员工不可用")
    return employee


def get_current_employee(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Employee:
    payload = _decode(creds)
    if payload.get("typ", "employee") != "employee":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请使用员工账号登录")
    return _load_employee(db, payload)


# 兼容别名：合并后员工即唯一登录主体
get_current_user = get_current_employee
get_current_worker = get_current_employee


class Principal:
    """单一登录主体：员工（含生产与后台属性）。

    is_staff = 纯生产员工（无任何后台角色）：只能访问自己的报工/数据。
    """

    def __init__(self, *, tenant_id: int, employee: Employee, is_staff: bool = False):
        self.tenant_id = tenant_id
        self.employee = employee
        self.kind = "employee"
        self.is_staff = is_staff


def get_principal(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Principal:
    """后台员工或生产员工均可（合并后唯一主体）。"""
    from app.services import rbac_service

    payload = _decode(creds)
    employee = _load_employee(db, payload)
    is_staff = not rbac_service.list_employee_role_codes(db, employee)
    return Principal(tenant_id=employee.tenant_id, employee=employee, is_staff=is_staff)


def require_roles(*roles: str):
    """依赖：员工任一角色的有效基础角色在 roles 内（admin 始终放行）。

    自定义/职能角色的 base_role 多为 manager；遗留 leader 按 manager 处理。
    """

    def _dep(
        employee: Employee = Depends(get_current_employee),
        db: Session = Depends(get_db),
    ) -> Employee:
        from app.services import rbac_service

        codes = rbac_service.list_employee_role_codes(db, employee)
        if "admin" in codes:
            return employee
        base = rbac_service.employee_effective_base_role(db, employee)
        if base == "admin" or base in roles:
            return employee
        for code in codes:
            if code in roles:
                return employee
            if rbac_service.effective_base_role(db, employee.tenant_id, code) in roles:
                return employee
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

    return _dep
