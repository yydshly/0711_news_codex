"""Store every audited credential requirement for an access method."""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0006"
down_revision = "20260712_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_access_methods") as batch_op:
        batch_op.add_column(
            sa.Column("auth_envs", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "UPDATE source_access_methods "
                "SET auth_envs = CASE WHEN auth_env IS NULL THEN CAST('[]' AS json) "
                "ELSE json_build_array(auth_env) END"
            )
        )
    else:
        bind.execute(
            sa.text(
                "UPDATE source_access_methods "
                "SET auth_envs = CASE WHEN auth_env IS NULL THEN '[]' "
                "ELSE '[\"' || auth_env || '\"]' END"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("source_access_methods") as batch_op:
        batch_op.drop_column("auth_envs")
