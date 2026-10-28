"""员工其它补贴（元/天）。"""

from alembic import op
import sqlalchemy as sa


revision = "0012_employee_other_allowance"
down_revision = "0011_workshop_count_by_header"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch_op:
        batch_op.add_column(
            sa.Column("other_allowance_daily", sa.Numeric(10, 2), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("employees") as batch_op:
        batch_op.drop_column("other_allowance_daily")
