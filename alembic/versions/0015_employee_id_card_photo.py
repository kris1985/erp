"""员工身份证正反面照片，均可空。"""

from alembic import op
import sqlalchemy as sa


revision = "0015_employee_id_card_photo"
down_revision = "0014_employee_photo_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch_op:
        batch_op.add_column(sa.Column("id_card_front_url", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("id_card_back_url", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("employees") as batch_op:
        batch_op.drop_column("id_card_back_url")
        batch_op.drop_column("id_card_front_url")
