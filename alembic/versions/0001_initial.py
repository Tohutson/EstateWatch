from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completion_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("sales_discovered", sa.Integer(), nullable=False),
        sa.Column("sales_hydrated", sa.Integer(), nullable=False),
        sa.Column("sales_eligible", sa.Integer(), nullable=False),
        sa.Column("new_sales", sa.Integer(), nullable=False),
        sa.Column("changed_sales", sa.Integer(), nullable=False),
        sa.Column("images_discovered", sa.Integer(), nullable=False),
        sa.Column("images_downloaded", sa.Integer(), nullable=False),
        sa.Column("images_analyzed", sa.Integer(), nullable=False),
        sa.Column("positive_matches", sa.Integer(), nullable=False),
        sa.Column("email_status", sa.String(length=80), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
    )
    op.create_table(
        "sales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("organization_name", sa.String(length=300), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("city", sa.String(length=200), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("picture_count", sa.Integer(), nullable=False),
        sa.Column("first_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_pictures_added_count", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_gallery_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("gallery_status", sa.String(length=40), nullable=False),
        sa.Column("gallery_error", sa.Text(), nullable=True),
        sa.Column("distance_miles", sa.Float(), nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_sales_source_external"),
    )
    op.create_table(
        "images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "sale_id", sa.Integer(), sa.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source_image_id", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.String(length=1200), nullable=False),
        sa.Column("normalized_url", sa.String(length=1200), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("perceptual_hash", sa.String(length=64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analysis_version", sa.String(length=80), nullable=True),
        sa.Column("local_thumbnail_path", sa.String(length=1000), nullable=True),
        sa.Column("local_original_path", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("local_prefilter_score", sa.Float(), nullable=True),
        sa.Column("local_prefilter_passed", sa.Boolean(), nullable=True),
        sa.UniqueConstraint("sale_id", "source_url", name="uq_images_sale_source_url"),
    )
    op.create_index("ix_images_sha256", "images", ["sha256"])
    op.create_table(
        "detections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("modern_likelihood", sa.Float(), nullable=False),
        sa.Column("visible_brand", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("model_provider", sa.String(length=80), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("analysis_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("included_in_email", sa.Boolean(), nullable=False),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("detections")
    op.drop_index("ix_images_sha256", table_name="images")
    op.drop_table("images")
    op.drop_table("sales")
    op.drop_table("runs")
