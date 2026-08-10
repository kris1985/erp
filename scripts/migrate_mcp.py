#!/usr/bin/env python3
"""生产补丁：MCP 表结构 + 系统角色默认权限增量同步。

用法（生产机，已激活 venv、工作目录为安装根）:
  python scripts/migrate_mcp.py

幂等：可重复执行。admin 仍运行时拿全部权限；本脚本把 PERMISSION_TREE /
DEFAULT_ROLE_PERMISSIONS 里新增码（含 menu.mcp_keys）补进非 admin 系统角色。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.db_schema import ensure_schema
from app.models import Tenant
from app.services.rbac_service import ensure_system_roles


def main() -> int:
    print("==> ensure_schema (含 mcp_api_keys)")
    ensure_schema()

    insp_tables = set()
    with engine.connect() as conn:
        # SQLAlchemy inspect 在部分方言下更稳
        from sqlalchemy import inspect as sa_inspect

        insp_tables = set(sa_inspect(engine).get_table_names())
    if "mcp_api_keys" not in insp_tables:
        print("ERROR: mcp_api_keys 未创建", file=sys.stderr)
        return 1
    print("    table ok: mcp_api_keys")

    db = SessionLocal()
    try:
        tenants = list(db.scalars(select(Tenant)).all())
        print(f"==> sync system roles for {len(tenants)} tenant(s)")
        for t in tenants:
            ensure_system_roles(db, t.id)
            db.commit()
            print(f"    tenant {t.id} ({t.name}): roles synced")
        # 冒烟：权限树含 menu.mcp_keys
        from app.permissions import all_permission_codes

        codes = all_permission_codes()
        if "menu.mcp_keys" not in codes:
            print("ERROR: menu.mcp_keys 不在权限目录", file=sys.stderr)
            return 1
        print("    permission catalog ok: menu.mcp_keys")
    finally:
        db.close()

    print("==> migrate_mcp done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
