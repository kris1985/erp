"""Add daily meal/housing allowances on employees."""

from alembic import op
import sqlalchemy as sa


revision = "0006_employee_daily_allowances"
down_revision = "0005_salary_settle_through"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch_op:
        batch_op.add_column(
            sa.Column("meal_allowance_daily", sa.Numeric(10, 2), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("housing_allowance_daily", sa.Numeric(10, 2), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("employees") as batch_op:
        batch_op.drop_column("housing_allowance_daily")
        batch_op.drop_column("meal_allowance_daily")
