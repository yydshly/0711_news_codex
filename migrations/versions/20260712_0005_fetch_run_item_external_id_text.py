"""Allow audit records to retain provider-native long identifiers."""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0005"
down_revision = "20260712_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fetch_run_items") as batch_op:
        batch_op.alter_column(
            "external_id",
            existing_type=sa.String(255),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("fetch_run_items") as batch_op:
        batch_op.alter_column(
            "external_id",
            existing_type=sa.Text(),
            type_=sa.String(255),
            existing_nullable=True,
        )
