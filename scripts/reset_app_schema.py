"""上线清库：只删除本系统的表，然后按当前模型重建空表。

不要 DROP DATABASE，也不要靠 alembic upgrade。
alembic/versions/0001 是空操作，0002–0015 只补过早期几列；
当前结构以模型 + 启动时的 ensure_schema() 为准，它只建缺表、补缺列，不会动其它应用的表。

本系统旧表（代码已不再使用，但外键还指向 tenants 等）：
users、workers、user_roles、sole_molds、sole_mold_entries。
它们是空的人员合并 / 底模遗留，一并删除，否则删不掉 tenants。

用法（先看清单，确认库名后再执行）：
  PYTHONPATH=. .venv/bin/python scripts/reset_app_schema.py
  PYTHONPATH=. .venv/bin/python scripts/reset_app_schema.py --yes

其它应用的表会原样保留。若那些表有外键指向本系统的表，脚本会停下，不删除。
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import bindparam, inspect, text

import app.models  # noqa: F401
from app.config import get_settings
from app.db import Base, engine
from app.db_schema import ensure_schema

# 模型里已经没有、但属于本系统、并且外键挂在本系统表上的遗留表。
LEGACY_TABLES = (
    "users",
    "workers",
    "user_roles",
    "sole_molds",
    "sole_mold_entries",
)

# 不在模型里，由运行时 CREATE TABLE IF NOT EXISTS 自建。清库时若存在也删掉。
RUNTIME_TABLES = (
    "agent_run_traces",
    "analysis_results",
    "analysis_calculations",
    "conversations",
    "alembic_version",
)


def app_tables() -> set[str]:
    return set(Base.metadata.tables) | set(LEGACY_TABLES) | set(RUNTIME_TABLES)


def main() -> int:
    parser = argparse.ArgumentParser(description="只清空并重建本系统的表")
    parser.add_argument("--yes", action="store_true", help="确认执行删除和重建")
    args = parser.parse_args()

    settings = get_settings()
    safe_url = settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url
    owned = app_tables()
    live = set(inspect(engine).get_table_names())
    drop_names = sorted(live & owned)
    keep_names = sorted(live - owned)

    print(f"数据库: {safe_url}")
    print(f"将删除并重建（本系统，{len(drop_names)} 张）:")
    for name in drop_names:
        print(f"  - {name}")
    print(f"保留不动（{len(keep_names)} 张）:")
    for name in keep_names:
        print(f"  - {name}")

    if keep_names and drop_names:
        with engine.connect() as conn:
            blocked = conn.execute(
                text(
                    """
                    SELECT TABLE_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND REFERENCED_TABLE_NAME IS NOT NULL
                      AND TABLE_NAME IN :keep_names
                      AND REFERENCED_TABLE_NAME IN :drop_names
                    """
                ).bindparams(
                    bindparam("keep_names", expanding=True),
                    bindparam("drop_names", expanding=True),
                ),
                {"keep_names": keep_names, "drop_names": drop_names},
            ).all()
        if blocked:
            print("已停止：下面这些非本系统的表外键指向即将删除的表，删表会把它们弄断。")
            for row in blocked:
                print(f"  {row[0]}.{row[1]} -> {row[2]}")
            return 1

    if not args.yes:
        print("这是预览。确认库名无误后加 --yes 才会删除并重建。")
        return 0

    if not drop_names:
        print("没有本系统的表需要删除，直接补齐结构。")
    else:
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for name in drop_names:
                conn.execute(text(f"DROP TABLE IF EXISTS `{name}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        print(f"已删除 {len(drop_names)} 张本系统的表。")

    ensure_schema()
    print("已按当前模型重建空表。不要跑 seed_demo。运营账号在首次打开 /ops/login 时创建。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
