from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from estate_sale_finder.analysis.base import AnalysisImage, LocalPrefilter, VisionProvider
from estate_sale_finder.analysis.errors import (
    VisionProviderError,
    VisionResponseMappingError,
)
from estate_sale_finder.analysis.local_prefilter import DisabledPrefilter
from estate_sale_finder.analysis.mapping import validate_vision_result_mapping
from estate_sale_finder.config import Settings
from estate_sale_finder.db.models import DetectionORM, ImageORM, SaleORM
from estate_sale_finder.db.repository import Repository
from estate_sale_finder.domain.models import ImageAnalysisResult, RunSummary, Sale, SaleCandidate
from estate_sale_finder.images.downloader import ImageDownloader
from estate_sale_finder.notifications.base import NotificationProvider
from estate_sale_finder.sources.base import GalleryUnavailableError, SaleSource
from estate_sale_finder.utils.dates import overlaps_window, utc_now
from estate_sale_finder.utils.geo import haversine_miles
from estate_sale_finder.watchlists import WatchlistProfile, load_watchlists

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunOptions:
    reanalyze: bool = False
    reanalyze_version_mismatch: bool = False
    sale_id: str | None = None
    dry_run: bool = False
    active_only: bool = False


class NoopNotifier:
    def send_digest(
        self,
        profile: WatchlistProfile,
        recipient: str,
        detections: list[DetectionORM],
    ) -> None:
        return None

    def send_failure(self, subject: str, body: str) -> None:
        return None


class Pipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        session: Session,
        source: SaleSource,
        downloader: ImageDownloader,
        vision_provider: VisionProvider,
        notifier: NotificationProvider | None = None,
        prefilter: LocalPrefilter | None = None,
        watchlists: list[WatchlistProfile] | None = None,
    ):
        self.settings = settings
        self.session = session
        self.repo = Repository(session)
        self.source = source
        self.downloader = downloader
        self.vision_provider = vision_provider
        self.notifier = notifier or NoopNotifier()
        self.prefilter = prefilter or DisabledPrefilter()
        self.watchlists = watchlists or load_watchlists(
            settings,
            require_recipients=settings.email_enabled,
        )

    def run(self, options: RunOptions) -> RunSummary:
        abandoned_runs = self.repo.mark_abandoned_running_runs()
        if abandoned_runs:
            logger.warning("abandoned_running_runs_marked_failed", extra={"count": abandoned_runs})
        self.session.commit()
        run = self.repo.create_run()
        summary = RunSummary()
        try:
            self.repo.sync_watchlists(self.watchlists)
            seeded = self.repo.seed_legacy_notification_state(self.watchlists)
            if seeded:
                logger.info("legacy_notification_state_seeded", extra={"count": seeded})
            self.session.commit()
            if options.sale_id:
                sales = self.source.hydrate_sales([options.sale_id])
                candidates_by_id: dict[str, SaleCandidate] = {}
            else:
                location = self.source.resolve_postal_code(self.settings.postal_code)
                candidates = self.source.discover_sales(location)
                summary.sales_discovered = len(candidates)
                eligible_candidates = self._filter_candidates(
                    candidates, location.latitude, location.longitude
                )
                candidates_by_id = {
                    candidate.external_id: candidate for candidate in eligible_candidates
                }
                sales = self.source.hydrate_sales(list(candidates_by_id))
            summary.sales_hydrated = len(sales)
            sales_to_refresh = self._persist_sales(sales, candidates_by_id, summary)
            self._refresh_galleries(sales_to_refresh, summary)
            self._download_discovered_images(summary)
            self._analyze_images(options, summary)
            self._send_digest(summary, options, run.id)
            self.repo.finish_run(run, status="success", summary=summary)
            self.session.commit()
            logger.info("run_complete", extra=summary.__dict__)
            return summary
        except Exception as exc:
            self.session.rollback()
            with self.session.begin():
                run = self.session.merge(run)
                self.repo.finish_run(run, status="failed", summary=summary, error_summary=str(exc))
            if self.settings.email_send_on_failure and not options.dry_run:
                try:
                    self.notifier.send_failure("Estate Sale Finder failed", str(exc))
                except Exception as notify_exc:
                    logger.warning(
                        "failure_notification_failed",
                        extra={"error": _sanitize_error(str(notify_exc))},
                    )
            logger.exception("run_failed")
            raise

    def _filter_candidates(
        self,
        candidates: list[SaleCandidate],
        origin_lat: float,
        origin_lon: float,
    ) -> list[SaleCandidate]:
        now = utc_now()
        window_end = now + timedelta(days=self.settings.lookahead_days)
        eligible: list[SaleCandidate] = []
        for candidate in candidates:
            distance = haversine_miles(
                origin_lat, origin_lon, candidate.latitude, candidate.longitude
            )
            if distance > self.settings.search_radius_miles:
                continue
            if candidate.sale_type not in self.settings.allowed_sale_types:
                continue
            if not overlaps_window(
                candidate.first_start_at, candidate.last_end_at, now, window_end
            ):
                continue
            eligible.append(
                candidate.__class__(**{**candidate.__dict__, "distance_miles": distance})
            )
        return eligible

    def _persist_sales(
        self,
        sales: list[Sale],
        candidates_by_id: dict[str, SaleCandidate],
        summary: RunSummary,
    ) -> list[tuple[SaleORM, Sale]]:
        to_refresh: list[tuple[SaleORM, Sale]] = []
        for sale in sales:
            candidate = candidates_by_id.get(sale.external_id)
            sale_with_distance = sale.__class__(
                **{
                    **sale.__dict__,
                    "distance_miles": candidate.distance_miles
                    if candidate
                    else sale.distance_miles,
                }
            )
            sale_orm, is_new, changed = self.repo.upsert_sale(sale_with_distance)
            if is_new:
                summary.new_sales += 1
            if changed:
                summary.changed_sales += 1
            if sale.picture_count >= self.settings.min_picture_count:
                summary.sales_eligible += 1
                if (
                    is_new
                    or changed
                    or sale_orm.last_gallery_refresh_at is None
                    or sale_orm.gallery_status != "ok"
                ):
                    to_refresh.append((sale_orm, sale_with_distance))
        self.session.commit()
        return to_refresh

    def _refresh_galleries(self, sales: list[tuple[SaleORM, Sale]], summary: RunSummary) -> None:
        for sale_orm, sale in sales:
            try:
                pictures = self.source.get_sale_pictures(sale)
                for picture in pictures:
                    _, is_new = self.repo.upsert_image(sale_orm, picture)
                    if is_new:
                        summary.images_discovered += 1
                self.repo.mark_gallery_status(sale_orm, "ok")
            except GalleryUnavailableError as exc:
                self.repo.mark_gallery_status(sale_orm, "unavailable", str(exc))
                logger.warning("gallery_unavailable", extra={"sale_external_id": sale.external_id})
            except Exception as exc:
                self.repo.mark_gallery_status(sale_orm, "error", str(exc))
                logger.warning(
                    "gallery_failed",
                    extra={"sale_external_id": sale.external_id, "error": str(exc)},
                )
            self.session.commit()

    def _download_discovered_images(self, summary: RunSummary) -> None:
        images = list(
            self.session.scalars(
                select(ImageORM).where(
                    (ImageORM.status == "discovered")
                    | ((ImageORM.status == "error") & (ImageORM.downloaded_at.is_(None)))
                )
            )
        )
        for image in images:
            self.downloader.download_into_record(image)
            if image.status == "downloaded":
                summary.images_downloaded += 1
            self.session.commit()

    def _analyze_images(self, options: RunOptions, summary: RunSummary) -> None:
        sale_db_id = None
        if options.sale_id:
            sale = self.repo.get_sale(self.source.source_name, options.sale_id)
            sale_db_id = sale.id if sale else None
        images = self.repo.images_to_analyze(
            analysis_version=self.settings.analysis_version,
            reanalyze=options.reanalyze,
            version_mismatch=options.reanalyze_version_mismatch,
            sale_db_id=sale_db_id,
            active_only=options.active_only,
        )
        if self.settings.vision_max_images_per_run is not None:
            original_count = len(images)
            images = images[: self.settings.vision_max_images_per_run]
            logger.info(
                "vision_images_limited",
                extra={
                    "selected_images": len(images),
                    "available_images": original_count,
                    "limit": self.settings.vision_max_images_per_run,
                },
            )
        pending: list[AnalysisImage] = []
        for image in images:
            if not image.local_thumbnail_path:
                image.status = "error"
                image.error_message = "Missing thumbnail for analysis"
                continue
            passed, score = self.prefilter.score(Path(image.local_thumbnail_path))
            summary.images_prefiltered += 1
            image.local_prefilter_passed = passed
            image.local_prefilter_score = score
            if passed:
                summary.images_prefilter_passed += 1
                pending.append(
                    AnalysisImage(
                        image_id=image.id,
                        thumbnail_path=Path(image.local_thumbnail_path),
                        source_url=image.source_url,
                    )
                )
            else:
                summary.images_prefilter_rejected += 1
                image.analyzed_at = utc_now()
                image.analysis_version = self.settings.analysis_version
                image.status = "analyzed"
            self.session.commit()

        logger.info(
            "local_prefilter_complete",
            extra={
                "images_prefiltered": summary.images_prefiltered,
                "images_prefilter_passed": summary.images_prefilter_passed,
                "images_prefilter_rejected": summary.images_prefilter_rejected,
            },
        )
        for index in range(0, len(pending), self.settings.vision_batch_size):
            batch = pending[index : index + self.settings.vision_batch_size]
            batch_number = index // self.settings.vision_batch_size + 1
            self._analyze_vision_batch_with_fallback(batch, batch_number, summary)

    def _analyze_vision_batch_with_fallback(
        self,
        batch: list[AnalysisImage],
        batch_number: int,
        summary: RunSummary,
    ) -> None:
        try:
            mapped_results = self._analyze_vision_batch(
                batch,
                batch_number,
                summary,
                max_attempts=self.settings.vision_max_batch_attempts,
            )
            self._persist_vision_results(mapped_results, summary)
            self.session.commit()
            return
        except VisionProviderError as exc:
            if len(batch) == 1:
                self._mark_image_analysis_failed(batch[0], exc, summary)
                self.session.commit()
                return
            summary.vision_batches_retried += 1
            logger.warning(
                "vision_batch_retry_individual",
                extra={
                    **self._vision_log_context(batch, batch_number),
                    "retry_strategy": "individual",
                    "error_type": type(exc).__name__,
                    "error": _sanitize_error(str(exc)),
                },
            )

        for offset, item in enumerate(batch, start=1):
            summary.images_retried_individually += 1
            try:
                mapped_results = self._analyze_vision_batch(
                    [item],
                    batch_number,
                    summary,
                    fallback_index=offset,
                    max_attempts=self.settings.vision_max_single_image_attempts,
                )
                self._persist_vision_results(mapped_results, summary)
            except VisionProviderError as exc:
                self._mark_image_analysis_failed(item, exc, summary)
            self.session.commit()

    def _analyze_vision_batch(
        self,
        batch: list[AnalysisImage],
        batch_number: int,
        summary: RunSummary,
        *,
        fallback_index: int | None = None,
        max_attempts: int,
    ) -> list[tuple[ImageORM, ImageAnalysisResult]]:
        analysis_batch = _with_batch_refs(batch)
        reference_to_image = self._reference_to_image(analysis_batch)
        log_context = self._vision_log_context(analysis_batch, batch_number, fallback_index)
        last_error: VisionProviderError | None = None
        for attempt in range(1, max_attempts + 1):
            attempt_context = {**log_context, "attempt": attempt, "max_attempts": max_attempts}
            self._mark_analysis_attempts(reference_to_image.values())
            self.session.commit()
            summary.vision_batches_sent += 1
            summary.vision_batches_attempted += 1
            logger.info("vision_batch_sent", extra=attempt_context)
            try:
                results = self.vision_provider.analyze(analysis_batch)
                mapped_results = validate_vision_result_mapping(
                    reference_to_image,
                    results,
                    log_context=attempt_context,
                )
            except VisionResponseMappingError as exc:
                last_error = exc
                summary.vision_batches_failed += 1
                summary.vision_batch_mapping_failures += 1
                logger.warning(
                    "vision_batch_mapping_failed",
                    extra={
                        **attempt_context,
                        "returned_refs": exc.returned_refs,
                        "missing_refs": sorted(exc.missing_refs),
                        "unexpected_refs": sorted(exc.unexpected_refs),
                        "duplicate_refs": sorted(exc.duplicate_refs),
                        "retry_strategy": _retry_strategy(attempt, max_attempts, len(batch)),
                    },
                )
            except VisionProviderError as exc:
                last_error = exc
                summary.vision_batches_failed += 1
                logger.warning(
                    "vision_batch_provider_failed",
                    extra={
                        **attempt_context,
                        "error_type": type(exc).__name__,
                        "error": _sanitize_error(str(exc)),
                        "retry_strategy": _retry_strategy(attempt, max_attempts, len(batch)),
                    },
                )
            else:
                summary.vision_batches_succeeded += 1
                logger.info(
                    "vision_batch_succeeded",
                    extra={**attempt_context, "returned_refs": sorted(reference_to_image)},
                )
                return mapped_results

            self.session.rollback()
            if attempt < max_attempts:
                summary.vision_batches_retried += 1
                time.sleep(self.settings.vision_retry_backoff_seconds)

        if last_error is None:
            last_error = VisionProviderError("Vision provider failed without an exception")
        raise last_error

    def _persist_vision_results(
        self,
        mapped_results: list[tuple[ImageORM, ImageAnalysisResult]],
        summary: RunSummary,
    ) -> None:
        for image, result in mapped_results:
            positives = self.repo.persist_analysis(
                image,
                result,
                analysis_version=self.settings.analysis_version,
            )
            summary.images_analyzed += 1
            summary.images_analysis_succeeded += 1
            summary.positive_matches += positives

    def _reference_to_image(self, batch: list[AnalysisImage]) -> dict[str, ImageORM]:
        by_id = {
            image.id: image
            for image in self.session.scalars(
                select(ImageORM).where(ImageORM.id.in_([item.image_id for item in batch]))
            )
        }
        return {item.image_ref: by_id[item.image_id] for item in batch}

    def _mark_analysis_attempts(self, images: Iterable[ImageORM]) -> None:
        for image in images:
            self.repo.mark_analysis_attempt(image)
        self.session.flush()

    def _mark_image_analysis_failed(
        self,
        item: AnalysisImage,
        exc: VisionProviderError,
        summary: RunSummary,
    ) -> None:
        image = self.session.get(ImageORM, item.image_id)
        if image is None:
            return
        error = _sanitize_error(str(exc))
        self.repo.mark_analysis_failed(image, error)
        summary.images_analysis_failed += 1
        logger.warning(
            "vision_image_analysis_failed",
            extra={
                "provider": self.vision_provider.provider_name,
                "model": self.vision_provider.model_name,
                "image_id": item.image_id,
                "sale_id": image.sale_id,
                "error_type": type(exc).__name__,
                "error": error,
            },
        )

    def _vision_log_context(
        self,
        batch: list[AnalysisImage],
        batch_number: int,
        fallback_index: int | None = None,
    ) -> dict[str, object]:
        image_ids = [item.image_id for item in batch]
        sale_ids = list(
            self.session.scalars(select(ImageORM.sale_id).where(ImageORM.id.in_(image_ids)))
        )
        return {
            "provider": self.vision_provider.provider_name,
            "model": self.vision_provider.model_name,
            "batch_number": batch_number,
            "batch_size": len(batch),
            "fallback_index": fallback_index,
            "expected_refs": [item.image_ref for item in batch],
            "image_ids": image_ids,
            "sale_ids": sale_ids,
        }

    def _send_digest(self, summary: RunSummary, options: RunOptions, run_id: int) -> None:
        if options.dry_run:
            summary.email_status = "dry_run"
            return
        if not self.settings.email_enabled:
            summary.email_status = "disabled"
            return
        sent = 0
        failures = 0
        considered = 0
        for profile in self.watchlists:
            for recipient in profile.recipients:
                considered += 1
                detections = self.repo.pending_detections_for_watchlist(
                    profile,
                    recipient,
                    limit=50,
                )
                if not detections and not profile.send_on_no_matches:
                    continue
                try:
                    self.notifier.send_digest(profile, recipient, detections)
                except Exception as exc:
                    failures += 1
                    logger.warning(
                        "watchlist_email_failed",
                        extra={
                            "watchlist_id": profile.id,
                            "recipient_hash": _recipient_hash(recipient),
                            "error": _sanitize_error(str(exc)),
                        },
                    )
                    continue
                self.repo.mark_notifications_sent(
                    detections,
                    watchlist_id=profile.id,
                    recipient=recipient,
                    email_run_id=run_id,
                )
                sent += 1
                self.session.commit()
        if failures and sent:
            summary.email_status = "partial_failed"
        elif failures:
            summary.email_status = "failed"
        elif sent:
            summary.email_status = "sent"
        elif considered:
            summary.email_status = "no_matches"
        else:
            summary.email_status = "no_recipients"


def _with_batch_refs(batch: list[AnalysisImage]) -> list[AnalysisImage]:
    return [
        replace(item, image_ref=f"img_{index:04d}") for index, item in enumerate(batch, start=1)
    ]


def _retry_strategy(attempt: int, max_attempts: int, batch_size: int) -> str:
    if attempt < max_attempts:
        return "same_batch"
    if batch_size > 1:
        return "individual"
    return "fail_image"


def _sanitize_error(error: str, limit: int = 500) -> str:
    sanitized = " ".join(error.split())
    if len(sanitized) <= limit:
        return sanitized
    return sanitized[: limit - 3] + "..."


def _recipient_hash(recipient: str) -> str:
    import hashlib

    return hashlib.sha256(recipient.lower().encode("utf-8")).hexdigest()[:12]
