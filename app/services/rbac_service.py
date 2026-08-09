"""租户角色与权限：内置职能角色自动灌库；用户可多角色（权限并集）。"""

from __future__ import annotations

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RolePermission, TenantRole, User, UserRoleAssignment
from app.permissions import (
    ROLES,
    all_permission_codes,
    default_permissions_for_role,
    permission_catalog,
    permission_tree_for_ui,
    pick_primary_role,
)


class RbacError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
# API 天花板仅两档；细权靠菜单权限
_BASE_ROLES = ("admin", "manager")
_SYSTEM_ROLE_CODES = {r["code"] for r in ROLES}
_LEGACY_LEADER = "leader"


def _valid_codes() -> set[str]:
    return set(all_permission_codes())


def ensure_system_roles(db: Session, tenant_id: int) -> None:
    """灌入内置角色及其默认权限；迁移废弃的用户·组长。"""
    for r in ROLES:
        row = db.scalar(
            select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.code == r["code"])
        )
        base = r.get("base_role") or r["code"]
        if not row:
            db.add(
                TenantRole(
                    tenant_id=tenant_id,
                    code=r["code"],
                    name=r["name"],
                    description=r.get("description"),
                    base_role=base,
                    is_system=True,
                    is_active=True,
                )
            )
            db.flush()
        else:
            row.name = r["name"]
            row.description = r.get("description")
            row.base_role = base
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
            for code in default_permissions_for_role(r["code"]):
                if code not in existing_codes:
                    db.add(RolePermission(tenant_id=tenant_id, role=r["code"], perm_code=code))

    # 废弃用户角色「组长」→ 车间主管
    leader_row = db.scalar(
        select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.code == _LEGACY_LEADER)
    )
    if leader_row and leader_row.is_active:
        leader_row.is_active = False
        leader_row.is_system = False
        leader_row.description = (leader_row.description or "") + "（已废弃，请用车间主管/员工组长）"
        leader_row.base_role = "manager"

    # 用户主角色 leader → workshop
    for u in db.scalars(
        select(User).where(User.tenant_id == tenant_id, User.role == _LEGACY_LEADER)
    ).all():
        u.role = "workshop"

    # 自定义角色天花板 leader → manager
    for row in db.scalars(
        select(TenantRole).where(
            TenantRole.tenant_id == tenant_id,
            TenantRole.base_role == _LEGACY_LEADER,
        )
    ).all():
        row.base_role = "manager"

    # 回填 user_roles（主角色）
    users = db.scalars(select(User).where(User.tenant_id == tenant_id)).all()
    for u in users:
        codes = list(
            db.scalars(
                select(UserRoleAssignment.role_code).where(UserRoleAssignment.user_id == u.id)
            ).all()
        )
        if not codes:
            primary = u.role if u.role != _LEGACY_LEADER else "workshop"
            if primary == _LEGACY_LEADER:
                primary = "workshop"
            db.add(
                UserRoleAssignment(
                    tenant_id=tenant_id,
                    user_id=u.id,
                    role_code=primary,
                )
            )
        else:
            # 把遗留 leader 赋值换成 workshop
            for c in list(codes):
                if c == _LEGACY_LEADER:
                    db.execute(
                        delete(UserRoleAssignment).where(
                            UserRoleAssignment.user_id == u.id,
                            UserRoleAssignment.role_code == _LEGACY_LEADER,
                        )
                    )
                    if "workshop" not in codes:
                        db.add(
                            UserRoleAssignment(
                                tenant_id=tenant_id,
                                user_id=u.id,
                                role_code="workshop",
                            )
                        )
                    u.role = pick_primary_role(
                        [x for x in codes if x != _LEGACY_LEADER] + (["workshop"] if "workshop" not in codes else [])
                    )

    db.commit()


def get_tenant_role(db: Session, tenant_id: int, code: str) -> TenantRole | None:
    return db.scalar(
        select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.code == code)
    )


def list_user_role_codes(db: Session, user: User) -> list[str]:
    ensure_system_roles(db, user.tenant_id)
    codes = list(
        db.scalars(
            select(UserRoleAssignment.role_code).where(UserRoleAssignment.user_id == user.id)
        ).all()
    )
    if not codes:
        primary = str(user.role) if user.role else "manager"
        if primary == _LEGACY_LEADER:
            primary = "workshop"
        return [primary]
    return [c if c != _LEGACY_LEADER else "workshop" for c in codes]


def set_user_roles(db: Session, user: User, role_codes: list[str]) -> list[str]:
    """设置用户角色列表（至少 1 个）；同步 users.role 为主角色。"""
    ensure_system_roles(db, user.tenant_id)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in role_codes or []:
        code = str(raw or "").strip()
        if not code or code in seen:
            continue
        if code == _LEGACY_LEADER:
            code = "workshop"
        assert_assignable_role(db, user.tenant_id, code)
        seen.add(code)
        cleaned.append(code)
    if not cleaned:
        raise RbacError("roles_required", "请至少选择一个角色")
    if "admin" in cleaned and len(cleaned) > 1:
        # 管理员已含全部权限，多余角色无意义但仍允许；主角色固定 admin
        pass

    db.execute(delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id))
    for code in cleaned:
        db.add(
            UserRoleAssignment(
                tenant_id=user.tenant_id,
                user_id=user.id,
                role_code=code,
            )
        )
    user.role = pick_primary_role(cleaned)
    db.flush()
    return cleaned


