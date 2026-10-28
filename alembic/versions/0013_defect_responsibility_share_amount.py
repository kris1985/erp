"""报废责任分摊保存填写金额。"""

from alembic import op
import sqlalchemy as sa


revision = "0013_defect_responsibility_share_amount"
down_revision = "0012_employee_other_allowance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("defect_responsibilities") as batch_op:
        batch_op.add_column(sa.Column("share_amount", sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("defect_responsibilities") as batch_op:
        batch_op.drop_column("share_amount")
