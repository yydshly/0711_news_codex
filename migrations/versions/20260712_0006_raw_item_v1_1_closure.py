"""Store every audited credential requirement for an access method."""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0006"
down_revision = "20260712_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fetch_runs") as batch_op:
        batch_op.drop_constraint(
            "fk_fetch_runs_access_method_id_source_access_methods", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_fetch_runs_access_method_id_source_access_methods",
            "source_access_methods",
            ["access_method_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("source_access_methods") as batch_op:
        batch_op.add_column(
            sa.Column("auth_envs", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
    with op.batch_alter_table("source_fetch_states") as batch_op:
        batch_op.add_column(sa.Column("last_failure_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("last_error_code", sa.String(length=64)))
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
    op.create_index(
        "ix_raw_items_title_fingerprint_published_at",
        "raw_items",
        ["title_fingerprint", "published_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_raw_items_title_fingerprint_published_at", table_name="raw_items")
    with op.batch_alter_table("source_fetch_states") as batch_op:
        batch_op.drop_column("last_error_code")
        batch_op.drop_column("last_failure_at")
    with op.batch_alter_table("source_access_methods") as batch_op:
        batch_op.drop_column("auth_envs")
    with op.batch_alter_table("fetch_runs") as batch_op:
        batch_op.drop_constraint(
            "fk_fetch_runs_access_method_id_source_access_methods", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_fetch_runs_access_method_id_source_access_methods",
            "source_access_methods",
            ["access_method_id"],
            ["id"],
        )