def effective_base_role(db: Session, tenant_id: int, role_code: str) -> str:
    """单个角色的 API 天花板。"""
    if role_code == "admin":
        return "admin"
    if role_code == _LEGACY_LEADER:
        return "manager"
    ensure_system_roles(db, tenant_id)
    row = get_tenant_role(db, tenant_id, role_code)
    if not row or not row.is_active:
        if role_code in _BASE_ROLES:
            return role_code
        if role_code in _SYSTEM_ROLE_CODES:
            return "manager"
        return "manager"
    base = row.base_role or "manager"
    if base == _LEGACY_LEADER:
        return "manager"
    return base if base in _BASE_ROLES else "manager"


def user_effective_base_role(db: Session, user: User) -> str:
    """多角色取最高天花板（有 admin 则为 admin，否则 manager）。"""
    codes = list_user_role_codes(db, user)
    bases = {effective_base_role(db, user.tenant_id, c) for c in codes}
    if "admin" in bases or "admin" in codes:
        return "admin"
    return "manager"


def get_role_permissions(db: Session, tenant_id: int, role: str) -> list[str]:
    ensure_system_roles(db, tenant_id)
    if role == _LEGACY_LEADER:
        role = "workshop"
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


def get_user_permissions(db: Session, user: User) -> list[str]:
    """多角色权限并集。"""
    codes = list_user_role_codes(db, user)
    if "admin" in codes:
        return all_permission_codes()
    merged: set[str] = set()
    for code in codes:
        try:
            merged.update(get_role_permissions(db, user.tenant_id, code))
        except RbacError:
            continue
    return sorted(merged)


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
    # 隐藏已废弃的 leader（即使 include_inactive，默认列表也不突出；include 时仍可见）
    if not include_inactive:
        rows = [r for r in rows if r.code != _LEGACY_LEADER]
    return [_serialize_role(db, tenant_id, r) for r in rows]


def create_role(
    db: Session,
    tenant_id: int,
    *,
    name: str,
    code: str | None = None,
    description: str | None = None,
    base_role: str = "manager",
    permissions: list[str] | None = None,
) -> dict:
    ensure_system_roles(db, tenant_id)
    name = (name or "").strip()
    if not name:
        raise RbacError("name_required", "请填写角色名称")
    if base_role == _LEGACY_LEADER:
        base_role = "manager"
    if base_role not in ("manager",):
        raise RbacError("invalid_base", "自定义角色接口级别仅支持「业务级」")

    raw = (code or "").strip().lower()
    auto = not raw
    if auto:
        raw = "role_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        raw = raw[:28].strip("_") or "role_custom"
        if not _CODE_RE.match(raw):
            n = db.scalar(
                select(func.count()).select_from(TenantRole).where(TenantRole.tenant_id == tenant_id)
            ) or 0
            raw = f"role_{n}"
    if not _CODE_RE.match(raw):
        raise RbacError("invalid_code", "角色编码须为小写字母开头，仅含字母数字下划线，2–31 位")
    if raw in _SYSTEM_ROLE_CODES or raw == "admin" or raw == _LEGACY_LEADER:
        raise RbacError("code_reserved", "该编码为系统保留，请换一个")

    if get_tenant_role(db, tenant_id, raw):
        if not auto:
            raise RbacError("duplicate_code", f"角色编码已存在：{raw}")
        base = raw[:24].rstrip("_")
        i = 2
        while get_tenant_role(db, tenant_id, f"{base}_{i}") or f"{base}_{i}" in _SYSTEM_ROLE_CODES:
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

    seed = permissions if permissions is not None else []
    valid = _valid_codes()
    for p in sorted({c for c in seed if c in valid}):
        db.add(RolePermission(tenant_id=tenant_id, role=raw, perm_code=p))
    db.commit()
    db.refresh(row)
    return _serialize_role(db, tenant_id, row)


def _count_users_with_role(db: Session, tenant_id: int, code: str, *, active_only: bool = False) -> int:
    q = (
        select(func.count())
        .select_from(UserRoleAssignment)
        .where(UserRoleAssignment.tenant_id == tenant_id, UserRoleAssignment.role_code == code)
    )
    via_assign = int(db.scalar(q) or 0)
    uq = select(func.count()).select_from(User).where(User.tenant_id == tenant_id, User.role == code)
    if active_only:
        uq = uq.where(User.is_active.is_(True))
    via_primary = int(db.scalar(uq) or 0)
    return max(via_assign, via_primary)


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
        if base_role == _LEGACY_LEADER:
            base_role = "manager"
        if base_role not in ("manager",):
            raise RbacError("invalid_base", "自定义角色接口级别仅支持「业务级」")
        row.base_role = base_role
    if is_active is not None:
        if row.is_system:
            raise RbacError("system_role", "系统内置角色不可停用")
        if is_active is False:
            used = _count_users_with_role(db, tenant_id, code, active_only=True)
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
    used = _count_users_with_role(db, tenant_id, code)
    if used:
        raise RbacError("role_in_use", f"仍有 {used} 个用户使用该角色，无法删除")
    db.execute(
        delete(RolePermission).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role == code,
        )
    )
    db.execute(
        delete(UserRoleAssignment).where(
            UserRoleAssignment.tenant_id == tenant_id,
            UserRoleAssignment.role_code == code,
        )
    )
    db.delete(row)
    db.commit()


def assert_assignable_role(db: Session, tenant_id: int, role: str) -> None:
    ensure_system_roles(db, tenant_id)
    if role == _LEGACY_LEADER:
        raise RbacError("invalid_role", "「组长」用户角色已废弃，请改用车间主管或员工组长")
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


def user_has_any_permission(db: Session, user: User, perm_code: str) -> bool:
    return perm_code in get_user_permissions(db, user)
