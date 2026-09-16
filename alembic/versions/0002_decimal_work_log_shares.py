"""Allow two decimal places in piecework allocations."""

from alembic import op
import sqlalchemy as sa


revision = "0002_decimal_work_log_shares"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("work_logs") as batch_op:
        batch_op.alter_column(
            "qualified_qty",
            existing_type=sa.Integer(),
            type_=sa.Numeric(14, 2),
            existing_nullable=False,
        )
    with op.batch_alter_table("work_log_group_shares") as batch_op:
        batch_op.alter_column(
            "pairs",
            existing_type=sa.Integer(),
            type_=sa.Numeric(14, 2),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("work_log_group_shares") as batch_op:
        batch_op.alter_column(
            "pairs",
            existing_type=sa.Numeric(14, 2),
            type_=sa.Integer(),
            existing_nullable=False,
        )
    with op.batch_alter_table("work_logs") as batch_op:
        batch_op.alter_column(
            "qualified_qty",
            existing_type=sa.Numeric(14, 2),
            type_=sa.Integer(),
            existing_nullable=False,
        )
