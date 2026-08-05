"""租户角色与权限：内置角色自动灌库，支持新增自定义角色。"""

from __future__ import annotations

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RolePermission, TenantRole, User
from app.permissions import (
    ROLES,
    all_permission_codes,
    default_permissions_for_role,
    permission_catalog,
    permission_tree_for_ui,
)


class RbacError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_BASE_ROLES = ("admin", "manager", "leader")


def _valid_codes() -> set[str]:
    return set(all_permission_codes())


def _role_code(user_or_role) -> str:
    if hasattr(user_or_role, "role"):
        r = user_or_role.role
        return r.value if hasattr(r, "value") else str(r)
    return str(user_or_role)


def ensure_system_roles(db: Session, tenant_id: int) -> None:
    """灌入内置角色及其默认权限。"""
    for r in ROLES:
        row = db.scalar(
            select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.code == r["code"])
        )
        if not row:
            db.add(
                TenantRole(
                    tenant_id=tenant_id,
                    code=r["code"],
                    name=r["name"],
                    description=r.get("description"),
                    base_role=r["code"],
                    is_system=True,
                    is_active=True,
                )
            )
            db.flush()
        else:
            # 保持内置角色元数据同步
            row.name = r["name"]
            row.description = r.get("description")
            row.base_role = r["code"]
            row.is_system = True
            row.is_active = True

        if r["code"] == "admin":
            continue
        existing_codes = set(
            db.scalars(
                select(RolePermission.perm_code).where(
                    RolePermission.tenant_id == tenant_id,
                    RolePermission.role == r["code"],
                )
            ).all()
        )
        if not existing_codes:
            for code in default_permissions_for_role(r["code"]):
                db.add(RolePermission(tenant_id=tenant_id, role=r["code"], perm_code=code))
        else:
            # 补齐后续新增的默认权限（不删租户已改权限）
            for code in default_permissions_for_role(r["code"]):
                if code not in existing_codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=r["code"], perm_code=code))
    db.commit()


def get_tenant_role(db: Session, tenant_id: int, code: str) -> TenantRole | None:
    return db.scalar(
        select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.code == code)
    )


def effective_base_role(db: Session, tenant_id: int, role_code: str) -> str:
    """API require_roles 用的有效角色（自定义角色回落到 base_role）。"""
    if role_code == "admin":
        return "admin"
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, role_code)
    if not row or not row.is_active:
        # 未登记的旧数据：若本身是内置编码则沿用
        if role_code in _BASE_ROLES:
            return role_code
        return "leader"
    base = row.base_role or "leader"
    return base if base in _BASE_ROLES else "leader"


def get_role_permissions(db: Session, tenant_id: int, role: str) -> list[str]:
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, role)
    if not row:
        if role == "admin":
            return all_permission_codes()
        raise RbacError("invalid_role", f"无效角色：{role}")
    if not row.is_active:
        raise RbacError("role_inactive", f"角色已停用：{role}")
    if row.base_role == "admin" or row.code == "admin":
        return all_permission_codes()
    rows = db.scalars(
        select(RolePermission.perm_code).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role == role,
        )
    ).all()
    valid = _valid_codes()
    return sorted(c for c in rows if c in valid)


def set_role_permissions(db: Session, tenant_id: int, role: str, codes: list[str]) -> list[str]:
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, role)
    if not row:
        raise RbacError("invalid_role", f"无效角色：{role}")
    if row.code == "admin" or row.base_role == "admin":
        raise RbacError("role_locked", "管理员权限固定为全部，不可编辑")
    if not row.is_active:
        raise RbacError("role_inactive", "已停用角色不可编辑权限")
    valid = _valid_codes()
    cleaned = sorted({c for c in codes if c in valid})
    db.execute(
        delete(RolePermission).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role == role,
        )
    )
    for code in cleaned:
        db.add(RolePermission(tenant_id=tenant_id, role=role, perm_code=code))
    db.commit()
    return cleaned


def _serialize_role(db: Session, tenant_id: int, row: TenantRole) -> dict:
    try:
        perms = get_role_permissions(db, tenant_id, row.code)
    except RbacError:
        perms = []
    editable = row.code != "admin" and row.base_role != "admin"
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "base_role": row.base_role,
        "is_system": bool(row.is_system),
        "is_active": bool(row.is_active),
        "editable": editable,
        "permission_count": len(perms),
        "permissions": perms,
    }


def list_roles(db: Session, tenant_id: int, *, include_inactive: bool = False) -> list[dict]:
    ensure_system_roles(db, tenant_id)
    q = select(TenantRole).where(TenantRole.tenant_id == tenant_id)
    if not include_inactive:
        q = q.where(TenantRole.is_active.is_(True))
    rows = db.scalars(q.order_by(TenantRole.is_system.desc(), TenantRole.id)).all()
    return [_serialize_role(db, tenant_id, r) for r in rows]


