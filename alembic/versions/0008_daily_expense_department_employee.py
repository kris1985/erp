"""Add department_id and employee_id to daily_expenses."""

from alembic import op
import sqlalchemy as sa


revision = "0008_daily_expense_department_employee"
down_revision = "0007_daily_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("daily_expenses", sa.Column("department_id", sa.Integer(), nullable=True))
    op.add_column("daily_expenses", sa.Column("employee_id", sa.Integer(), nullable=True))
    op.create_index("ix_daily_expenses_department_id", "daily_expenses", ["department_id"])
    op.create_index("ix_daily_expenses_employee_id", "daily_expenses", ["employee_id"])
    op.create_foreign_key(
        "fk_daily_expenses_department_id",
        "daily_expenses",
        "departments",
        ["department_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_daily_expenses_employee_id",
        "daily_expenses",
        "employees",
        ["employee_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_daily_expenses_employee_id", "daily_expenses", type_="foreignkey")
    op.drop_constraint("fk_daily_expenses_department_id", "daily_expenses", type_="foreignkey")
    op.drop_index("ix_daily_expenses_employee_id", table_name="daily_expenses")
    op.drop_index("ix_daily_expenses_department_id", table_name="daily_expenses")
    op.drop_column("daily_expenses", "employee_id")
    op.drop_column("daily_expenses", "department_id")
