"""Add process pay mode for piecework and hourly routes."""

from alembic import op
import sqlalchemy as sa


revision = "0003_process_pay_mode"
down_revision = "0002_decimal_work_log_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("process_definitions") as batch_op:
        batch_op.add_column(
            sa.Column("pay_mode", sa.String(length=16), nullable=False, server_default="piecework")
        )


def downgrade() -> None:
    with op.batch_alter_table("process_definitions") as batch_op:
        batch_op.drop_column("pay_mode")