def create_role(
    db: Session,
    tenant_id: int,
    *,
    name: str,
    code: str | None = None,
    description: str | None = None,
    base_role: str = "leader",
    permissions: list[str] | None = None,
) -> dict:
    ensure_system_roles(db, tenant_id)
    name = (name or "").strip()
    if not name:
        raise RbacError("name_required", "请填写角色名称")
    if base_role not in ("manager", "leader"):
        raise RbacError("invalid_base", "基础角色只能是主管或组长（不可选管理员）")

    raw = (code or "").strip().lower()
    auto = not raw
    if auto:
        # 从名称生成简易编码（中文名会落到 role_N）
        raw = "role_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        raw = raw[:28].strip("_") or "role_custom"
        if not _CODE_RE.match(raw):
            n = db.scalar(
                select(func.count()).select_from(TenantRole).where(TenantRole.tenant_id == tenant_id)
            ) or 0
            raw = f"role_{n}"
    if not _CODE_RE.match(raw):
        raise RbacError("invalid_code", "角色编码须为小写字母开头，仅含字母数字下划线，2–31 位")
    if raw in _BASE_ROLES or raw == "admin":
        raise RbacError("code_reserved", "该编码为系统保留，请换一个")

    if get_tenant_role(db, tenant_id, raw):
        if not auto:
            raise RbacError("duplicate_code", f"角色编码已存在：{raw}")
        # 自动编码冲突时追加序号
        base = raw[:24].rstrip("_")
        i = 2
        while get_tenant_role(db, tenant_id, f"{base}_{i}") or f"{base}_{i}" in _BASE_ROLES:
            i += 1
            if i > 9999:
                raise RbacError("duplicate_code", "无法生成唯一角色编码")
        raw = f"{base}_{i}"

    row = TenantRole(
        tenant_id=tenant_id,
        code=raw,
        name=name,
        description=(description or "").strip() or None,
        base_role=base_role,
        is_system=False,
        is_active=True,
    )
    db.add(row)
    db.flush()

    seed = permissions if permissions is not None else default_permissions_for_role(base_role)
    valid = _valid_codes()
    for p in sorted({c for c in seed if c in valid}):
        db.add(RolePermission(tenant_id=tenant_id, role=raw, perm_code=p))
    db.commit()
    db.refresh(row)
    return _serialize_role(db, tenant_id, row)


def update_role(
    db: Session,
    tenant_id: int,
    code: str,
    *,
    name: str | None = None,
    description: str | None = None,
    base_role: str | None = None,
    is_active: bool | None = None,
) -> dict:
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, code)
    if not row:
        raise RbacError("invalid_role", f"无效角色：{code}")
    if row.is_system and is_active is False:
        raise RbacError("system_role", "系统内置角色不可停用")
    if name is not None:
        name = name.strip()
        if not name:
            raise RbacError("name_required", "请填写角色名称")
        row.name = name
    if description is not None:
        row.description = description.strip() or None
    if base_role is not None:
        if row.is_system:
            raise RbacError("system_role", "系统内置角色不可改基础角色")
        if base_role not in ("manager", "leader"):
            raise RbacError("invalid_base", "基础角色只能是主管或组长")
        row.base_role = base_role
    if is_active is not None:
        if row.is_system:
            raise RbacError("system_role", "系统内置角色不可停用")
        if is_active is False:
            used = db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.tenant_id == tenant_id, User.role == code, User.is_active.is_(True))
            ) or 0
            if used:
                raise RbacError("role_in_use", f"仍有 {used} 个启用用户使用该角色，无法停用")
        row.is_active = is_active
    db.commit()
    db.refresh(row)
    return _serialize_role(db, tenant_id, row)


def delete_role(db: Session, tenant_id: int, code: str) -> None:
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, code)
    if not row:
        raise RbacError("invalid_role", f"无效角色：{code}")
    if row.is_system:
        raise RbacError("system_role", "系统内置角色不可删除")
    used = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.tenant_id == tenant_id, User.role == code)
    ) or 0
    if used:
        raise RbacError("role_in_use", f"仍有 {used} 个用户使用该角色，无法删除")
    db.execute(
        delete(RolePermission).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role == code,
        )
    )
    db.delete(row)
    db.commit()


def assert_assignable_role(db: Session, tenant_id: int, role: str) -> None:
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, role)
    if not row or not row.is_active:
        raise RbacError("invalid_role", f"无效或已停用角色：{role}")


def permissions_matrix(db: Session, tenant_id: int) -> dict:
    roles = list_roles(db, tenant_id)
    role_list = [{"code": r["code"], "name": r["name"]} for r in roles]
    granted_map = {r["code"]: set(r["permissions"]) for r in roles}
    items = []
    for p in permission_catalog():
        items.append(
            {
                "code": p["code"],
                "name": p["name"],
                "module": p["module"],
                "kind": p["kind"],
                "roles": {rc: (p["code"] in granted_map.get(rc, set())) for rc in granted_map},
            }
        )
    return {"roles": role_list, "items": items, "tree": permission_tree_for_ui()}


def user_has_permission(db: Session, tenant_id: int, role: str, perm_code: str) -> bool:
    try:
        perms = get_role_permissions(db, tenant_id, role)
    except RbacError:
        return False
    return perm_code in perms
