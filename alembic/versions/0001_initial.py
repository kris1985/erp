"""empty — autogenerate or create_all via seed for MVP."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MVP uses Base.metadata.create_all in seed; keep revision for Alembic chain.
    pass


def downgrade() -> None:
    pass
