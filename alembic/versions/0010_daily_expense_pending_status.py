"""Widen daily_expenses.status so pending (待付款) fits."""

from alembic import op


revision = "0010_daily_expense_pending_status"
down_revision = "0009_business_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE daily_expenses MODIFY COLUMN status VARCHAR(16) NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE daily_expenses MODIFY COLUMN status VARCHAR(6) NOT NULL")
