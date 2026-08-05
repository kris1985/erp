from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    create_worker_token,
    get_current_user,
    get_current_worker,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.db import get_db
from app.models import Tenant, TenantRole, User, Worker
from app.schemas.api import (
    ChangePasswordRequest,
    LoginRequest,
    TokenData,
    WorkerChangePasswordRequest,
    WorkerLoginRequest,
)
from app.schemas.common import ok

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username, User.is_active.is_(True)))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token(user)
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    from app.services import inventory_settings, rbac_service

    try:
        permissions = rbac_service.get_role_permissions(db, user.tenant_id, role)
    except Exception:
        permissions = []
    base_role = rbac_service.effective_base_role(db, user.tenant_id, role)
    inventory = inventory_settings.get_inventory_by_tenant_id(db, user.tenant_id)
    data = TokenData(
        access_token=token,
        display_name=user.display_name,
        role=role,
        tenant_id=user.tenant_id,
    )
    return ok(
        {
            **data.model_dump(),
            "actor": "user",
            "must_change_password": False,
            "permissions": permissions,
            "base_role": base_role,
            "inventory": inventory,
        }
    )


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services import inventory_settings, rbac_service

    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    try:
        permissions = rbac_service.get_role_permissions(db, user.tenant_id, role)
    except Exception:
        permissions = []
    base_role = rbac_service.effective_base_role(db, user.tenant_id, role)
    tenant = db.get(Tenant, user.tenant_id)
    role_row = db.scalar(
        select(TenantRole).where(TenantRole.tenant_id == user.tenant_id, TenantRole.code == role)
    )
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": role,
            "role_name": role_row.name if role_row else role,
            "base_role": base_role,
            "tenant_id": user.tenant_id,
            "tenant_name": tenant.name if tenant else None,
            "actor": "user",
            "permissions": permissions,
            "inventory": inventory_settings.get_inventory_for_tenant(tenant),
        }
    )


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return ok({"message": "密码已修改"})


@router.post("/worker/login")
def worker_login(body: WorkerLoginRequest, db: Session = Depends(get_db)):
    mobile = (body.mobile or "").strip()
    if not mobile:
        raise HTTPException(status_code=400, detail="请填写手机号")
    worker = db.scalar(
        select(Worker).where(Worker.mobile == mobile, Worker.is_active.is_(True))
    )
    if not worker or not worker.password_hash:
        raise HTTPException(status_code=401, detail="手机号或密码错误")
    if not verify_password(body.password, worker.password_hash):
        raise HTTPException(status_code=401, detail="手机号或密码错误")
    token = create_worker_token(worker)
    return ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "display_name": worker.name,
            "role": worker.role.value if hasattr(worker.role, "value") else str(worker.role),
            "tenant_id": worker.tenant_id,
            "worker_id": worker.id,
            "actor": "worker",
            "must_change_password": bool(worker.must_change_password),
        }
    )


@router.get("/worker/me")
def worker_me(worker: Worker = Depends(get_current_worker), db: Session = Depends(get_db)):
    from app.models import Position

    tenant = db.get(Tenant, worker.tenant_id)
    position_name = None
    if worker.position_id:
        pos = db.get(Position, worker.position_id)
        position_name = pos.name if pos else None
    salary_model = (
        worker.salary_model.value if hasattr(worker.salary_model, "value") else str(worker.salary_model)
    )
    return ok(
        {
            "id": worker.id,
            "name": worker.name,
            "mobile": worker.mobile,
            "role": worker.role.value if hasattr(worker.role, "value") else str(worker.role),
            "position_name": position_name,
            "salary_model": salary_model,
            "tenant_id": worker.tenant_id,
            "tenant_name": tenant.name if tenant else None,
            "must_change_password": bool(worker.must_change_password),
            "actor": "worker",
        }
    )


@router.post("/worker/change-password")
def worker_change_password(
    body: WorkerChangePasswordRequest,
    db: Session = Depends(get_db),
    worker: Worker = Depends(get_current_worker),
):
    if not worker.password_hash or not verify_password(body.old_password, worker.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    settings = get_settings()
    if body.new_password == settings.worker_default_password:
        raise HTTPException(status_code=400, detail="新密码不能与默认密码相同")
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    worker.password_hash = hash_password(body.new_password)
    worker.must_change_password = False
    db.commit()
    return ok({"message": "密码已修改", "must_change_password": False})
