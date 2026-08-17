"""旧库人员迁移：users + workers → employees（合并），并重指业务外键。

背景：员工/用户合并重构后，旧 MySQL 库（workers/users 表）的数据不会自动进入新的
employees 表，导致 admin 无法登录。本脚本做一次性迁移：

1. 收集并删除所有指向旧 users/workers 表的外键约束
2. workers → employees（保留全部档案字段）
3. users → 合并进对应员工（按旧 worker_id / 手机号 / 姓名匹配），补账号字段；
   无匹配的纯后台用户（admin/manager）新建员工档案
4. user_roles → employee_roles
5. 所有引用 workers.id / users.id 的业务表外键重指到新的 employees.id
6. 重建外键约束指向 employees(id)

幂等：employees 表已有数据时跳过数据迁移（外键重指仍可重跑）。
用法：PYTHONPATH=. .venv/bin/python scripts/migrate_legacy_personnel.py
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.config import get_settings

# 指向旧表的外键（通用收集，无需硬编码；此清单仅用于列名匹配的兜底）
FK_REMAP: list[tuple[str, str, str]] = [
    ("order_process_assignments", "worker_id", "workers"),
    ("order_processes", "assigned_worker_id", "workers"),
    ("rework_tasks", "worker_id", "workers"),
    ("salary_acknowledgements", "worker_id", "workers"),
    ("schedule_draft_assignments", "worker_id", "workers"),
    ("team_members", "worker_id", "workers"),
    ("trace_unit_logs", "worker_id", "workers"),
    ("trace_units", "created_by_worker_id", "workers"),
    ("work_log_group_shares", "worker_id", "workers"),
    ("work_logs", "worker_id", "workers"),
    ("fg_ledgers", "created_by", "users"),
    ("material_iqc_records", "decided_by", "users"),
    ("material_releases", "created_by", "users"),
    ("mcp_api_keys", "created_by", "users"),
    ("merge_batches", "created_by", "users"),
    ("order_change_logs", "created_by", "users"),
    ("orders", "created_by", "users"),
    ("packing_plans", "created_by", "users"),
    ("payments", "created_by", "users"),
    ("purchase_orders", "created_by", "users"),
    ("rework_tasks", "created_by", "users"),
    ("sales_line_labor_allocations", "created_by", "users"),
    ("sales_orders", "created_by", "users"),
    ("schedule_drafts", "confirmed_by", "users"),
    ("shared_material_ledgers", "created_by", "users"),
    ("shipments", "created_by", "users"),
    ("spec_execution_orders", "created_by", "users"),
    ("stock_docs", "created_by", "users"),
    ("supplier_payments", "created_by", "users"),
    ("teams", "leader_user_id", "users"),
]

_SELECT_FKS = text(
    """
    SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME IN ('users', 'workers')
    """
)


def _cols(conn, table: str) -> set[str]:
    return {c["name"] for c in inspect(conn.engine).get_columns(table)}


def _list_fks(conn) -> list[tuple[str, str, str, str]]:
    return [
        (r[0], r[1], r[2], r[3])
        for r in conn.execute(_SELECT_FKS).all()
    ]


def migrate() -> None:
    settings = get_settings()
    eng = create_engine(settings.database_url, pool_pre_ping=True)
    insp = inspect(eng)
    tables = set(insp.get_table_names())
    if "employees" not in tables:
        print("employees 表不存在：请先启动一次应用（ensure_schema 会自动建表）再迁移。")
        return

    # ── 阶段 0（无事务，DDL）：删除指向旧表的全部外键约束 ──
    with eng.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        fks = _list_fks(conn)
        for table, col, cname, ref in fks:
            conn.execute(text(f"ALTER TABLE {table} DROP FOREIGN KEY {cname}"))
        print(f"已删除指向 users/workers 的外键约束: {len(fks)} 个")

    # ── 阶段 1（事务）：数据迁移 ──
    with eng.begin() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM employees")).scalar()
        if n:
            print(f"employees 已有 {n} 行，跳过数据迁移（外键重指仍执行）。")
            employee_rows_exist = True
        else:
            employee_rows_exist = False

        worker_map: dict[int, int] = {}
        user_map: dict[int, int] = {}

        if not employee_rows_exist and "workers" in tables:
            # 1) workers → employees
            for w in conn.execute(text("SELECT * FROM workers ORDER BY id")).mappings():
                r = conn.execute(
                    text(
                        "INSERT INTO employees (tenant_id, name, mobile, wechat_openid, wechat_unionid, "
                        "password_hash, must_change_password, position_id, salary_model, base_salary, "
                        "base_quota, skill_factor, bank_account, bank_name, bank_account_name, is_active) "
                        "VALUES (:tenant_id,:name,:mobile,:wechat_openid,:wechat_unionid,:password_hash,"
                        ":must_change_password,:position_id,:salary_model,:base_salary,:base_quota,"
                        ":skill_factor,:bank_account,:bank_name,:bank_account_name,:is_active)"
                    ),
                    {
                        "tenant_id": w["tenant_id"],
                        "name": w["name"],
                        "mobile": w.get("mobile"),
                        "wechat_openid": w.get("wechat_openid"),
                        "wechat_unionid": w.get("wechat_unionid"),
                        "password_hash": w.get("password_hash"),
                        "must_change_password": w.get("must_change_password", 1) or 1,
                        "position_id": w.get("position_id"),
                        "salary_model": w.get("salary_model") or "pure_piece",
                        "base_salary": w.get("base_salary") or 0,
                        "base_quota": w.get("base_quota") or 0,
                        "skill_factor": w.get("skill_factor") or 1.0,
                        "bank_account": w.get("bank_account"),
                        "bank_name": w.get("bank_name"),
                        "bank_account_name": w.get("bank_account_name"),
                        "is_active": w.get("is_active", 1),
                    },
                )
                worker_map[w["id"]] = r.lastrowid
            print(f"workers → employees: {len(worker_map)} 条")

            # 2) users → 合并进员工
            if "users" in tables:
                for u in conn.execute(text("SELECT * FROM users ORDER BY id")).mappings():
                    target = None
                    if u.get("worker_id") and u["worker_id"] in worker_map:
                        target = worker_map[u["worker_id"]]
                    else:
                        row = conn.execute(
                            text(
                                "SELECT id FROM employees WHERE tenant_id = :t "
                                "AND ((mobile IS NOT NULL AND mobile = :m) OR name = :n) ORDER BY id LIMIT 1"
                            ),
                            {"t": u["tenant_id"], "m": u.get("mobile"), "n": u.get("display_name") or u["username"]},
                        ).first()
                        if row:
                            target = row[0]
                    if target is None:
                        r = conn.execute(
                            text(
                                "INSERT INTO employees (tenant_id, name, username, password_hash, must_change_password, "
                                "salary_model, base_salary, base_quota, skill_factor, is_active) "
                                "VALUES (:tenant_id,:name,:username,:password_hash,0,'fixed',0,0,1.00,1)"
                            ),
                            {
                                "tenant_id": u["tenant_id"],
                                "name": u.get("display_name") or u["username"],
                                "username": u["username"],
                                "password_hash": u.get("password_hash"),
                            },
                        )
                        target = r.lastrowid
                        print(f"  纯后台用户 → 新建员工: {u['username']} (employee {target})")
                    else:
                        conn.execute(
                            text(
                                "UPDATE employees SET username = :username, "
                                "password_hash = COALESCE(password_hash, :password_hash), must_change_password = 0 "
                                "WHERE id = :id"
                            ),
                            {
                                "username": u["username"],
                                "password_hash": u.get("password_hash"),
                                "id": target,
                            },
                        )
                        print(f"  用户 {u['username']} → 合并进员工 id={target}")
                    user_map[u["id"]] = target
                print(f"users → employees: {len(user_map)} 条")

            # 3) user_roles → employee_roles
            if "user_roles" in tables:
                moved = 0
                for ur in conn.execute(text("SELECT * FROM user_roles")).mappings():
                    emp_id = user_map.get(ur["user_id"])
                    if emp_id is None:
                        continue
                    conn.execute(
                        text(
                            "INSERT INTO employee_roles (tenant_id, employee_id, role_code) "
                            "VALUES (:t, :e, :r) ON DUPLICATE KEY UPDATE role_code = role_code"
                        ),
                        {"t": ur["tenant_id"], "e": emp_id, "r": ur["role_code"]},
                    )
                    moved += 1
                print(f"user_roles → employee_roles: {moved} 条")

        # 4) 业务外键重指（幂等：按当前列内旧 id 匹配新 id）
        old_map: dict[int, int] = {}
        with eng.connect() as probe:
            if not worker_map:
                for r in probe.execute(text("SELECT id, name FROM workers")).all():
                    row = probe.execute(
                        text("SELECT id FROM employees WHERE name = :n LIMIT 1"), {"n": r[1]}
                    ).first()
                    if row:
                        old_map[int(r[0])] = row[0]
            else:
                old_map.update(worker_map)
        remapped = 0
        for table, col, src in FK_REMAP:
            if table not in tables:
                continue
            cols = _cols(conn, table)
            if col not in cols:
                continue
            rows = conn.execute(text(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL")).all()
            for rid, old_id in rows:
                new_id = old_map.get(int(old_id))
                if new_id:
                    conn.execute(
                        text(f"UPDATE {table} SET {col} = :new WHERE id = :rid"),
                        {"new": new_id, "rid": rid},
                    )
                    remapped += 1
        print(f"业务外键重指: {remapped} 条")

    # ── 阶段 2（无事务，DDL）：重建外键指向 employees(id)（幂等） ──
    with eng.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        existing = {
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME = 'employees'"
                )
            ).all()
        }
        rebuilt = 0
        for table, col, src in FK_REMAP:
            if table not in tables or col not in _cols(conn, table):
                continue
            if (table, col) in existing:
                continue
            try:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD FOREIGN KEY ({col}) REFERENCES employees (id)")
                )
                rebuilt += 1
            except Exception as e:
                print(f"  重建 {table}.{col} 失败（{type(e).__name__}: {e}），跳过")
        print(f"重建外键指向 employees: {rebuilt} 个")

    print("迁移完成。可用 admin / <原密码> 登录。")


if __name__ == "__main__":
    migrate()
