#!/usr/bin/env python3
"""生产补丁：无班组模式「部门=组」收口 — 系统角色默认权限清理。

背景：menu.teams / btn.teams.write 不再进入 DEFAULT_ROLE_PERMISSIONS
（班组 UI 由租户 enable_teams 开关控制，无班组模式彻底隐藏）。本脚本把
存量租户 manager / workshop 系统角色上遗留的这两个码清掉，保持权限矩阵一致。

只动系统角色 manager / workshop；自定义角色（管理员手动勾选过的）不动。

用法（生产机，已激活 venv、工作目录为安装根）:
  python scripts/migrate_teams_perms_cleanup.py

幂等：可重复执行；无对应行时为 no-op。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import RolePermission, Tenant
from app.services.rbac_service import ensure_system_roles

PRUNE_ROLES = ("manager", "workshop")
PRUNE_CODES = ("menu.teams", "btn.teams.write")


def main() -> int:
    db = SessionLocal()
    try:
        tenants = list(db.scalars(select(Tenant)).all())
        total = 0
        for t in tenants:
            ensure_system_roles(db, t.id)
            removed = 0
            for role in PRUNE_ROLES:
                res = db.execute(
                    delete(RolePermission).where(
                        RolePermission.tenant_id == t.id,
                        RolePermission.role == role,
                        RolePermission.perm_code.in_(PRUNE_CODES),
                    )
                )
                removed += res.rowcount or 0
            total += removed
            db.commit()
            print(f"    tenant {t.id} ({t.name}): removed {removed} row(s)")
        print(f"==> removed {total} legacy team-permission row(s) across {len(tenants)} tenant(s)")
    finally:
        db.close()

    print("==> migrate_teams_perms_cleanup done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
