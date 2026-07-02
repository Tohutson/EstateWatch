from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0002_vision_retry_state"
down_revision = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "images",
        sa.Column(
            "analysis_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "images",
        sa.Column("last_analysis_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("images", sa.Column("last_analysis_error", sa.Text(), nullable=True))
    op.add_column(
        "runs",
        sa.Column(
            "vision_batches_attempted",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "runs",
        sa.Column("vision_batches_retried", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "runs",
        sa.Column(
            "vision_batch_mapping_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "images_retried_individually",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "runs",
        sa.Column("images_analysis_failed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "runs",
        sa.Column("images_analysis_succeeded", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("runs", "images_analysis_succeeded")
    op.drop_column("runs", "images_analysis_failed")
    op.drop_column("runs", "images_retried_individually")
    op.drop_column("runs", "vision_batch_mapping_failures")
    op.drop_column("runs", "vision_batches_retried")
    op.drop_column("runs", "vision_batches_attempted")
    op.drop_column("images", "last_analysis_error")
    op.drop_column("images", "last_analysis_attempt_at")
    op.drop_column("images", "analysis_attempt_count")
