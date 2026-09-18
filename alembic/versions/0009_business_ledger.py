"""Create business_ledger_entries; add fund_account to expenses/advances."""

from alembic import op
import sqlalchemy as sa


revision = "0009_business_ledger"
down_revision = "0008_daily_expense_department_employee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_ledger_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("biz_type", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("fund_account", sa.String(length=16), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_no", sa.String(length=80), nullable=True),
        sa.Column("year_month", sa.String(length=7), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_type", "source_id", name="uq_business_ledger_source"),
    )
    op.create_index("ix_business_ledger_entries_tenant_id", "business_ledger_entries", ["tenant_id"])
    op.create_index("ix_business_ledger_entries_entry_date", "business_ledger_entries", ["entry_date"])
    op.create_index("ix_business_ledger_entries_biz_type", "business_ledger_entries", ["biz_type"])
    op.create_index("ix_business_ledger_entries_source_type", "business_ledger_entries", ["source_type"])
    op.create_index("ix_business_ledger_entries_source_id", "business_ledger_entries", ["source_id"])
    op.create_index("ix_business_ledger_entries_year_month", "business_ledger_entries", ["year_month"])
    op.create_index("ix_business_ledger_entries_status", "business_ledger_entries", ["status"])

    op.add_column("daily_expenses", sa.Column("fund_account", sa.String(length=16), nullable=True))
    op.add_column("salary_advances", sa.Column("fund_account", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("salary_advances", "fund_account")
    op.drop_column("daily_expenses", "fund_account")
    op.drop_index("ix_business_ledger_entries_status", table_name="business_ledger_entries")
    op.drop_index("ix_business_ledger_entries_year_month", table_name="business_ledger_entries")
    op.drop_index("ix_business_ledger_entries_source_id", table_name="business_ledger_entries")
    op.drop_index("ix_business_ledger_entries_source_type", table_name="business_ledger_entries")
    op.drop_index("ix_business_ledger_entries_biz_type", table_name="business_ledger_entries")
    op.drop_index("ix_business_ledger_entries_entry_date", table_name="business_ledger_entries")
    op.drop_index("ix_business_ledger_entries_tenant_id", table_name="business_ledger_entries")
    op.drop_table("business_ledger_entries")
