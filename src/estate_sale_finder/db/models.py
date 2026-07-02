from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SaleORM(Base):
    __tablename__ = "sales"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_sales_source_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    organization_name: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(20))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    picture_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remote_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_pictures_added_count: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_gallery_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gallery_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_requested")
    gallery_error: Mapped[str | None] = mapped_column(Text)
    distance_miles: Mapped[float | None] = mapped_column(Float)

    images: Mapped[list[ImageORM]] = relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )


class ImageORM(Base):
    __tablename__ = "images"
    __table_args__ = (UniqueConstraint("sale_id", "source_url", name="uq_images_sale_source_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    source_image_id: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_version: Mapped[str | None] = mapped_column(String(80))
    analysis_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_analysis_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_analysis_error: Mapped[str | None] = mapped_column(Text)
    local_thumbnail_path: Mapped[str | None] = mapped_column(String(1000))
    local_original_path: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="discovered")
    error_message: Mapped[str | None] = mapped_column(Text)
    local_prefilter_score: Mapped[float | None] = mapped_column(Float)
    local_prefilter_passed: Mapped[bool | None] = mapped_column(Boolean)

    sale: Mapped[SaleORM] = relationship(back_populates="images")
    detections: Mapped[list[DetectionORM]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )


class DetectionORM(Base):
    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    modern_likelihood: Mapped[float] = mapped_column(Float, nullable=False)
    visible_brand: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    model_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    included_in_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    image: Mapped[ImageORM] = relationship(back_populates="detections")


class RunORM(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    sales_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sales_hydrated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sales_eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_sales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_sales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    images_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    images_downloaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    images_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vision_batches_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vision_batches_retried: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vision_batch_mapping_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    images_retried_individually: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    images_analysis_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    images_analysis_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    positive_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email_status: Mapped[str] = mapped_column(String(80), nullable=False, default="not_sent")
    error_summary: Mapped[str | None] = mapped_column(Text)
