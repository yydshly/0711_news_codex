"""Add event-quality v2.1 tier, rank, and candidate-pair audit data."""

import sqlalchemy as sa
from alembic import op

revision = "20260715_0015"
down_revision = "20260714_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column(
        "events",
        sa.Column(
            "display_tier",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'signal'"),
        ),
    )
    op.add_column(
        "events",
        sa.Column("rank_score", sa.Float(), nullable=False, server_default=sa.text("0")),
    )
    op.execute(
        "UPDATE events SET display_tier = CASE "
        "WHEN visibility = 'legacy' OR status = 'rejected' THEN 'audit_only' "
        "WHEN status = 'confirmed' THEN 'hotspot' ELSE 'signal' END"
    )
    op.execute(
        "UPDATE events SET rank_score = COALESCE((SELECT heat FROM event_scores "
        "WHERE event_scores.event_id = events.id "
        "AND event_scores.version_number = events.current_version_number), 0)"
    )
    op.create_index(
        "ix_events_tier_rank_occurred_at",
        "events",
        ["visibility", "display_tier", "rank_score", "occurred_at"],
    )
    op.create_table(
        "event_pair_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("left_raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False),
        sa.Column("right_raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False),
        sa.Column("algorithm_version", sa.String(120), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("rule_score", sa.Float(), nullable=False),
        sa.Column("rule_reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("model_same_event", sa.Boolean()),
        sa.Column("model_confidence", sa.Float()),
        sa.Column("final_decision", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("left_raw_item_id < right_raw_item_id", name="ck_event_pair_order"),
        sa.UniqueConstraint(
            "left_raw_item_id",
            "right_raw_item_id",
            "algorithm_version",
            "input_fingerprint",
            name="uq_event_pair_decision_input",
        ),
    )
    op.create_index(
        "ix_event_pair_decisions_lookup",
        "event_pair_decisions",
        ["left_raw_item_id", "right_raw_item_id", "algorithm_version"],
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("event_model_runs") as batch_op:
            batch_op.add_column(sa.Column("pair_decision_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_event_model_runs_pair_decision_id",
                "event_pair_decisions",
                ["pair_decision_id"],
                ["id"],
            )
            batch_op.create_index(
                "ix_event_model_runs_pair_decision_id", ["pair_decision_id"]
            )
    else:
        op.add_column(
            "event_model_runs",
            sa.Column(
                "pair_decision_id",
                sa.Integer(),
                sa.ForeignKey("event_pair_decisions.id"),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_event_model_runs_pair_decision_id",
            "event_model_runs",
            ["pair_decision_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("event_model_runs") as batch_op:
            batch_op.drop_index("ix_event_model_runs_pair_decision_id")
            batch_op.drop_constraint("fk_event_model_runs_pair_decision_id", type_="foreignkey")
            batch_op.drop_column("pair_decision_id")
    else:
        op.drop_index("ix_event_model_runs_pair_decision_id", table_name="event_model_runs")
        op.drop_column("event_model_runs", "pair_decision_id")
    op.drop_index("ix_event_pair_decisions_lookup", table_name="event_pair_decisions")
    op.drop_table("event_pair_decisions")
    op.drop_index("ix_events_tier_rank_occurred_at", table_name="events")
    op.drop_column("events", "rank_score")
    op.drop_column("events", "display_tier")
