"""Create worker_adjustments and salary_advances tables."""

from alembic import op
import sqlalchemy as sa


revision = "0004_worker_adjustments_advances"
down_revision = "0003_process_pay_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_adjustments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("advance_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["employees.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["worker_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worker_adjustments_tenant_id", "worker_adjustments", ["tenant_id"])
    op.create_index("ix_worker_adjustments_worker_id", "worker_adjustments", ["worker_id"])
    op.create_index("ix_worker_adjustments_year_month", "worker_adjustments", ["year_month"])
    op.create_index("ix_worker_adjustments_source", "worker_adjustments", ["source"])
    op.create_index("ix_worker_adjustments_advance_id", "worker_adjustments", ["advance_id"])

    op.create_table(
        "salary_advances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("advanced_at", sa.Date(), nullable=False),
        sa.Column("repay_year_month", sa.String(length=7), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["employees.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["worker_id"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_salary_advances_tenant_id", "salary_advances", ["tenant_id"])
    op.create_index("ix_salary_advances_worker_id", "salary_advances", ["worker_id"])
    op.create_index("ix_salary_advances_repay_year_month", "salary_advances", ["repay_year_month"])


def downgrade() -> None:
    op.drop_index("ix_salary_advances_repay_year_month", table_name="salary_advances")
    op.drop_index("ix_salary_advances_worker_id", table_name="salary_advances")
    op.drop_index("ix_salary_advances_tenant_id", table_name="salary_advances")
    op.drop_table("salary_advances")
    op.drop_index("ix_worker_adjustments_advance_id", table_name="worker_adjustments")
    op.drop_index("ix_worker_adjustments_source", table_name="worker_adjustments")
    op.drop_index("ix_worker_adjustments_year_month", table_name="worker_adjustments")
    op.drop_index("ix_worker_adjustments_worker_id", table_name="worker_adjustments")
    op.drop_index("ix_worker_adjustments_tenant_id", table_name="worker_adjustments")
    op.drop_table("worker_adjustments")
