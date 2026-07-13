"""Link content probes to their remediation acquisition evidence."""

import sqlalchemy as sa
from alembic import op

revision = "20260713_0013"
down_revision = "20260713_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_probe_runs",
        sa.Column("remediation_acquisition_probe_id", sa.Integer(), nullable=True),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_source_probe_remediation_acquisition",
            "source_probe_runs",
            "source_acquisition_probe_runs",
            ["remediation_acquisition_probe_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_source_probe_runs_remediation_acquisition_probe_id",
        "source_probe_runs",
        ["remediation_acquisition_probe_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_probe_runs_remediation_acquisition_probe_id",
        table_name="source_probe_runs",
    )
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(
            "fk_source_probe_remediation_acquisition",
            "source_probe_runs",
            type_="foreignkey",
        )
    op.drop_column("source_probe_runs", "remediation_acquisition_probe_id")
