#!/usr/bin/env python3
"""
将本机 MySQL（.env DATABASE_URL）中的 ERP 表全量同步到远程（deploy.env）。

安全约束：
- 只操作 ERP 表（SQLAlchemy models ∩ 本机库表）
- 不会 DROP/TRUNCATE u8s_* / t_picture* 等无关表
- 本机通常无法直连 RDS：默认经 DEPLOY_SERVER1 SSH 隧道转发

用法:
  source .venv/bin/activate
  python scripts/sync_local_db_to_remote.py --yes
"""

from __future__ import annotations

import argparse
import atexit
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pymysql
from pymysql.connections import Connection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import Base
from app.models import *  # noqa: F401,F403


def _load_kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _parse_mysql_url(url: str) -> dict[str, Any]:
    u = urlparse(url.replace("mysql+pymysql://", "mysql://", 1))
    db = (u.path or "/").lstrip("/").split("?")[0]
    return {
        "host": u.hostname or "127.0.0.1",
        "port": u.port or 3306,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "database": db,
        "charset": "utf8mb4",
        "connect_timeout": 30,
        "autocommit": False,
    }


def _rewrite_url_host(url: str, host: str, port: int) -> str:
    return re.sub(
        r"(@)([^/:?]+)(:\d+)?(/)",
        rf"@{host}:{port}/",
        url,
        count=1,
    )


def _connect(cfg: dict[str, Any]) -> Connection:
    return pymysql.connect(**cfg)


def _try_connect(cfg: dict[str, Any]) -> bool:
    try:
        c = _connect(cfg)
        c.close()
        return True
    except Exception:
        return False


def _start_ssh_tunnel(
    dep: dict[str, str], rds_host: str, rds_port: int, local_port: int
) -> subprocess.Popen:
    ssh_host = dep.get("DEPLOY_SERVER1_HOST") or ""
    ssh_port = dep.get("DEPLOY_SERVER1_PORT") or "22"
    ssh_user = dep.get("DEPLOY_SERVER1_USER") or "root"
    if not ssh_host:
        raise SystemExit("deploy.env 缺少 DEPLOY_SERVER1_HOST，无法建立 SSH 隧道")
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-N",
        "-L",
        f"{local_port}:{rds_host}:{rds_port}",
        "-p",
        str(ssh_port),
        f"{ssh_user}@{ssh_host}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(lambda: proc.terminate() if proc.poll() is None else None)
    for _ in range(40):
        time.sleep(0.2)
        if proc.poll() is not None:
            raise SystemExit("SSH 隧道启动失败（检查密钥登录）")
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=0.5):
                return proc
        except OSError:
            continue
    proc.terminate()
    raise SystemExit("SSH 隧道端口未就绪")


def _erp_tables(local: Connection) -> list[str]:
    model_tables = set(Base.metadata.tables.keys())
    with local.cursor() as cur:
        cur.execute("SHOW TABLES")
        local_tables = {r[0] for r in cur.fetchall()}
    tables = sorted(model_tables & local_tables)
    if not tables:
        raise SystemExit("未找到可同步的 ERP 表")
    return tables


def _table_columns(conn: Connection, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        return [r[0] for r in cur.fetchall()]


def _count(conn: Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM `{table}`")
        return int(cur.fetchone()[0])


def _recreate_remote_schema(remote_url: str, tables: list[str]) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(remote_url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for t in tables:
            conn.execute(text(f"DROP TABLE IF EXISTS `{t}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    tables_meta = [Base.metadata.tables[t] for t in tables if t in Base.metadata.tables]
    Base.metadata.create_all(bind=engine, tables=tables_meta)
    engine.dispose()


def _copy_table(local: Connection, remote: Connection, table: str, chunk: int = 500) -> int:
    local_cols = _table_columns(local, table)
    remote_cols = set(_table_columns(remote, table))
    cols = [c for c in local_cols if c in remote_cols]
    if not cols:
        print(f"  skip {table}: 无共同列")
        return 0
    missing = [c for c in local_cols if c not in remote_cols]
    if missing:
        print(f"  warn {table}: 远程缺少列 {missing}（多为已废弃列），已跳过")

    col_sql = ", ".join(f"`{c}`" for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))
    insert_sql = f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders})"
    select_sql = f"SELECT {col_sql} FROM `{table}`"

    copied = 0
    with local.cursor() as lcur, remote.cursor() as rcur:
        lcur.execute(select_sql)
        while True:
            rows = lcur.fetchmany(chunk)
            if not rows:
                break
            rcur.executemany(insert_sql, rows)
            copied += len(rows)
        remote.commit()
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="本机 ERP MySQL → 远程全量覆盖同步")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过交互确认")
    parser.add_argument("--chunk", type=int, default=500)
    parser.add_argument("--tunnel-port", type=int, default=13306)
    parser.add_argument("--no-tunnel", action="store_true", help="禁止 SSH 隧道（要求本机直连 RDS）")
    args = parser.parse_args()

    local_env = _load_kv(ROOT / ".env")
    dep = _load_kv(ROOT / "deploy.env")
    local_url = local_env.get("DATABASE_URL")
    remote_url = dep.get("DATABASE_URL")
    if not local_url or local_env.get("USE_SQLITE", "").lower() in {"1", "true", "yes"}:
        raise SystemExit("本机需配置 MySQL DATABASE_URL（USE_SQLITE=false）")
    if not remote_url:
        raise SystemExit("deploy.env 缺少 DATABASE_URL")

    local_cfg = _parse_mysql_url(local_url)
    remote_cfg = _parse_mysql_url(remote_url)
    effective_remote_url = remote_url

    print("本地:", f"{local_cfg['user']}@{local_cfg['host']}/{local_cfg['database']}")
    print("远程:", f"{remote_cfg['user']}@{remote_cfg['host']}/{remote_cfg['database']}")
    print("警告: 将 DROP 远程同名 ERP 表后重建并全量插入；不会动 u8s/t_picture 等表")

    if not args.no_tunnel and not _try_connect(remote_cfg):
        print(
            f"==> 本机无法直连 RDS，经 {dep.get('DEPLOY_SERVER1_HOST')} "
            f"建立 SSH 隧道 :{args.tunnel_port}"
        )
        _start_ssh_tunnel(dep, remote_cfg["host"], remote_cfg["port"], args.tunnel_port)
        effective_remote_url = _rewrite_url_host(remote_url, "127.0.0.1", args.tunnel_port)
        remote_cfg = _parse_mysql_url(effective_remote_url)

    local = _connect(local_cfg)
    remote = _connect(remote_cfg)
    try:
        tables = _erp_tables(local)
        print(f"待同步表: {len(tables)}")
        total_local = 0
        for t in tables:
            n = _count(local, t)
            total_local += n
            if n:
                print(f"  {t}: {n}")
        print(f"本机总行数: {total_local}")

        if not args.yes:
            ans = input("确认覆盖远程 ERP 数据？输入 YES 继续: ").strip()
            if ans != "YES":
                print("已取消")
                return 1

        print("==> 重建远程 ERP 表结构")
        _recreate_remote_schema(effective_remote_url, tables)

        print("==> 关闭远程外键检查并导入")
        with remote.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            remote.commit()

        total_copied = 0
        for t in tables:
            n = _copy_table(local, remote, t, chunk=args.chunk)
            total_copied += n
            print(f"  ok {t}: {n}")

        with remote.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
            remote.commit()

        print(f"完成: 已导入 {total_copied} 行 / {len(tables)} 表")
        return 0
    finally:
        local.close()
        remote.close()


if __name__ == "__main__":
    raise SystemExit(main())
