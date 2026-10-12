"""车间剩余按生产单：workshop_material_counts 加 header_id。"""

from alembic import op
import sqlalchemy as sa


revision = "0011_workshop_count_by_header"
down_revision = "0010_daily_expense_pending_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 旧全局清点无生产单语义，直接清空后重建约束
    op.execute("DELETE FROM workshop_material_counts")
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("workshop_material_counts") as batch:
            batch.drop_constraint("uq_workshop_material_count", type_="unique")
            batch.add_column(sa.Column("header_id", sa.Integer(), nullable=False))
            batch.create_unique_constraint(
                "uq_workshop_material_count_header",
                ["tenant_id", "header_id", "supplier_product_id", "size_id"],
            )
    else:
        op.execute("ALTER TABLE workshop_material_counts DROP INDEX uq_workshop_material_count")
        op.execute(
            "ALTER TABLE workshop_material_counts "
            "ADD COLUMN header_id INT NOT NULL, "
            "ADD INDEX ix_workshop_material_counts_header_id (header_id), "
            "ADD CONSTRAINT fk_workshop_material_counts_header_id "
            "FOREIGN KEY (header_id) REFERENCES execution_headers (id), "
            "ADD UNIQUE KEY uq_workshop_material_count_header "
            "(tenant_id, header_id, supplier_product_id, size_id)"
        )


def downgrade() -> None:
    op.execute("DELETE FROM workshop_material_counts")
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("workshop_material_counts") as batch:
            batch.drop_constraint("uq_workshop_material_count_header", type_="unique")
            batch.drop_column("header_id")
            batch.create_unique_constraint(
                "uq_workshop_material_count",
                ["tenant_id", "supplier_product_id", "size_id"],
            )
    else:
        op.execute(
            "ALTER TABLE workshop_material_counts "
            "DROP INDEX uq_workshop_material_count_header, "
            "DROP FOREIGN KEY fk_workshop_material_counts_header_id, "
            "DROP INDEX ix_workshop_material_counts_header_id, "
            "DROP COLUMN header_id, "
            "ADD UNIQUE KEY uq_workshop_material_count "
            "(tenant_id, supplier_product_id, size_id)"
        )
