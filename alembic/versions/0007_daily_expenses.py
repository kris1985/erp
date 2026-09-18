"""Create daily_expenses + daily_expense_lines for operating expense bookkeeping."""

from alembic import op
import sqlalchemy as sa


revision = "0007_daily_expenses"
down_revision = "0006_employee_daily_allowances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_expenses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["employees.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_expenses_tenant_id", "daily_expenses", ["tenant_id"])
    op.create_index("ix_daily_expenses_kind", "daily_expenses", ["kind"])
    op.create_index("ix_daily_expenses_expense_date", "daily_expenses", ["expense_date"])
    op.create_index("ix_daily_expenses_status", "daily_expenses", ["status"])

    op.create_table(
        "daily_expense_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("category_image_urls", sa.Text(), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("invoice_urls", sa.Text(), nullable=True),
        sa.Column("receipt_urls", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["expense_id"], ["daily_expenses.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_expense_lines_tenant_id", "daily_expense_lines", ["tenant_id"])
    op.create_index("ix_daily_expense_lines_expense_id", "daily_expense_lines", ["expense_id"])
    op.create_index("ix_daily_expense_lines_category", "daily_expense_lines", ["category"])
    op.create_index("ix_daily_expense_lines_occurred_on", "daily_expense_lines", ["occurred_on"])


def downgrade() -> None:
    op.drop_index("ix_daily_expense_lines_occurred_on", table_name="daily_expense_lines")
    op.drop_index("ix_daily_expense_lines_category", table_name="daily_expense_lines")
    op.drop_index("ix_daily_expense_lines_expense_id", table_name="daily_expense_lines")
    op.drop_index("ix_daily_expense_lines_tenant_id", table_name="daily_expense_lines")
    op.drop_table("daily_expense_lines")
    op.drop_index("ix_daily_expenses_status", table_name="daily_expenses")
    op.drop_index("ix_daily_expenses_expense_date", table_name="daily_expenses")
    op.drop_index("ix_daily_expenses_kind", table_name="daily_expenses")
    op.drop_index("ix_daily_expenses_tenant_id", table_name="daily_expenses")
    op.drop_table("daily_expenses")
