from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0003_watchlist_notifications"
down_revision = "0002_vision_retry_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watchlists",
        sa.Column("id", sa.String(length=120), primary_key=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "watchlist_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "watchlist_id",
            sa.String(length=120),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.UniqueConstraint(
            "watchlist_id",
            "category",
            name="uq_watchlist_targets_watchlist_category",
        ),
    )
    op.create_table(
        "detection_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "detection_id",
            sa.Integer(),
            sa.ForeignKey("detections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "watchlist_id",
            sa.String(length=120),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "email_run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "detection_id",
            "watchlist_id",
            "recipient_email",
            name="uq_detection_notifications_detection_watchlist_recipient",
        ),
    )


def downgrade() -> None:
    op.drop_table("detection_notifications")
    op.drop_table("watchlist_targets")
    op.drop_table("watchlists")
