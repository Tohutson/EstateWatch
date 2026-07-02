from __future__ import annotations

from sqlalchemy import Select, delete, select
from sqlalchemy.orm import Session, selectinload

from estate_sale_finder.domain.models import (
    APPROVED_TARGET_CATEGORIES,
    DetectedItem,
    ImageAnalysisResult,
    Sale,
    SalePicture,
    approved_detected_item,
)
from estate_sale_finder.utils.dates import utc_now
from estate_sale_finder.utils.urls import normalize_url

from .models import DetectionORM, ImageORM, RunORM, SaleORM


def sale_has_changed(existing: SaleORM, sale: Sale) -> bool:
    return (
        existing.picture_count != sale.picture_count
        or existing.remote_modified_at != sale.remote_modified_at
        or existing.latest_pictures_added_count != sale.latest_pictures_added_count
    )


class Repository:
    def __init__(self, session: Session):
        self.session = session

    def create_run(self) -> RunORM:
        run = RunORM(start_time=utc_now(), status="running")
        self.session.add(run)
        self.session.flush()
        return run

    def mark_abandoned_running_runs(self) -> int:
        now = utc_now()
        abandoned_runs = list(
            self.session.scalars(select(RunORM).where(RunORM.status == "running"))
        )
        for run in abandoned_runs:
            run.completion_time = now
            run.status = "failed"
            run.error_summary = (
                "Run was still marked running when a new run acquired the process lock"
            )
        return len(abandoned_runs)

    def finish_run(
        self,
        run: RunORM,
        *,
        status: str,
        summary: object,
        error_summary: str | None = None,
    ) -> None:
        run.completion_time = utc_now()
        run.status = status
        for field in [
            "sales_discovered",
            "sales_hydrated",
            "sales_eligible",
            "new_sales",
            "changed_sales",
            "images_discovered",
            "images_downloaded",
            "images_analyzed",
            "vision_batches_attempted",
            "vision_batches_retried",
            "vision_batch_mapping_failures",
            "images_retried_individually",
            "images_analysis_failed",
            "images_analysis_succeeded",
            "positive_matches",
            "email_status",
        ]:
            if hasattr(summary, field):
                setattr(run, field, getattr(summary, field))
        run.error_summary = error_summary

    def get_sale(self, source: str, external_id: str) -> SaleORM | None:
        return self.session.scalar(
            select(SaleORM).where(SaleORM.source == source, SaleORM.external_id == external_id)
        )

    def upsert_sale(self, sale: Sale) -> tuple[SaleORM, bool, bool]:
        now = utc_now()
        existing = self.get_sale(sale.source, sale.external_id)
        is_new = existing is None
        changed = False
        if existing is None:
            existing = SaleORM(
                source=sale.source,
                external_id=sale.external_id,
                first_seen_at=now,
                gallery_status="not_requested",
                active=True,
                title=sale.title,
                url=sale.url,
                latitude=sale.latitude,
                longitude=sale.longitude,
                type=sale.sale_type,
                picture_count=sale.picture_count,
                first_start_at=sale.first_start_at,
                last_end_at=sale.last_end_at,
            )
            self.session.add(existing)
        else:
            changed = sale_has_changed(existing, sale)
        existing.title = sale.title
        existing.organization_name = sale.organization_name
        existing.url = sale.url
        existing.address = sale.address
        existing.city = sale.city
        existing.state = sale.state
        existing.postal_code = sale.postal_code
        existing.latitude = sale.latitude
        existing.longitude = sale.longitude
        existing.type = sale.sale_type
        existing.picture_count = sale.picture_count
        existing.first_start_at = sale.first_start_at
        existing.last_end_at = sale.last_end_at
        existing.first_published_at = sale.first_published_at
        existing.remote_modified_at = sale.remote_modified_at
        existing.latest_pictures_added_count = sale.latest_pictures_added_count
        existing.last_seen_at = now
        existing.active = sale.last_end_at >= now
        existing.distance_miles = sale.distance_miles
        self.session.flush()
        return existing, is_new, changed

    def mark_gallery_status(self, sale: SaleORM, status: str, error: str | None = None) -> None:
        sale.gallery_status = status
        sale.gallery_error = error
        sale.last_gallery_refresh_at = utc_now()

    def upsert_image(self, sale: SaleORM, picture: SalePicture) -> tuple[ImageORM, bool]:
        existing = self.session.scalar(
            select(ImageORM).where(
                ImageORM.sale_id == sale.id,
                ImageORM.source_url == picture.source_url,
            )
        )
        if existing:
            return existing, False
        image = ImageORM(
            sale_id=sale.id,
            source_image_id=picture.source_id,
            source_url=picture.source_url,
            normalized_url=normalize_url(picture.source_url),
            first_seen_at=utc_now(),
            status="discovered",
        )
        self.session.add(image)
        self.session.flush()
        return image, True

    def images_to_analyze(
        self,
        *,
        analysis_version: str,
        reanalyze: bool,
        version_mismatch: bool,
        sale_db_id: int | None = None,
    ) -> list[ImageORM]:
        if reanalyze or version_mismatch:
            stmt: Select[tuple[ImageORM]] = select(ImageORM).where(
                ImageORM.status.in_(["downloaded", "analyzed", "failed"])
            )
        else:
            stmt = select(ImageORM).where(ImageORM.status.in_(["downloaded", "failed"]))
        if sale_db_id is not None:
            stmt = stmt.where(ImageORM.sale_id == sale_db_id)
        if not reanalyze:
            if version_mismatch:
                stmt = stmt.where(
                    (ImageORM.analyzed_at.is_(None))
                    | (ImageORM.analysis_version != analysis_version)
                )
            else:
                stmt = stmt.where(ImageORM.analyzed_at.is_(None))
        return list(self.session.scalars(stmt))

    def unemailable_detections(self, limit: int) -> list[DetectionORM]:
        return list(
            self.session.scalars(
                select(DetectionORM)
                .options(selectinload(DetectionORM.image).selectinload(ImageORM.sale))
                .where(DetectionORM.included_in_email.is_(False))
                .where(DetectionORM.category.in_(APPROVED_TARGET_CATEGORIES))
                .order_by(DetectionORM.created_at.asc())
                .limit(limit)
            )
        )

    def persist_analysis(
        self,
        image: ImageORM,
        result: ImageAnalysisResult,
        *,
        analysis_version: str,
    ) -> int:
        image.analyzed_at = utc_now()
        image.analysis_version = analysis_version
        image.status = "analyzed"
        image.last_analysis_error = None
        approved_items = [
            approved_item
            for item in result.items
            if (approved_item := approved_detected_item(item)) is not None
        ]
        self.session.execute(delete(DetectionORM).where(DetectionORM.image_id == image.id))
        for item in approved_items:
            self.session.add(_detection_from_item(image.id, item, result, analysis_version))
        self.session.flush()
        return len(approved_items)

    def mark_analysis_attempt(self, image: ImageORM) -> None:
        image.analysis_attempt_count += 1
        image.last_analysis_attempt_at = utc_now()
        if image.analyzed_at is None:
            image.status = "analyzing"

    def mark_analysis_failed(self, image: ImageORM, error: str) -> None:
        image.last_analysis_error = _bounded_error(error)
        image.error_message = image.last_analysis_error
        if image.analyzed_at is None:
            image.status = "failed"
        self.session.flush()

    def mark_detections_emailed(self, detections: list[DetectionORM]) -> None:
        now = utc_now()
        for detection in detections:
            detection.included_in_email = True
            detection.email_sent_at = now


def _detection_from_item(
    image_id: int,
    item: DetectedItem,
    result: ImageAnalysisResult,
    analysis_version: str,
) -> DetectionORM:
    return DetectionORM(
        image_id=image_id,
        category=item.category,
        label=item.label,
        confidence=item.confidence,
        modern_likelihood=item.modern_likelihood,
        visible_brand=item.visible_brand,
        notes=item.notes,
        model_provider=result.provider,
        model_name=result.model_name,
        prompt_version=result.prompt_version,
        analysis_version=analysis_version,
        created_at=utc_now(),
    )


def _bounded_error(error: str, limit: int = 500) -> str:
    sanitized = " ".join(error.split())
    if len(sanitized) <= limit:
        return sanitized
    return sanitized[: limit - 3] + "..."
