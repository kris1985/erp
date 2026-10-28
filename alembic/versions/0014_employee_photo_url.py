"""员工照片，可空。"""

from alembic import op
import sqlalchemy as sa


revision = "0014_employee_photo_url"
down_revision = "0013_defect_responsibility_share_amount"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch_op:
        batch_op.add_column(sa.Column("photo_url", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("employees") as batch_op:
        batch_op.drop_column("photo_url")
