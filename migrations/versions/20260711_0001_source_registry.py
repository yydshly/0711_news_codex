"""Create source intelligence registry tables."""

from alembic import op

from newsradar.db.models import Base

revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
