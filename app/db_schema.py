"""Ensure DB columns/tables exist for iterative MVP schema adds (MySQL/SQLite)."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Base, engine
import app.models  # noqa: F401 — 注册元数据


def _add_column(conn, table: str, ddl: str) -> None:
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_schema() -> None:
    # 新建表（含 order_process_assignments）
    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    dialect = engine.dialect.name

    with engine.begin() as conn:
        if "order_processes" in tables:
            cols = {c["name"] for c in insp.get_columns("order_processes")}
            if "assigned_worker_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_processes", "assigned_worker_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_processes ADD COLUMN assigned_worker_id INT NULL, "
                            "ADD INDEX ix_order_processes_assigned_worker_id (assigned_worker_id)"
                        )
                    )

        if "workers" in tables:
            cols = {c["name"] for c in insp.get_columns("workers")}
            if "password_hash" not in cols:
                _add_column(conn, "workers", "password_hash VARCHAR(255) NULL")
            if "must_change_password" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "workers", "must_change_password BOOLEAN DEFAULT 1")
                else:
                    _add_column(
                        conn,
                        "workers",
                        "must_change_password TINYINT(1) NOT NULL DEFAULT 1",
                    )
            if "position_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "workers", "position_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE workers ADD COLUMN position_id INT NULL, "
                            "ADD INDEX ix_workers_position_id (position_id)"
                        )
                    )

        assignment_tables = set(inspect(engine).get_table_names())
        if "order_process_assignments" in assignment_tables:
            cols = {c["name"] for c in insp.get_columns("order_process_assignments")}
            # insp may be stale after create_all; re-check
            cols = {c["name"] for c in inspect(engine).get_columns("order_process_assignments")}
            if "quota_qty" not in cols:
                _add_column(conn, "order_process_assignments", "quota_qty INTEGER NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("order_process_assignments")}
            if "color_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_process_assignments", "color_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_process_assignments ADD COLUMN color_id INT NULL, "
                            "ADD INDEX ix_opa_color_id (color_id)"
                        )
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("order_process_assignments")}
            if "size_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_process_assignments", "size_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_process_assignments ADD COLUMN size_id INT NULL, "
                            "ADD INDEX ix_opa_size_id (size_id)"
                        )
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("order_process_assignments")}
            if "trace_unit_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_process_assignments", "trace_unit_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_process_assignments ADD COLUMN trace_unit_id INT NULL, "
                            "ADD INDEX ix_opa_trace_unit_id (trace_unit_id)"
                        )
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("order_process_assignments")}
            if "share_weight" not in cols:
                _add_column(conn, "order_process_assignments", "share_weight INTEGER NULL")
            # 旧唯一键 → 支持同人多色码/多捆行
            for old_idx in (
                "uq_order_process_worker",
                "uq_opa_process_worker_sku",
            ):
                try:
                    if dialect == "sqlite":
                        conn.execute(text(f"DROP INDEX IF EXISTS {old_idx}"))
                    else:
                        conn.execute(
                            text(f"ALTER TABLE order_process_assignments DROP INDEX {old_idx}")
                        )
                except Exception:
                    pass
            try:
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS uq_opa_process_worker_scope "
                            "ON order_process_assignments "
                            "(order_process_id, worker_id, color_id, size_id, trace_unit_id)"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_process_assignments "
                            "ADD UNIQUE INDEX uq_opa_process_worker_scope "
                            "(order_process_id, worker_id, color_id, size_id, trace_unit_id)"
                        )
                    )
            except Exception:
                pass

        # 把旧的单人派工迁移到多人表（仅当 assignments 为空且旧字段有值）
        if "order_processes" in tables and "order_process_assignments" in assignment_tables:
            conn.execute(
                text(
                    """
                    INSERT INTO order_process_assignments
                        (tenant_id, order_id, order_process_id, worker_id)
                    SELECT op.tenant_id, op.order_id, op.id, op.assigned_worker_id
                    FROM order_processes op
                    WHERE op.assigned_worker_id IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM order_process_assignments a
                        WHERE a.order_process_id = op.id AND a.worker_id = op.assigned_worker_id
                      )
                    """
                )
            )

        # styles: 遗留表字段（新库不再创建 styles；旧库保留兼容）
        if "styles" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("styles")}
            if "category" not in cols:
                _add_column(conn, "styles", "category VARCHAR(50) NULL")
            if "brand_partner_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "styles", "brand_partner_id INTEGER NULL")
                else:
                    _add_column(conn, "styles", "brand_partner_id INT NULL")
            if "notes" not in cols:
                _add_column(conn, "styles", "notes TEXT NULL")

        # orders: 客户档案
        if "orders" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "customer_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "orders", "customer_id INTEGER NULL")
                else:
                    _add_column(conn, "orders", "customer_id INT NULL")

        # supplier_products: 分类/单位改为外键
        tables = set(inspect(engine).get_table_names())
        if "supplier_products" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("supplier_products")}
            if "name" not in cols:
                _add_column(conn, "supplier_products", "name VARCHAR(100) NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("supplier_products")}
            if "category_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "supplier_products", "category_id INTEGER NULL")
                else:
                    _add_column(conn, "supplier_products", "category_id INT NULL")
            if "pricing_unit_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "supplier_products", "pricing_unit_id INTEGER NULL")
                else:
                    _add_column(conn, "supplier_products", "pricing_unit_id INT NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("supplier_products")}
            if "unit_price" not in cols:
                _add_column(conn, "supplier_products", "unit_price DECIMAL(12,4) NULL")
            # 旧字符串字段迁移到主数据
            cols = {c["name"] for c in inspect(engine).get_columns("supplier_products")}
            if "category" in cols and "material_categories" in tables:
                conn.execute(
                    text(
                        """
                        INSERT INTO material_categories (tenant_id, name, sort_order, is_active)
                        SELECT DISTINCT sp.tenant_id, sp.category, 0, 1
                        FROM supplier_products sp
                        WHERE sp.category IS NOT NULL AND sp.category != ''
                          AND NOT EXISTS (
                            SELECT 1 FROM material_categories mc
                            WHERE mc.tenant_id = sp.tenant_id AND mc.name = sp.category
                          )
                        """
                    )
                )
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            """
                            UPDATE supplier_products
                            SET category_id = (
                              SELECT mc.id FROM material_categories mc
                              WHERE mc.tenant_id = supplier_products.tenant_id
                                AND mc.name = supplier_products.category
                            )
                            WHERE category IS NOT NULL AND category != '' AND category_id IS NULL
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            UPDATE supplier_products sp
                            INNER JOIN material_categories mc
                              ON mc.tenant_id = sp.tenant_id AND mc.name = sp.category
                            SET sp.category_id = mc.id
                            WHERE sp.category IS NOT NULL AND sp.category != ''
                              AND sp.category_id IS NULL
                            """
                        )
                    )
            if "pricing_unit" in cols and "pricing_units" in tables:
                conn.execute(
                    text(
                        """
                        INSERT INTO pricing_units (tenant_id, name, sort_order, is_active)
                        SELECT DISTINCT sp.tenant_id, sp.pricing_unit, 0, 1
                        FROM supplier_products sp
                        WHERE sp.pricing_unit IS NOT NULL AND sp.pricing_unit != ''
                          AND NOT EXISTS (
                            SELECT 1 FROM pricing_units pu
                            WHERE pu.tenant_id = sp.tenant_id AND pu.name = sp.pricing_unit
                          )
                        """
                    )
                )
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            """
                            UPDATE supplier_products
                            SET pricing_unit_id = (
                              SELECT pu.id FROM pricing_units pu
                              WHERE pu.tenant_id = supplier_products.tenant_id
                                AND pu.name = supplier_products.pricing_unit
                            )
                            WHERE pricing_unit IS NOT NULL AND pricing_unit != '' AND pricing_unit_id IS NULL
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            UPDATE supplier_products sp
                            INNER JOIN pricing_units pu
                              ON pu.tenant_id = sp.tenant_id AND pu.name = sp.pricing_unit
                            SET sp.pricing_unit_id = pu.id
                            WHERE sp.pricing_unit IS NOT NULL AND sp.pricing_unit != ''
                              AND sp.pricing_unit_id IS NULL
                            """
                        )
                    )

        # own_products: 报价与成本字段
        tables = set(inspect(engine).get_table_names())
        if "own_products" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("own_products")}
            if "material_cost" not in cols:
                _add_column(conn, "own_products", "material_cost DECIMAL(14,4) NULL")
                if "total_price" in cols:
                    conn.execute(
                        text("UPDATE own_products SET material_cost = COALESCE(total_price, 0)")
                    )
                conn.execute(text("UPDATE own_products SET material_cost = 0 WHERE material_cost IS NULL"))
            cols = {c["name"] for c in inspect(engine).get_columns("own_products")}
            if "quote_price" not in cols:
                _add_column(conn, "own_products", "quote_price DECIMAL(14,4) NULL")
            if "labor_cost" not in cols:
                _add_column(conn, "own_products", "labor_cost DECIMAL(14,4) NULL DEFAULT 0")
            if "other_cost" not in cols:
                _add_column(conn, "own_products", "other_cost DECIMAL(14,4) NULL DEFAULT 0")
            cols = {c["name"] for c in inspect(engine).get_columns("own_products")}
            if "trace_enabled" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "own_products", "trace_enabled BOOLEAN DEFAULT 0")
                else:
                    _add_column(
                        conn,
                        "own_products",
                        "trace_enabled TINYINT(1) NOT NULL DEFAULT 0",
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("own_products")}
            if "order_qty" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "own_products", "order_qty INTEGER DEFAULT 0")
                else:
                    _add_column(conn, "own_products", "order_qty INT NULL DEFAULT 0")
                conn.execute(text("UPDATE own_products SET order_qty = 0 WHERE order_qty IS NULL"))
            cols = {c["name"] for c in inspect(engine).get_columns("own_products")}
            if "total_price" in cols:
                try:
                    conn.execute(text("ALTER TABLE own_products DROP COLUMN total_price"))
                except Exception:
                    # SQLite 旧版本或不支持时：至少填默认值，避免 NOT NULL 插入失败
                    conn.execute(
                        text(
                            "UPDATE own_products SET total_price = COALESCE(material_cost, 0)"
                            " + COALESCE(labor_cost, 0) + COALESCE(other_cost, 0)"
                            " WHERE total_price IS NULL"
                        )
                    )

        # own_product_labors: 自定义工序名
        tables = set(inspect(engine).get_table_names())
        if "own_product_labors" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("own_product_labors")}
            if "process_name" not in cols:
                _add_column(conn, "own_product_labors", "process_name VARCHAR(50) NULL")
                if "process_definitions" in tables:
                    if dialect == "sqlite":
                        conn.execute(
                            text(
                                """
                                UPDATE own_product_labors
                                SET process_name = (
                                  SELECT pd.name FROM process_definitions pd
                                  WHERE pd.id = own_product_labors.process_id
                                )
                                WHERE process_name IS NULL OR process_name = ''
                                """
                            )
                        )
                    else:
                        conn.execute(
                            text(
                                """
                                UPDATE own_product_labors opl
                                LEFT JOIN process_definitions pd ON pd.id = opl.process_id
                                SET opl.process_name = COALESCE(pd.name, '')
                                WHERE opl.process_name IS NULL OR opl.process_name = ''
                                """
                            )
                        )
                conn.execute(
                    text("UPDATE own_product_labors SET process_name = '' WHERE process_name IS NULL")
                )
            # process_id 允许为空（自定义工序以名称为主）
            cols = {c["name"] for c in inspect(engine).get_columns("own_product_labors")}
            if "process_id" in cols and dialect != "sqlite":
                try:
                    conn.execute(text("ALTER TABLE own_product_labors MODIFY process_id INT NULL"))
                except Exception:
                    pass

        # own_product_other_costs: 多项其它成本；回填旧 other_cost
        tables = set(inspect(engine).get_table_names())
        if "own_product_other_costs" in tables and "own_products" in tables:
            conn.execute(
                text(
                    """
                    INSERT INTO own_product_other_costs
                        (tenant_id, own_product_id, name, amount, sort_order)
                    SELECT p.tenant_id, p.id, '其它', p.other_cost, 0
                    FROM own_products p
                    WHERE COALESCE(p.other_cost, 0) > 0
                      AND NOT EXISTS (
                        SELECT 1 FROM own_product_other_costs o
                        WHERE o.own_product_id = p.id
                      )
                    """
                )
            )

        # orders / work_logs: style_id → own_product_id
        tables = set(inspect(engine).get_table_names())
        if "orders" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "own_product_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "orders", "own_product_id INTEGER NULL")
                else:
                    _add_column(conn, "orders", "own_product_id INT NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "own_product_id" in cols and "style_id" in cols and "styles" in tables and "own_products" in tables:
                # 按款号=产品编号回填；无匹配则用该租户第一个产品
                conn.execute(
                    text(
                        """
                        UPDATE orders
                        SET own_product_id = (
                            SELECT op.id FROM own_products op
                            JOIN styles s ON s.style_code = op.product_code
                              AND s.tenant_id = op.tenant_id
                            WHERE s.id = orders.style_id
                            LIMIT 1
                        )
                        WHERE own_product_id IS NULL AND style_id IS NOT NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE orders
                        SET own_product_id = (
                            SELECT op.id FROM own_products op
                            WHERE op.tenant_id = orders.tenant_id
                            ORDER BY op.id
                            LIMIT 1
                        )
                        WHERE own_product_id IS NULL
                        """
                    )
                )
            if dialect != "sqlite":
                try:
                    conn.execute(text("ALTER TABLE orders MODIFY own_product_id INT NOT NULL"))
                except Exception:
                    pass
                try:
                    conn.execute(text("ALTER TABLE orders MODIFY style_id INT NULL"))
                except Exception:
                    pass

        tables = set(inspect(engine).get_table_names())
        if "work_logs" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("work_logs")}
            if "own_product_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "work_logs", "own_product_id INTEGER NULL")
                else:
                    _add_column(conn, "work_logs", "own_product_id INT NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("work_logs")}
            if "trace_unit_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "work_logs", "trace_unit_id INTEGER NULL")
                else:
                    _add_column(conn, "work_logs", "trace_unit_id INT NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("work_logs")}
            if "own_product_id" in cols and "orders" in tables:
                conn.execute(
                    text(
                        """
                        UPDATE work_logs
                        SET own_product_id = (
                            SELECT o.own_product_id FROM orders o WHERE o.id = work_logs.order_id
                        )
                        WHERE own_product_id IS NULL
                        """
                    )
                )
            if dialect != "sqlite":
                try:
                    conn.execute(text("ALTER TABLE work_logs MODIFY own_product_id INT NOT NULL"))
                except Exception:
                    pass
                try:
                    conn.execute(text("ALTER TABLE work_logs MODIFY style_id INT NULL"))
                except Exception:
                    pass

        # 备料交付：订单售价 / 色码已出货 / 急单
        tables = set(inspect(engine).get_table_names())
        if "orders" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "unit_price" not in cols:
                _add_column(conn, "orders", "unit_price DECIMAL(14,4) NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "other_cost_amount" not in cols:
                _add_column(conn, "orders", "other_cost_amount DECIMAL(14,4) NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "is_rush" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "orders", "is_rush BOOLEAN DEFAULT 0")
                else:
                    _add_column(conn, "orders", "is_rush TINYINT(1) NOT NULL DEFAULT 0")
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "rush_reason" not in cols:
                _add_column(conn, "orders", "rush_reason VARCHAR(255) NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "rushed_at" not in cols:
                _add_column(conn, "orders", "rushed_at DATETIME NULL")
        if "order_items" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("order_items")}
            if "shipped_qty" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_items", "shipped_qty INTEGER DEFAULT 0")
                else:
                    _add_column(conn, "order_items", "shipped_qty INT NOT NULL DEFAULT 0")

        tables = set(inspect(engine).get_table_names())
        if "purchase_orders" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("purchase_orders")}
            if "ordered_at" not in cols:
                _add_column(conn, "purchase_orders", "ordered_at DATETIME NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("purchase_orders")}
            if "public_token" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "purchase_orders", "public_token VARCHAR(40)")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE purchase_orders ADD COLUMN public_token VARCHAR(40) NULL, "
                            "ADD UNIQUE INDEX uq_purchase_orders_public_token (public_token)"
                        )
                    )
            # 历史已下单单据：用创建时间回填下单时间
            conn.execute(
                text(
                    """
                    UPDATE purchase_orders
                    SET ordered_at = created_at
                    WHERE ordered_at IS NULL
                      AND status NOT IN ('draft', 'cancelled')
                    """
                )
            )

        # 工人银行卡
        tables = set(inspect(engine).get_table_names())
        if "workers" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("workers")}
            if "bank_account" not in cols:
                _add_column(conn, "workers", "bank_account VARCHAR(40) NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("workers")}
            if "bank_name" not in cols:
                _add_column(conn, "workers", "bank_name VARCHAR(100) NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("workers")}
            if "bank_account_name" not in cols:
                _add_column(conn, "workers", "bank_account_name VARCHAR(50) NULL")

        # 租户配置（库存模式等）
        tables = set(inspect(engine).get_table_names())
        if "tenants" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("tenants")}
            if "settings_json" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "tenants", "settings_json TEXT NULL")
                else:
                    _add_column(conn, "tenants", "settings_json JSON NULL")

        # 报工锁价 + 月结锁账表
        tables = set(inspect(engine).get_table_names())
        if "work_logs" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("work_logs")}
            if "unit_price" not in cols:
                _add_column(conn, "work_logs", "unit_price DECIMAL(14,4) NULL")
            # 旧报工按产品工序现价回填一次（之后改价不再动已锁价行）
            cols = {c["name"] for c in inspect(engine).get_columns("work_logs")}
            if "unit_price" in cols and "own_product_labors" in tables:
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            """
                            UPDATE work_logs
                            SET unit_price = (
                              SELECT opl.unit_price FROM own_product_labors opl
                              WHERE opl.own_product_id = work_logs.own_product_id
                                AND opl.process_id = work_logs.process_id
                              LIMIT 1
                            )
                            WHERE unit_price IS NULL
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            UPDATE work_logs wl
                            INNER JOIN own_product_labors opl
                              ON opl.own_product_id = wl.own_product_id
                             AND opl.process_id = wl.process_id
                            SET wl.unit_price = opl.unit_price
                            WHERE wl.unit_price IS NULL
                            """
                        )
                    )

