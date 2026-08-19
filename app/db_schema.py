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

        if "employees" in tables:
            cols = {c["name"] for c in insp.get_columns("employees")}
            if "password_hash" not in cols:
                _add_column(conn, "employees", "password_hash VARCHAR(255) NULL")
            if "must_change_password" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "employees", "must_change_password BOOLEAN DEFAULT 1")
                else:
                    _add_column(
                        conn,
                        "employees",
                        "must_change_password TINYINT(1) NOT NULL DEFAULT 1",
                    )
            if "position_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "employees", "position_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE employees ADD COLUMN position_id INT NULL, "
                            "ADD INDEX ix_employees_position_id (position_id)"
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
            cols = {c["name"] for c in inspect(engine).get_columns("supplier_products")}
            if "min_stock_qty" not in cols:
                _add_column(conn, "supplier_products", "min_stock_qty DECIMAL(14,4) NULL")
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
            cols = {c["name"] for c in inspect(engine).get_columns("own_products")}
            if "fabric" not in cols:
                _add_column(conn, "own_products", "fabric VARCHAR(100) NULL")
            if "lining" not in cols:
                _add_column(conn, "own_products", "lining VARCHAR(100) NULL")

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
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "sales_order_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "orders", "sales_order_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE orders ADD COLUMN sales_order_id INT NULL, "
                            "ADD INDEX ix_orders_sales_order_id (sales_order_id)"
                        )
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "sales_order_line_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "orders", "sales_order_line_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE orders ADD COLUMN sales_order_line_id INT NULL, "
                            "ADD INDEX ix_orders_sales_order_line_id (sales_order_line_id)"
                        )
                    )
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
        if "employees" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("employees")}
            if "bank_account" not in cols:
                _add_column(conn, "employees", "bank_account VARCHAR(40) NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("employees")}
            if "bank_name" not in cols:
                _add_column(conn, "employees", "bank_name VARCHAR(100) NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("employees")}
            if "bank_account_name" not in cols:
                _add_column(conn, "employees", "bank_account_name VARCHAR(50) NULL")

        # 租户配置（库存模式等）
        tables = set(inspect(engine).get_table_names())
        if "tenants" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("tenants")}
            if "settings_json" not in cols:
                # MySQL 5.6 无 JSON 类型，统一 TEXT
                _add_column(conn, "tenants", "settings_json TEXT NULL")

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

        tables = set(inspect(engine).get_table_names())
        if "sales_order_lines" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("sales_order_lines")}
            if "color_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "sales_order_lines", "color_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE sales_order_lines ADD COLUMN color_id INT NULL, "
                            "ADD INDEX ix_sales_order_lines_color_id (color_id)"
                        )
                    )
                if "sales_order_line_items" in tables:
                    if dialect == "sqlite":
                        conn.execute(
                            text(
                                """
                                UPDATE sales_order_lines
                                SET color_id = (
                                    SELECT color_id FROM sales_order_line_items
                                    WHERE sales_order_line_items.sales_order_line_id = sales_order_lines.id
                                      AND color_id IS NOT NULL
                                    LIMIT 1
                                )
                                WHERE color_id IS NULL
                                """
                            )
                        )
                    else:
                        conn.execute(
                            text(
                                """
                                UPDATE sales_order_lines sl
                                INNER JOIN (
                                    SELECT sales_order_line_id, MIN(color_id) AS color_id
                                    FROM sales_order_line_items
                                    WHERE color_id IS NOT NULL
                                    GROUP BY sales_order_line_id
                                ) si ON si.sales_order_line_id = sl.id
                                SET sl.color_id = si.color_id
                                WHERE sl.color_id IS NULL
                                """
                            )
                        )
            if "notes" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "sales_order_lines", "notes TEXT NULL")
                else:
                    conn.execute(text("ALTER TABLE sales_order_lines ADD COLUMN notes TEXT NULL"))
                if "sales_orders" in tables:
                    so_cols = {c["name"] for c in inspect(engine).get_columns("sales_orders")}
                    if "notes" in so_cols:
                        if dialect == "sqlite":
                            conn.execute(
                                text(
                                    """
                                    UPDATE sales_order_lines
                                    SET notes = (
                                        SELECT so.notes FROM sales_orders so
                                        WHERE so.id = sales_order_lines.sales_order_id
                                          AND so.notes IS NOT NULL AND so.notes != ''
                                    )
                                    WHERE notes IS NULL
                                      AND sort_order = 0
                                    """
                                )
                            )
                        else:
                            conn.execute(
                                text(
                                    """
                                    UPDATE sales_order_lines sl
                                    INNER JOIN sales_orders so ON so.id = sl.sales_order_id
                                    SET sl.notes = so.notes
                                    WHERE sl.sort_order = 0
                                      AND sl.notes IS NULL
                                      AND so.notes IS NOT NULL AND so.notes != ''
                                    """
                                )
                            )
            if "fabric" not in cols:
                _add_column(conn, "sales_order_lines", "fabric VARCHAR(100) NULL")
            if "lining" not in cols:
                _add_column(conn, "sales_order_lines", "lining VARCHAR(100) NULL")

        if "sales_orders" in tables:
            so_cols = {c["name"] for c in inspect(engine).get_columns("sales_orders")}
            if "brand_logo_url" not in so_cols:
                _add_column(conn, "sales_orders", "brand_logo_url VARCHAR(255) NULL")
            if "notes_image_url" not in so_cols:
                _add_column(conn, "sales_orders", "notes_image_url VARCHAR(255) NULL")

        if "sizes" in tables:
            size_cols = {c["name"] for c in inspect(engine).get_columns("sizes")}
            if "is_active" not in size_cols:
                if dialect == "sqlite":
                    _add_column(conn, "sizes", "is_active BOOLEAN DEFAULT 1")
                else:
                    _add_column(conn, "sizes", "is_active TINYINT(1) NOT NULL DEFAULT 1")

        # 工序用料归属：分类默认 → BOM 覆盖 → 订单快照
        if "material_categories" in tables:
            cols = {c["name"] for c in insp.get_columns("material_categories")}
            if "default_consume_process_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "material_categories", "default_consume_process_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE material_categories "
                            "ADD COLUMN default_consume_process_id INT NULL, "
                            "ADD INDEX ix_material_categories_default_consume_process_id "
                            "(default_consume_process_id)"
                        )
                    )
        if "own_product_materials" in tables:
            cols = {c["name"] for c in insp.get_columns("own_product_materials")}
            if "consume_process_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "own_product_materials", "consume_process_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE own_product_materials "
                            "ADD COLUMN consume_process_id INT NULL, "
                            "ADD INDEX ix_own_product_materials_consume_process_id (consume_process_id)"
                        )
                    )
        if "order_material_requirements" in tables:
            cols = {c["name"] for c in insp.get_columns("order_material_requirements")}
            if "consume_process_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_material_requirements", "consume_process_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_material_requirements "
                            "ADD COLUMN consume_process_id INT NULL, "
                            "ADD INDEX ix_order_material_requirements_consume_process_id "
                            "(consume_process_id)"
                        )
                    )
            if "consume_process_name" not in cols:
                _add_column(conn, "order_material_requirements", "consume_process_name VARCHAR(50) NULL")

        if "orders" in tables:
            cols = {c["name"] for c in insp.get_columns("orders")}
            if "schedule_status" not in cols:
                _add_column(
                    conn,
                    "orders",
                    "schedule_status VARCHAR(20) NOT NULL DEFAULT 'none'",
                )

        if "process_definitions" in tables:
            cols = {c["name"] for c in insp.get_columns("process_definitions")}
            if "default_days" not in cols:
                _add_column(
                    conn,
                    "process_definitions",
                    "default_days INTEGER NOT NULL DEFAULT 1",
                )

        # 工序工艺定额：单人日产能 + 标准人力；废弃 default_days（排产改按产能算天数）
        tables = set(inspect(engine).get_table_names())
        if "process_definitions" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("process_definitions")}
            if "per_worker_capacity" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "process_definitions", "per_worker_capacity NUMERIC(10,2)")
                else:
                    _add_column(conn, "process_definitions", "per_worker_capacity DECIMAL(10,2) NULL")
            if "standard_workers" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "process_definitions", "standard_workers INTEGER DEFAULT 1")
                else:
                    _add_column(conn, "process_definitions", "standard_workers INT NULL DEFAULT 1")
            if "current_workers" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "process_definitions", "current_workers INTEGER")
                else:
                    _add_column(conn, "process_definitions", "current_workers INT NULL")
            if "default_days" in cols:
                try:
                    conn.execute(text("ALTER TABLE process_definitions DROP COLUMN default_days"))
                except Exception:
                    pass

        # 员工/人员主档：合并 users+employees 后的新增列（部门、登录账号、外部组织预留）
        tables = set(inspect(engine).get_table_names())
        if "employees" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("employees")}
            for col, ddl_sqlite, ddl_mysql in (
                ("username", "username VARCHAR(50)", "username VARCHAR(50) NULL"),
                ("department_id", "department_id INTEGER", "department_id INT NULL"),
                ("ext_source", "ext_source VARCHAR(16)", "ext_source VARCHAR(16) NULL"),
                ("ext_user_id", "ext_user_id VARCHAR(100)", "ext_user_id VARCHAR(100) NULL"),
            ):
                if col not in cols:
                    if dialect == "sqlite":
                        _add_column(conn, "employees", ddl_sqlite)
                    else:
                        _add_column(conn, "employees", ddl_mysql)

        # 生产角色废弃：employees 移除 role 列（组长身份改由班组 leader 表达）
        tables = set(inspect(engine).get_table_names())
        if "employees" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("employees")}
            if "role" in cols:
                try:
                    conn.execute(text("ALTER TABLE employees DROP COLUMN role"))
                except Exception:
                    pass

        # 班组挂生产组织：部门（单产线）/ 产线（多产线开关开启）
        tables = set(inspect(engine).get_table_names())
        if "teams" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("teams")}
            if "department_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "teams", "department_id INTEGER")
                else:
                    _add_column(conn, "teams", "department_id INT NULL")
            if "production_line_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "teams", "production_line_id INTEGER")
                else:
                    _add_column(conn, "teams", "production_line_id INT NULL")

        # 部门表：主管 / 上级 / 外部组织预留
        tables = set(inspect(engine).get_table_names())
        if "departments" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("departments")}
            for col, ddl_sqlite, ddl_mysql in (
                ("parent_id", "parent_id INTEGER", "parent_id INT NULL"),
                ("manager_employee_id", "manager_employee_id INTEGER", "manager_employee_id INT NULL"),
                ("ext_source", "ext_source VARCHAR(16)", "ext_source VARCHAR(16) NULL"),
                ("ext_dept_id", "ext_dept_id VARCHAR(100)", "ext_dept_id VARCHAR(100) NULL"),
            ):
                if col not in cols:
                    if dialect == "sqlite":
                        _add_column(conn, "departments", ddl_sqlite)
                    else:
                        _add_column(conn, "departments", ddl_mysql)

        # 账期：供应商默认 / 采购单覆盖 / 应付到期日
        tables = set(inspect(engine).get_table_names())
        if "partners" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("partners")}
            if "payment_term_days" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "partners", "payment_term_days INTEGER NOT NULL DEFAULT 0")
                else:
                    _add_column(
                        conn,
                        "partners",
                        "payment_term_days INT NOT NULL DEFAULT 0",
                    )
        if "purchase_orders" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("purchase_orders")}
            if "payment_term_days" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "purchase_orders", "payment_term_days INTEGER NULL")
                else:
                    _add_column(conn, "purchase_orders", "payment_term_days INT NULL")
        if "payables" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("payables")}
            if "payment_term_days" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "payables", "payment_term_days INTEGER NOT NULL DEFAULT 0")
                else:
                    _add_column(conn, "payables", "payment_term_days INT NOT NULL DEFAULT 0")
            cols = {c["name"] for c in inspect(engine).get_columns("payables")}
            if "due_date" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "payables", "due_date DATE")
                else:
                    _add_column(conn, "payables", "due_date DATE NULL")
                # 回填：无到期日则按挂账日（现结）
                conn.execute(
                    text(
                        "UPDATE payables SET due_date = payable_date "
                        "WHERE due_date IS NULL"
                    )
                )

        # B1c：按码用量 BOM / 需求 / 采购 / 池
        tables = set(inspect(engine).get_table_names())
        if "own_product_materials" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("own_product_materials")}
            if "usage_by_size" not in cols:
                if dialect == "sqlite":
                    _add_column(
                        conn, "own_product_materials", "usage_by_size BOOLEAN DEFAULT 0"
                    )
                else:
                    _add_column(
                        conn,
                        "own_product_materials",
                        "usage_by_size TINYINT(1) NOT NULL DEFAULT 0",
                    )
            if "size_usage_table_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "own_product_materials", "size_usage_table_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE own_product_materials "
                            "ADD COLUMN size_usage_table_id INT NULL, "
                            "ADD INDEX ix_own_product_materials_size_usage_table_id "
                            "(size_usage_table_id)"
                        )
                    )
        if "order_material_requirements" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("order_material_requirements")}
            if "usage_by_size" not in cols:
                if dialect == "sqlite":
                    _add_column(
                        conn,
                        "order_material_requirements",
                        "usage_by_size BOOLEAN DEFAULT 0",
                    )
                else:
                    _add_column(
                        conn,
                        "order_material_requirements",
                        "usage_by_size TINYINT(1) NOT NULL DEFAULT 0",
                    )
            if "size_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_material_requirements", "size_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_material_requirements "
                            "ADD COLUMN size_id INT NULL, "
                            "ADD INDEX ix_order_material_requirements_size_id (size_id)"
                        )
                    )
            if "size_coeff" not in cols:
                if dialect == "sqlite":
                    _add_column(
                        conn,
                        "order_material_requirements",
                        "size_coeff NUMERIC(12,4) DEFAULT 1",
                    )
                else:
                    _add_column(
                        conn,
                        "order_material_requirements",
                        "size_coeff DECIMAL(12,4) NOT NULL DEFAULT 1",
                    )
        if "purchase_order_lines" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("purchase_order_lines")}
            if "size_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "purchase_order_lines", "size_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE purchase_order_lines "
                            "ADD COLUMN size_id INT NULL, "
                            "ADD INDEX ix_purchase_order_lines_size_id (size_id)"
                        )
                    )
            if "sales_order_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "purchase_order_lines", "sales_order_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE purchase_order_lines "
                            "ADD COLUMN sales_order_id INT NULL, "
                            "ADD INDEX ix_purchase_order_lines_sales_order_id (sales_order_id)"
                        )
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("purchase_order_lines")}
            if "sales_order_line_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "purchase_order_lines", "sales_order_line_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE purchase_order_lines "
                            "ADD COLUMN sales_order_line_id INT NULL, "
                            "ADD INDEX ix_purchase_order_lines_sales_order_line_id (sales_order_line_id)"
                        )
                    )
        if "shared_material_stocks" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("shared_material_stocks")}
            if "size_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "shared_material_stocks", "size_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE shared_material_stocks "
                            "ADD COLUMN size_id INT NULL, "
                            "ADD INDEX ix_shared_material_stocks_size_id (size_id)"
                        )
                    )
            # 唯一键：旧 (tenant, sp) → (tenant, sp, size_id)；SQLite 难改约束，依赖 create_all 新库
            if dialect != "sqlite":
                idxs = {i["name"] for i in inspect(engine).get_indexes("shared_material_stocks")}
                # MySQL unique 也可能在 unique_constraints
                uqs = {
                    u["name"]
                    for u in inspect(engine).get_unique_constraints("shared_material_stocks")
                }
                if "uq_shared_material_stock" in (idxs | uqs):
                    try:
                        conn.execute(text("ALTER TABLE shared_material_stocks DROP INDEX uq_shared_material_stock"))
                    except Exception:
                        pass
                if "uq_shared_material_stock_size" not in (idxs | uqs):
                    try:
                        conn.execute(
                            text(
                                "ALTER TABLE shared_material_stocks "
                                "ADD UNIQUE KEY uq_shared_material_stock_size "
                                "(tenant_id, supplier_product_id, size_id)"
                            )
                        )
                    except Exception:
                        pass
        if "shared_material_ledgers" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("shared_material_ledgers")}
            if "size_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "shared_material_ledgers", "size_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE shared_material_ledgers "
                            "ADD COLUMN size_id INT NULL, "
                            "ADD INDEX ix_shared_material_ledgers_size_id (size_id)"
                        )
                    )

        # B1c：分类建议按码 + 默认码表
        tables = set(inspect(engine).get_table_names())
        if "material_categories" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("material_categories")}
            if "suggest_usage_by_size" not in cols:
                if dialect == "sqlite":
                    _add_column(
                        conn,
                        "material_categories",
                        "suggest_usage_by_size BOOLEAN DEFAULT 0",
                    )
                else:
                    _add_column(
                        conn,
                        "material_categories",
                        "suggest_usage_by_size TINYINT(1) NOT NULL DEFAULT 0",
                    )
            if "default_size_usage_table_id" not in cols:
                if dialect == "sqlite":
                    _add_column(
                        conn, "material_categories", "default_size_usage_table_id INTEGER"
                    )
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE material_categories "
                            "ADD COLUMN default_size_usage_table_id INT NULL, "
                            "ADD INDEX ix_material_categories_default_size_usage_table_id "
                            "(default_size_usage_table_id)"
                        )
                    )

        # 计划损耗：BOM / 用料 % + 固定量
        tables = set(inspect(engine).get_table_names())
        if "own_product_materials" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("own_product_materials")}
            if "loss_rate" not in cols:
                if dialect == "sqlite":
                    _add_column(
                        conn,
                        "own_product_materials",
                        "loss_rate NUMERIC(8,4) DEFAULT 0",
                    )
                else:
                    _add_column(
                        conn,
                        "own_product_materials",
                        "loss_rate DECIMAL(8,4) NOT NULL DEFAULT 0",
                    )
            if "loss_fixed_qty" not in cols:
                if dialect == "sqlite":
                    _add_column(
                        conn,
                        "own_product_materials",
                        "loss_fixed_qty NUMERIC(14,4) DEFAULT 0",
                    )
                else:
                    _add_column(
                        conn,
                        "own_product_materials",
                        "loss_fixed_qty DECIMAL(14,4) NOT NULL DEFAULT 0",
                    )
            if "color_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "own_product_materials", "color_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE own_product_materials "
                            "ADD COLUMN color_id INT NULL, "
                            "ADD INDEX ix_own_product_materials_color_id (color_id)"
                        )
                    )
        if "order_material_requirements" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("order_material_requirements")}
            if "loss_fixed_qty" not in cols:
                if dialect == "sqlite":
                    _add_column(
                        conn,
                        "order_material_requirements",
                        "loss_fixed_qty NUMERIC(14,4) DEFAULT 0",
                    )
                else:
                    _add_column(
                        conn,
                        "order_material_requirements",
                        "loss_fixed_qty DECIMAL(14,4) NOT NULL DEFAULT 0",
                    )
            # B1a 客供催办字段
            if "customer_chase_status" not in cols:
                _add_column(
                    conn,
                    "order_material_requirements",
                    "customer_chase_status VARCHAR(20) NOT NULL DEFAULT 'open'",
                )
            if "customer_chase_note" not in cols:
                _add_column(
                    conn, "order_material_requirements", "customer_chase_note VARCHAR(255) NULL"
                )
            if "customer_chased_at" not in cols:
                _add_column(
                    conn, "order_material_requirements", "customer_chased_at DATETIME NULL"
                )

        # 出货/应收：冗余销售单号，供客户对账（执行仍认生产单 order_id）
        tables = set(inspect(engine).get_table_names())
        for table in ("shipments", "receivables"):
            if table not in tables:
                continue
            cols = {c["name"] for c in inspect(engine).get_columns(table)}
            if "sales_order_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, table, "sales_order_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD COLUMN sales_order_id INT NULL, "
                            f"ADD INDEX ix_{table}_sales_order_id (sales_order_id)"
                        )
                    )
            cols = {c["name"] for c in inspect(engine).get_columns(table)}
            if "sales_order_no" not in cols:
                _add_column(conn, table, "sales_order_no VARCHAR(50) NULL")

        # 出货改挂销售：order_id 可空；明细挂销售色码
        if "shipments" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("shipments")}
            order_col = next(
                (c for c in inspect(engine).get_columns("shipments") if c["name"] == "order_id"),
                None,
            )
            if dialect != "sqlite" and order_col is not None and order_col.get("nullable") is False:
                conn.execute(text("ALTER TABLE shipments MODIFY COLUMN order_id INT NULL"))
        if "receivables" in tables:
            order_col = next(
                (c for c in inspect(engine).get_columns("receivables") if c["name"] == "order_id"),
                None,
            )
            if dialect != "sqlite" and order_col is not None and order_col.get("nullable") is False:
                conn.execute(text("ALTER TABLE receivables MODIFY COLUMN order_id INT NULL"))
        if "shipment_lines" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("shipment_lines")}
            if "sales_order_line_item_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "shipment_lines", "sales_order_line_item_id INTEGER NULL")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE shipment_lines ADD COLUMN sales_order_line_item_id INT NULL, "
                            "ADD INDEX ix_shipment_lines_sales_order_line_item_id (sales_order_line_item_id)"
                        )
                    )
            order_item_col = next(
                (
                    c
                    for c in inspect(engine).get_columns("shipment_lines")
                    if c["name"] == "order_item_id"
                ),
                None,
            )
            if (
                dialect != "sqlite"
                and order_item_col is not None
                and order_item_col.get("nullable") is False
            ):
                conn.execute(text("ALTER TABLE shipment_lines MODIFY COLUMN order_item_id INT NULL"))

        if "shipments" in tables and "orders" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("shipments")}
            if "sales_order_id" in cols and "sales_order_no" in cols:
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            """
                            UPDATE shipments
                            SET sales_order_id = (
                              SELECT o.sales_order_id FROM orders o
                              WHERE o.id = shipments.order_id
                            )
                            WHERE sales_order_id IS NULL
                            """
                        )
                    )
                    conn.execute(
                        text(
                            """
                            UPDATE shipments
                            SET sales_order_no = (
                              SELECT so.order_no FROM sales_orders so
                              WHERE so.id = shipments.sales_order_id
                            )
                            WHERE sales_order_no IS NULL AND sales_order_id IS NOT NULL
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            UPDATE shipments sh
                            INNER JOIN orders o ON o.id = sh.order_id
                            LEFT JOIN sales_orders so ON so.id = o.sales_order_id
                            SET sh.sales_order_id = o.sales_order_id,
                                sh.sales_order_no = so.order_no
                            WHERE sh.sales_order_id IS NULL
                              AND o.sales_order_id IS NOT NULL
                            """
                        )
                    )
                    # 已有 id 缺单号快照时补齐
                    conn.execute(
                        text(
                            """
                            UPDATE shipments sh
                            INNER JOIN sales_orders so ON so.id = sh.sales_order_id
                            SET sh.sales_order_no = so.order_no
                            WHERE sh.sales_order_no IS NULL
                              AND sh.sales_order_id IS NOT NULL
                            """
                        )
                    )

        if "receivables" in tables and "orders" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("receivables")}
            if "sales_order_id" in cols and "sales_order_no" in cols:
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            """
                            UPDATE receivables
                            SET sales_order_id = (
                              SELECT o.sales_order_id FROM orders o
                              WHERE o.id = receivables.order_id
                            )
                            WHERE sales_order_id IS NULL
                            """
                        )
                    )
                    conn.execute(
                        text(
                            """
                            UPDATE receivables
                            SET sales_order_no = (
                              SELECT so.order_no FROM sales_orders so
                              WHERE so.id = receivables.sales_order_id
                            )
                            WHERE sales_order_no IS NULL AND sales_order_id IS NOT NULL
                            """
                        )
                    )
                    # 优先用出货单已冗余字段（与出货确认时口径一致）
                    conn.execute(
                        text(
                            """
                            UPDATE receivables
                            SET sales_order_id = (
                              SELECT sh.sales_order_id FROM shipments sh
                              WHERE sh.id = receivables.shipment_id
                            ),
                            sales_order_no = (
                              SELECT sh.sales_order_no FROM shipments sh
                              WHERE sh.id = receivables.shipment_id
                            )
                            WHERE shipment_id IS NOT NULL
                              AND sales_order_id IS NULL
                              AND EXISTS (
                                SELECT 1 FROM shipments sh
                                WHERE sh.id = receivables.shipment_id
                                  AND sh.sales_order_id IS NOT NULL
                              )
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            UPDATE receivables ar
                            INNER JOIN shipments sh ON sh.id = ar.shipment_id
                            SET ar.sales_order_id = sh.sales_order_id,
                                ar.sales_order_no = sh.sales_order_no
                            WHERE ar.sales_order_id IS NULL
                              AND sh.sales_order_id IS NOT NULL
                            """
                        )
                    )
                    conn.execute(
                        text(
                            """
                            UPDATE receivables ar
                            INNER JOIN orders o ON o.id = ar.order_id
                            LEFT JOIN sales_orders so ON so.id = o.sales_order_id
                            SET ar.sales_order_id = o.sales_order_id,
                                ar.sales_order_no = so.order_no
                            WHERE ar.sales_order_id IS NULL
                              AND o.sales_order_id IS NOT NULL
                            """
                        )
                    )
                    conn.execute(
                        text(
                            """
                            UPDATE receivables ar
                            INNER JOIN sales_orders so ON so.id = ar.sales_order_id
                            SET ar.sales_order_no = so.order_no
                            WHERE ar.sales_order_no IS NULL
                              AND ar.sales_order_id IS NOT NULL
                            """
                        )
                    )

        # AU-I0：部件路线 / 筐捆 / 技能系数 / 组拆分
        tables = set(inspect(engine).get_table_names())
        if "employees" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("employees")}
            if "skill_factor" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "employees", "skill_factor NUMERIC(5, 2) DEFAULT 1.00")
                else:
                    _add_column(
                        conn,
                        "employees",
                        "skill_factor DECIMAL(5,2) NOT NULL DEFAULT 1.00",
                    )

        if "own_product_labors" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("own_product_labors")}
            if "part_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "own_product_labors", "part_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE own_product_labors ADD COLUMN part_id INT NULL, "
                            "ADD INDEX ix_own_product_labors_part_id (part_id)"
                        )
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("own_product_labors")}
            if "is_kit_checkpoint" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "own_product_labors", "is_kit_checkpoint BOOLEAN DEFAULT 0")
                else:
                    _add_column(
                        conn,
                        "own_product_labors",
                        "is_kit_checkpoint TINYINT(1) NOT NULL DEFAULT 0",
                    )

        if "order_processes" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("order_processes")}
            if "part_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_processes", "part_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_processes ADD COLUMN part_id INT NULL, "
                            "ADD INDEX ix_order_processes_part_id (part_id)"
                        )
                    )
            # A'档排产依据快照（确认下发时写入，供已排单追溯）
            if "capacity_source" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_processes", "capacity_source VARCHAR(20)")
                else:
                    _add_column(conn, "order_processes", "capacity_source VARCHAR(20) NULL")
            if "capacity_active_workers" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_processes", "capacity_active_workers INTEGER")
                else:
                    _add_column(conn, "order_processes", "capacity_active_workers INT NULL")
            if "capacity_avg_per_head" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_processes", "capacity_avg_per_head NUMERIC(10,2)")
                else:
                    _add_column(conn, "order_processes", "capacity_avg_per_head DECIMAL(10,2) NULL")
            if "capacity_efficiency" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_processes", "capacity_efficiency NUMERIC(5,2)")
                else:
                    _add_column(conn, "order_processes", "capacity_efficiency DECIMAL(5,2) NULL")

        if "trace_units" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("trace_units")}
            if "part_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "trace_units", "part_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE trace_units ADD COLUMN part_id INT NULL, "
                            "ADD INDEX ix_trace_units_part_id (part_id)"
                        )
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("trace_units")}
            if "received_at" not in cols:
                _add_column(conn, "trace_units", "received_at DATETIME NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("trace_units")}
            if "received_by_worker_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "trace_units", "received_by_worker_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE trace_units ADD COLUMN received_by_worker_id INT NULL, "
                            "ADD INDEX ix_trace_units_received_by_worker_id (received_by_worker_id)"
                        )
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("trace_units")}
            if "sales_order_id" not in cols:
                # AU-I1 合单分筐：开裁按销售订单拆独立筐，打 sales_order_id 戳
                if dialect == "sqlite":
                    _add_column(conn, "trace_units", "sales_order_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE trace_units ADD COLUMN sales_order_id INT NULL, "
                            "ADD INDEX ix_trace_units_sales_order_id (sales_order_id)"
                        )
                    )

        # AU-I1：合单分配 / 执行单桥接
        tables = set(inspect(engine).get_table_names())
        if "sales_order_line_items" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("sales_order_line_items")}
            if "allocated_qty" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "sales_order_line_items", "allocated_qty INTEGER DEFAULT 0")
                else:
                    _add_column(
                        conn,
                        "sales_order_line_items",
                        "allocated_qty INT NOT NULL DEFAULT 0",
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("sales_order_line_items")}
            if "produced_qty" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "sales_order_line_items", "produced_qty INTEGER DEFAULT 0")
                else:
                    _add_column(
                        conn,
                        "sales_order_line_items",
                        "produced_qty INT NOT NULL DEFAULT 0",
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("sales_order_line_items")}
            if "shipped_qty" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "sales_order_line_items", "shipped_qty INTEGER DEFAULT 0")
                else:
                    _add_column(
                        conn,
                        "sales_order_line_items",
                        "shipped_qty INT NOT NULL DEFAULT 0",
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("sales_order_line_items")}
            if "labor_cost" not in cols:
                if dialect == "sqlite":
                    _add_column(
                        conn, "sales_order_line_items", "labor_cost NUMERIC(14,4) DEFAULT 0"
                    )
                else:
                    _add_column(
                        conn,
                        "sales_order_line_items",
                        "labor_cost DECIMAL(14,4) NOT NULL DEFAULT 0",
                    )

        if "trace_units" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("trace_units")}
            if "execution_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "trace_units", "execution_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE trace_units ADD COLUMN execution_id INT NULL, "
                            "ADD INDEX ix_trace_units_execution_id (execution_id)"
                        )
                    )

        if "order_material_requirements" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("order_material_requirements")}
            if "execution_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_material_requirements", "execution_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_material_requirements "
                            "ADD COLUMN execution_id INT NULL, "
                            "ADD INDEX ix_order_material_requirements_execution_id (execution_id)"
                        )
                    )

        if "stock_docs" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("stock_docs")}
            if "execution_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "stock_docs", "execution_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE stock_docs ADD COLUMN execution_id INT NULL, "
                            "ADD INDEX ix_stock_docs_execution_id (execution_id)"
                        )
                    )
            if dialect != "sqlite":
                status_col = next(
                    (c for c in inspect(engine).get_columns("stock_docs") if c["name"] == "status"),
                    None,
                )
                length = getattr(status_col.get("type") if status_col else None, "length", None)
                if isinstance(length, int) and 0 < length < 16:
                    conn.execute(
                        text("ALTER TABLE stock_docs MODIFY COLUMN status VARCHAR(16) NOT NULL")
                    )

        if "packing_plans" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("packing_plans")}
            if "basket_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "packing_plans", "basket_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE packing_plans ADD COLUMN basket_id INT NULL, "
                            "ADD INDEX ix_packing_plans_basket_id (basket_id)"
                        )
                    )
            if "execution_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "packing_plans", "execution_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE packing_plans ADD COLUMN execution_id INT NULL, "
                            "ADD INDEX ix_packing_plans_execution_id (execution_id)"
                        )
                    )
            order_col = next(
                (c for c in inspect(engine).get_columns("packing_plans") if c["name"] == "order_id"),
                None,
            )
            if dialect != "sqlite" and order_col is not None and order_col.get("nullable") is False:
                conn.execute(text("ALTER TABLE packing_plans MODIFY COLUMN order_id INT NULL"))

        if "packing_cartons" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("packing_cartons")}
            if "shipment_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "packing_cartons", "shipment_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE packing_cartons ADD COLUMN shipment_id INT NULL, "
                            "ADD INDEX ix_packing_cartons_shipment_id (shipment_id)"
                        )
                    )

        if "spec_execution_orders" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("spec_execution_orders")}
            if "is_rush" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "spec_execution_orders", "is_rush BOOLEAN DEFAULT 0")
                else:
                    _add_column(
                        conn,
                        "spec_execution_orders",
                        "is_rush TINYINT(1) NOT NULL DEFAULT 0",
                    )
            cols = {c["name"] for c in inspect(engine).get_columns("spec_execution_orders")}
            if "rush_reason" not in cols:
                _add_column(conn, "spec_execution_orders", "rush_reason VARCHAR(255) NULL")
            if "rushed_at" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "spec_execution_orders", "rushed_at DATETIME")
                else:
                    _add_column(conn, "spec_execution_orders", "rushed_at DATETIME NULL")
            cols = {c["name"] for c in inspect(engine).get_columns("spec_execution_orders")}
            if "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "spec_execution_orders", "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE spec_execution_orders ADD COLUMN header_id INT NULL, "
                            "ADD INDEX ix_spec_execution_orders_header_id (header_id)"
                        )
                    )

        if "sales_order_lines" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("sales_order_lines")}
            if "execution_header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "sales_order_lines", "execution_header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE sales_order_lines ADD COLUMN execution_header_id INT NULL, "
                            "ADD INDEX ix_sales_order_lines_execution_header_id (execution_header_id)"
                        )
                    )

        # AU-I2：TraceUnitAction 含 warehouse(9)；旧库按早期短枚举建了 varchar(8)
        if "trace_unit_logs" in tables and dialect != "sqlite":
            action_col = next(
                (c for c in inspect(engine).get_columns("trace_unit_logs") if c["name"] == "action"),
                None,
            )
            length = getattr(action_col.get("type") if action_col else None, "length", None)
            if isinstance(length, int) and 0 < length < 32:
                conn.execute(text("ALTER TABLE trace_unit_logs MODIFY COLUMN action VARCHAR(32) NOT NULL"))

        if "trace_units" in tables and dialect != "sqlite":
            status_col = next(
                (c for c in inspect(engine).get_columns("trace_units") if c["name"] == "status"),
                None,
            )
            length = getattr(status_col.get("type") if status_col else None, "length", None)
            if isinstance(length, int) and 0 < length < 32:
                conn.execute(text("ALTER TABLE trace_units MODIFY COLUMN status VARCHAR(32) NOT NULL"))

        # 去桥接：用料/领退料挂执行单头
        if "order_material_requirements" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("order_material_requirements")}
            if "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_material_requirements", "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_material_requirements ADD COLUMN header_id INT NULL, "
                            "ADD INDEX ix_omr_header_id (header_id)"
                        )
                    )
        if "stock_docs" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("stock_docs")}
            if "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "stock_docs", "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE stock_docs ADD COLUMN header_id INT NULL, "
                            "ADD INDEX ix_stock_docs_header_id (header_id)"
                        )
                    )

        # K3：报工/开裁挂执行单头；桥接 order_id 可空
        if "work_logs" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("work_logs")}
            if "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "work_logs", "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE work_logs ADD COLUMN header_id INT NULL, "
                            "ADD INDEX ix_work_logs_header_id (header_id)"
                        )
                    )
            if dialect != "sqlite":
                col = next(
                    (c for c in inspect(engine).get_columns("work_logs") if c["name"] == "order_id"),
                    None,
                )
                if col is not None and not col.get("nullable", True):
                    conn.execute(text("ALTER TABLE work_logs MODIFY COLUMN order_id INT NULL"))
            # 回填 header_id（同桥接取最新头）
            if dialect == "sqlite":
                conn.execute(
                    text(
                        """
                        UPDATE work_logs
                        SET header_id = (
                            SELECT eh.id FROM execution_headers eh
                            WHERE eh.shop_order_id = work_logs.order_id
                              AND eh.tenant_id = work_logs.tenant_id
                            ORDER BY eh.id DESC LIMIT 1
                        )
                        WHERE header_id IS NULL AND order_id IS NOT NULL
                        """
                    )
                )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE work_logs wl
                        JOIN (
                            SELECT shop_order_id, tenant_id, MAX(id) AS hid
                            FROM execution_headers
                            WHERE shop_order_id IS NOT NULL
                            GROUP BY shop_order_id, tenant_id
                        ) x ON x.shop_order_id = wl.order_id AND x.tenant_id = wl.tenant_id
                        SET wl.header_id = x.hid
                        WHERE wl.header_id IS NULL AND wl.order_id IS NOT NULL
                        """
                    )
                )

        if "trace_units" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("trace_units")}
            if "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "trace_units", "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE trace_units ADD COLUMN header_id INT NULL, "
                            "ADD INDEX ix_trace_units_header_id (header_id)"
                        )
                    )
            if dialect != "sqlite":
                col = next(
                    (c for c in inspect(engine).get_columns("trace_units") if c["name"] == "order_id"),
                    None,
                )
                if col is not None and not col.get("nullable", True):
                    conn.execute(text("ALTER TABLE trace_units MODIFY COLUMN order_id INT NULL"))
            if dialect == "sqlite":
                conn.execute(
                    text(
                        """
                        UPDATE trace_units
                        SET header_id = (
                            SELECT seo.header_id FROM spec_execution_orders seo
                            WHERE seo.id = trace_units.execution_id
                              AND seo.header_id IS NOT NULL
                            LIMIT 1
                        )
                        WHERE header_id IS NULL AND execution_id IS NOT NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE trace_units
                        SET header_id = (
                            SELECT eh.id FROM execution_headers eh
                            WHERE eh.shop_order_id = trace_units.order_id
                              AND eh.tenant_id = trace_units.tenant_id
                            ORDER BY eh.id DESC LIMIT 1
                        )
                        WHERE header_id IS NULL AND order_id IS NOT NULL
                        """
                    )
                )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE trace_units tu
                        JOIN spec_execution_orders seo ON seo.id = tu.execution_id
                        SET tu.header_id = seo.header_id
                        WHERE tu.header_id IS NULL AND seo.header_id IS NOT NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE trace_units tu
                        JOIN (
                            SELECT shop_order_id, tenant_id, MAX(id) AS hid
                            FROM execution_headers
                            WHERE shop_order_id IS NOT NULL
                            GROUP BY shop_order_id, tenant_id
                        ) x ON x.shop_order_id = tu.order_id AND x.tenant_id = tu.tenant_id
                        SET tu.header_id = x.hid
                        WHERE tu.header_id IS NULL AND tu.order_id IS NOT NULL
                        """
                    )
                )

        # K4：桥接壳打标 + 工序挂执行单头
        if "orders" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("orders")}
            if "is_bridge" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "orders", "is_bridge INTEGER NOT NULL DEFAULT 0")
                else:
                    _add_column(conn, "orders", "is_bridge TINYINT(1) NOT NULL DEFAULT 0")
            # 有执行单头挂接的壳一律标桥接
            if dialect == "sqlite":
                conn.execute(
                    text(
                        """
                        UPDATE orders
                        SET is_bridge = 1
                        WHERE id IN (
                            SELECT shop_order_id FROM execution_headers
                            WHERE shop_order_id IS NOT NULL
                        )
                        """
                    )
                )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE orders o
                        JOIN execution_headers eh ON eh.shop_order_id = o.id
                        SET o.is_bridge = 1
                        """
                    )
                )

        if "order_processes" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("order_processes")}
            if "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_processes", "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_processes ADD COLUMN header_id INT NULL, "
                            "ADD INDEX ix_order_processes_header_id (header_id)"
                        )
                    )
            if dialect == "sqlite":
                conn.execute(
                    text(
                        """
                        UPDATE order_processes
                        SET header_id = (
                            SELECT eh.id FROM execution_headers eh
                            WHERE eh.shop_order_id = order_processes.order_id
                              AND eh.tenant_id = order_processes.tenant_id
                            ORDER BY eh.id DESC LIMIT 1
                        )
                        WHERE header_id IS NULL
                        """
                    )
                )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE order_processes op
                        JOIN (
                            SELECT shop_order_id, tenant_id, MAX(id) AS hid
                            FROM execution_headers
                            WHERE shop_order_id IS NOT NULL
                            GROUP BY shop_order_id, tenant_id
                        ) x ON x.shop_order_id = op.order_id AND x.tenant_id = op.tenant_id
                        SET op.header_id = x.hid
                        WHERE op.header_id IS NULL
                        """
                    )
                )

        if "order_process_assignments" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("order_process_assignments")}
            if "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "order_process_assignments", "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE order_process_assignments ADD COLUMN header_id INT NULL, "
                            "ADD INDEX ix_opa_header_id (header_id)"
                        )
                    )
            if dialect == "sqlite":
                conn.execute(
                    text(
                        """
                        UPDATE order_process_assignments
                        SET header_id = (
                            SELECT op.header_id FROM order_processes op
                            WHERE op.id = order_process_assignments.order_process_id
                              AND op.header_id IS NOT NULL
                            LIMIT 1
                        )
                        WHERE header_id IS NULL
                        """
                    )
                )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE order_process_assignments opa
                        JOIN order_processes op ON op.id = opa.order_process_id
                        SET opa.header_id = op.header_id
                        WHERE opa.header_id IS NULL AND op.header_id IS NOT NULL
                        """
                    )
                )

        # K4-B：停写壳 — order_id 可空（工序/派工/用料可仅挂 header）
        if dialect != "sqlite":
            for table in ("order_processes", "order_process_assignments", "order_material_requirements"):
                if table not in tables:
                    continue
                col = next(
                    (c for c in inspect(engine).get_columns(table) if c["name"] == "order_id"),
                    None,
                )
                if col is not None and not col.get("nullable", True):
                    conn.execute(text(f"ALTER TABLE {table} MODIFY COLUMN order_id INT NULL"))

        # K4-D：经典排产草稿行挂执行单头；order_id 可空
        if "schedule_draft_lines" in tables:
            cols = {c["name"] for c in inspect(engine).get_columns("schedule_draft_lines")}
            if "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, "schedule_draft_lines", "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE schedule_draft_lines ADD COLUMN header_id INT NULL, "
                            "ADD INDEX ix_schedule_draft_lines_header_id (header_id)"
                        )
                    )
            if dialect != "sqlite":
                col = next(
                    (
                        c
                        for c in inspect(engine).get_columns("schedule_draft_lines")
                        if c["name"] == "order_id"
                    ),
                    None,
                )
                if col is not None and not col.get("nullable", True):
                    conn.execute(
                        text("ALTER TABLE schedule_draft_lines MODIFY COLUMN order_id INT NULL")
                    )

        # K4-E：不良/返修/筐预装认 header_id；order_id 可空
        for table in ("defect_events", "rework_tasks", "packing_plans"):
            if table not in tables:
                continue
            cols = {c["name"] for c in inspect(engine).get_columns(table)}
            if "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, table, "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD COLUMN header_id INT NULL, "
                            f"ADD INDEX ix_{table}_header_id (header_id)"
                        )
                    )
            if dialect != "sqlite":
                col = next(
                    (c for c in inspect(engine).get_columns(table) if c["name"] == "order_id"),
                    None,
                )
                if col is not None and not col.get("nullable", True):
                    conn.execute(text(f"ALTER TABLE {table} MODIFY COLUMN order_id INT NULL"))

        # K4-F：领退料/发车间/客供/核销认 header；order_id 可空
        for table, add_header in (
            ("stock_docs", False),
            ("material_releases", True),
            ("customer_supply_receipts", True),
            ("payment_allocations", False),
        ):
            if table not in tables:
                continue
            cols = {c["name"] for c in inspect(engine).get_columns(table)}
            if add_header and "header_id" not in cols:
                if dialect == "sqlite":
                    _add_column(conn, table, "header_id INTEGER")
                else:
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD COLUMN header_id INT NULL, "
                            f"ADD INDEX ix_{table}_header_id (header_id)"
                        )
                    )
            if dialect != "sqlite":
                col = next(
                    (c for c in inspect(engine).get_columns(table) if c["name"] == "order_id"),
                    None,
                )
                if col is not None and not col.get("nullable", True):
                    conn.execute(text(f"ALTER TABLE {table} MODIFY COLUMN order_id INT NULL"))

        # K4-H：不归档、不 DROP orders。剩余 NOT NULL 卸掉；MySQL 去掉指向 orders 的 FK
        for table in ("order_change_logs", "merge_batch_members"):
            if table not in tables:
                continue
            if dialect != "sqlite":
                col = next(
                    (c for c in inspect(engine).get_columns(table) if c["name"] == "order_id"),
                    None,
                )
                if col is not None and not col.get("nullable", True):
                    conn.execute(text(f"ALTER TABLE {table} MODIFY COLUMN order_id INT NULL"))
        if dialect != "sqlite":
            fk_rows = conn.execute(
                text(
                    "SELECT TABLE_NAME, CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME = 'orders'"
                )
            ).fetchall()
            seen: set[tuple[str, str]] = set()
            for table_name, constraint_name in fk_rows:
                key = (str(table_name), str(constraint_name))
                if key in seen or not constraint_name:
                    continue
                seen.add(key)
                conn.execute(
                    text(f"ALTER TABLE `{table_name}` DROP FOREIGN KEY `{constraint_name}`")
                )
