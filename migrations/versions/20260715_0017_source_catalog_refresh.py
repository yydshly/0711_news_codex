"""Persist frozen source catalog refresh members and probe provenance."""

import sqlalchemy as sa
from alembic import op

revision = "20260715_0017"
down_revision = "20260715_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_catalog_refresh_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operation_run_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("availability_snapshot", sa.String(length=32), nullable=False),
        sa.Column("coverage_mode_snapshot", sa.String(length=32), nullable=False),
        sa.Column("access_kind_snapshot", sa.String(length=32), nullable=False),
        sa.Column("lane", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("result_code", sa.String(length=64)),
        sa.Column("conclusion", sa.Text()),
        sa.Column("content_probe_run_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("provider_probe_run_id", sa.Integer()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["operation_run_id"], ["operation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source_definitions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["provider_probe_run_id"], ["source_provider_probe_runs.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("operation_run_id", "source_id"),
    )
    op.create_index(
        "ix_source_catalog_refresh_members_operation_state",
        "source_catalog_refresh_members",
        ["operation_run_id", "state"],
    )
    for table_name, index_name in (
        ("source_probe_runs", "ix_source_probe_runs_operation_run_id"),
        ("source_provider_probe_runs", "ix_source_provider_probe_runs_operation_run_id"),
    ):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.add_column(sa.Column("operation_run_id", sa.Integer(), nullable=True))
                batch_op.create_foreign_key(
                    f"fk_{table_name}_operation_run_id",
                    "operation_runs",
                    ["operation_run_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
                batch_op.create_index(index_name, ["operation_run_id"])
        else:
            op.add_column(
                table_name,
                sa.Column(
                    "operation_run_id",
                    sa.Integer(),
                    sa.ForeignKey("operation_runs.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
            op.create_index(index_name, table_name, ["operation_run_id"])


def downgrade() -> None:
    for table_name, index_name in (
        ("source_provider_probe_runs", "ix_source_provider_probe_runs_operation_run_id"),
        ("source_probe_runs", "ix_source_probe_runs_operation_run_id"),
    ):
        op.drop_index(index_name, table_name=table_name)
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_constraint(
                    f"fk_{table_name}_operation_run_id", type_="foreignkey"
                )
                batch_op.drop_column("operation_run_id")
        else:
            op.drop_column(table_name, "operation_run_id")
    op.drop_index(
        "ix_source_catalog_refresh_members_operation_state",
        table_name="source_catalog_refresh_members",
    )
    op.drop_table("source_catalog_refresh_members")
