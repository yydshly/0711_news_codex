"""Add daily report item editorial reviews."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0025"
down_revision = "20260716_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_report_item_editorial_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "daily_report_item_id",
            sa.Integer(),
            sa.ForeignKey("daily_report_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("zh_title", sa.Text(), nullable=False),
        sa.Column("zh_summary", sa.Text(), nullable=False),
        sa.Column("review_recommendation", sa.Text(), nullable=False),
        sa.Column("evidence_assessment", sa.Text(), nullable=False),
        sa.Column(
            "copied_from_editorial_review_id",
            sa.Integer(),
            sa.ForeignKey(
                "daily_report_item_editorial_reviews.id", ondelete="RESTRICT"
            ),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_daily_report_editorial_revision"),
        sa.CheckConstraint(
            "decision IN ('keep', 'needs_evidence', 'exclude', 'duplicate')",
            name="ck_daily_report_editorial_decision",
        ),
        sa.UniqueConstraint(
            "daily_report_item_id",
            "revision",
            name="uq_daily_report_editorial_item_revision",
        ),
    )
    op.create_index(
        "ix_daily_report_editorial_reviews_item_revision",
        "daily_report_item_editorial_reviews",
        ["daily_report_item_id", "revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_daily_report_editorial_reviews_item_revision",
        table_name="daily_report_item_editorial_reviews",
    )
    op.drop_table("daily_report_item_editorial_reviews")
