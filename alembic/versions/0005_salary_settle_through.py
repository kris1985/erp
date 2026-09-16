"""Add settle_through to salary_month_locks for early month-end cutoff."""

from alembic import op
import sqlalchemy as sa


revision = "0005_salary_settle_through"
down_revision = "0004_worker_adjustments_advances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("salary_month_locks") as batch_op:
        batch_op.add_column(sa.Column("settle_through", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("salary_month_locks") as batch_op:
        batch_op.drop_column("settle_through")
