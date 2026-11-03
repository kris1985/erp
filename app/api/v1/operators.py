"""平台运营登录与租户管理。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_operator_token, get_current_operator, verify_password
from app.db import get_db
from app.models import Operator
from app.schemas.common import ok
from app.services.app_release_service import (
    AppReleaseError,
    delete_release,
    list_releases,
    save_release,
    update_release,
)
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


class AppReleaseIn(BaseModel):
    platform: str
    kind: str = "native"
    version_name: str
    version_code: int = Field(ge=1, le=2_000_000_000)
    download_url: str = ""
    notes: str | None = Field(default=None, max_length=500)
    force_update: bool = False
    is_published: bool = True
    min_native_version_code: int | None = Field(default=None, ge=1, le=2_000_000_000)


class AppReleaseUpdateIn(BaseModel):
    version_name: str
    version_code: int = Field(ge=1, le=2_000_000_000)
    download_url: str = ""
    notes: str | None = Field(default=None, max_length=500)
    force_update: bool = False
    is_published: bool = True
    is_current: bool = False
    min_native_version_code: int | None = Field(default=None, ge=1, le=2_000_000_000)


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


@router.get("/app-releases")
def api_list_app_releases(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    return ok(list_releases(db))


@router.put("/app-releases")
def api_save_app_release(
    body: AppReleaseIn,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    try:
        data = save_release(
            db,
            platform=body.platform,
            kind=body.kind,
            version_name=body.version_name,
            version_code=body.version_code,
            download_url=body.download_url,
            notes=body.notes,
            force_update=body.force_update,
            is_published=body.is_published,
            min_native_version_code=body.min_native_version_code,
        )
    except AppReleaseError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return ok(data)


def _raise_release(exc: AppReleaseError) -> None:
    status = 404 if exc.code == "not_found" else 400
    raise HTTPException(status_code=status, detail=exc.message) from exc


@router.put("/app-releases/{release_id}")
def api_update_app_release(
    release_id: int,
    body: AppReleaseUpdateIn,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    try:
        data = update_release(
            db,
            release_id,
            version_name=body.version_name,
            version_code=body.version_code,
            download_url=body.download_url,
            notes=body.notes,
            force_update=body.force_update,
            is_published=body.is_published,
            is_current=body.is_current,
            min_native_version_code=body.min_native_version_code,
        )
    except AppReleaseError as exc:
        _raise_release(exc)
    return ok(data)


@router.delete("/app-releases/{release_id}")
def api_delete_app_release(
    release_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    try:
        delete_release(db, release_id)
    except AppReleaseError as exc:
        _raise_release(exc)
    return ok({"id": release_id})


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
