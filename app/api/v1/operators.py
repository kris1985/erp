"""平台运营登录与租户管理。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_operator_token, get_current_operator, verify_password
from app.db import get_db
from app.models import Operator
from app.schemas.common import ok
from app.services.operator_service import (
    OperatorError,
    create_tenant,
    delete_tenant,
    ensure_default_operator,
    list_tenants,
    reset_tenant_admin_password,
    update_tenant,
)

router = APIRouter(prefix="/operators", tags=["operators"])


class OperatorLoginIn(BaseModel):
    username: str
    password: str


class TenantWriteIn(BaseModel):
    name: str
    admin_name: str | None = None
    admin_mobile: str
    password: str | None = None
    expires_on: str | None = None
    notes: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class ResetPasswordIn(BaseModel):
    password: str


def _raise(exc: OperatorError) -> None:
    code = 404 if exc.code == "not_found" else 400
    raise HTTPException(status_code=code, detail=exc.message) from exc


@router.post("/login")
def operator_login(body: OperatorLoginIn, db: Session = Depends(get_db)):
    ensure_default_operator(db)
    username = (body.username or "").strip()
    operator = db.scalar(select(Operator).where(Operator.username == username))
    password_ok = False
    if operator and operator.is_active and operator.password_hash:
        try:
            password_ok = verify_password(body.password or "", operator.password_hash)
        except Exception:
            password_ok = False
    if not password_ok:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return ok(
        {
            "access_token": create_operator_token(operator.id),
            "token_type": "bearer",
            "id": operator.id,
            "name": operator.name,
            "username": operator.username,
        }
    )


@router.get("/me")
def operator_me(operator: Operator = Depends(get_current_operator)):
    return ok({"id": operator.id, "name": operator.name, "username": operator.username})


@router.get("/tenants")
def api_list_tenants(
    keyword: str | None = None,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    return ok(list_tenants(db, keyword=keyword))


@router.post("/tenants")
def api_create_tenant(
    body: TenantWriteIn,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    if not body.password:
        raise HTTPException(status_code=400, detail="请设置管理员初始密码")
    try:
        data = create_tenant(
            db,
            name=body.name,
            admin_name=body.admin_name,
            admin_mobile=body.admin_mobile,
            password=body.password,
            expires_on=body.expires_on,
            notes=body.notes,
            is_active=body.is_active,
        )
    except OperatorError as exc:
        _raise(exc)
    return ok(data)


@router.put("/tenants/{tenant_id}")
def api_update_tenant(
    tenant_id: int,
    body: TenantWriteIn,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    try:
        data = update_tenant(
            db,
            tenant_id,
            name=body.name,
            admin_name=body.admin_name,
            admin_mobile=body.admin_mobile,
            password=body.password,
            expires_on=body.expires_on,
            notes=body.notes,
            is_active=body.is_active,
        )
    except OperatorError as exc:
        _raise(exc)
    return ok(data)


@router.post("/tenants/{tenant_id}/reset-password")
def api_reset_password(
    tenant_id: int,
    body: ResetPasswordIn,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    try:
        reset_tenant_admin_password(db, tenant_id, body.password)
    except OperatorError as exc:
        _raise(exc)
    return ok({"id": tenant_id})


@router.delete("/tenants/{tenant_id}")
def api_delete_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    try:
        delete_tenant(db, tenant_id)
    except OperatorError as exc:
        _raise(exc)
    return ok({"id": tenant_id})
