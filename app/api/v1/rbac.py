"""角色 / 权限：支持新增自定义角色，并按菜单/按钮编辑授权。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.models import User
from app.permissions import permission_tree_for_ui
from app.schemas.common import ok
from app.services import rbac_service
from app.services.rbac_service import RbacError

router = APIRouter(tags=["rbac"])


class RoleCreate(BaseModel):
    name: str
    code: str | None = None
    description: str | None = None
    base_role: str = "leader"
    permissions: list[str] | None = None
    copy_from: str | None = None  # 从已有角色复制权限


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    base_role: str | None = None
    is_active: bool | None = None


class RolePermissionsUpdate(BaseModel):
    permissions: list[str] = Field(default_factory=list)


def _http(e: RbacError) -> HTTPException:
    return HTTPException(status_code=400, detail=e.message)


@router.get("/roles")
def api_list_roles(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    items = rbac_service.list_roles(db, user.tenant_id, include_inactive=include_inactive)
    return ok({"items": items, "total": len(items)})


@router.post("/roles")
def api_create_role(
    body: RoleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    """新建角色；传 copy_from 时复制该角色权限与接口级别。"""
    perms = body.permissions
    base_role = body.base_role if body.base_role in ("manager", "leader") else "leader"
    if body.copy_from:
        try:
            src = rbac_service.get_tenant_role(db, user.tenant_id, body.copy_from)
            if not src:
                raise RbacError("invalid_role", f"无效角色：{body.copy_from}")
            if perms is None:
                perms = rbac_service.get_role_permissions(db, user.tenant_id, body.copy_from)
            # 管理员不可作自定义角色的 base_role，降为主管级
            base_role = src.base_role if src.base_role in ("manager", "leader") else "manager"
        except RbacError as e:
            raise _http(e) from e
    elif perms is None:
        perms = []
    try:
        row = rbac_service.create_role(
            db,
            user.tenant_id,
            name=body.name,
            code=body.code,
            description=body.description,
            base_role=base_role,
            permissions=perms,
        )
    except RbacError as e:
        raise _http(e) from e
    return ok(row)


@router.patch("/roles/{role}")
def api_update_role(
    role: str,
    body: RoleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    data = body.model_dump(exclude_unset=True)
    try:
        row = rbac_service.update_role(db, user.tenant_id, role, **data)
    except RbacError as e:
        raise _http(e) from e
    return ok(row)


@router.delete("/roles/{role}")
def api_delete_role(
    role: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    try:
        rbac_service.delete_role(db, user.tenant_id, role)
    except RbacError as e:
        raise _http(e) from e
    return ok({"deleted": True, "code": role})


@router.get("/roles/{role}/permissions")
def api_get_role_permissions(
    role: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    try:
        codes = rbac_service.get_role_permissions(db, user.tenant_id, role)
    except RbacError as e:
        raise _http(e) from e
    return ok({"role": role, "permissions": codes, "tree": permission_tree_for_ui()})


@router.put("/roles/{role}/permissions")
def api_put_role_permissions(
    role: str,
    body: RolePermissionsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    try:
        codes = rbac_service.set_role_permissions(db, user.tenant_id, role, body.permissions)
    except RbacError as e:
        raise _http(e) from e
    return ok({"role": role, "permissions": codes})


@router.get("/permissions")
def api_list_permissions(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    return ok(rbac_service.permissions_matrix(db, user.tenant_id))


@router.get("/permissions/tree")
def api_permission_tree(user: User = Depends(require_roles("admin"))):
    return ok({"tree": permission_tree_for_ui()})
