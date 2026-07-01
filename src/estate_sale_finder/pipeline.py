from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from estate_sale_finder.analysis.base import AnalysisImage, LocalPrefilter, VisionProvider
from estate_sale_finder.analysis.local_prefilter import DisabledPrefilter
from estate_sale_finder.config import Settings
from estate_sale_finder.db.models import DetectionORM, ImageORM, SaleORM
from estate_sale_finder.db.repository import Repository
from estate_sale_finder.domain.models import RunSummary, Sale, SaleCandidate
from estate_sale_finder.images.downloader import ImageDownloader
from estate_sale_finder.notifications.base import NotificationProvider
from estate_sale_finder.sources.base import GalleryUnavailableError, SaleSource
from estate_sale_finder.utils.dates import overlaps_window, utc_now
from estate_sale_finder.utils.geo import haversine_miles

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunOptions:
    reanalyze: bool = False
    reanalyze_version_mismatch: bool = False
    sale_id: str | None = None
    dry_run: bool = False


class NoopNotifier:
    def send_digest(self, detections: list[DetectionORM]) -> None:
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
    ):
        self.settings = settings
        self.session = session
        self.repo = Repository(session)
        self.source = source
        self.downloader = downloader
        self.vision_provider = vision_provider
        self.notifier = notifier or NoopNotifier()
        self.prefilter = prefilter or DisabledPrefilter()

    def run(self, options: RunOptions) -> RunSummary:
        run = self.repo.create_run()
        summary = RunSummary()
        try:
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
            self._send_digest(summary, options)
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
                self.notifier.send_failure("Estate Sale Finder failed", str(exc))
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
                if is_new or changed or sale_orm.last_gallery_refresh_at is None:
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
        images = list(self.session.scalars(select(ImageORM).where(ImageORM.status == "discovered")))
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
        )
        pending: list[AnalysisImage] = []
        for image in images:
            if not image.local_thumbnail_path:
                image.status = "error"
                image.error_message = "Missing thumbnail for analysis"
                continue
            passed, score = self.prefilter.score(Path(image.local_thumbnail_path))
            image.local_prefilter_passed = passed
            image.local_prefilter_score = score
            if passed:
                pending.append(
                    AnalysisImage(
                        image_id=image.id,
                        thumbnail_path=Path(image.local_thumbnail_path),
                        source_url=image.source_url,
                    )
                )
            else:
                image.analyzed_at = utc_now()
                image.analysis_version = self.settings.analysis_version
                image.status = "analyzed"
            self.session.commit()

        for index in range(0, len(pending), self.settings.vision_batch_size):
            batch = pending[index : index + self.settings.vision_batch_size]
            by_id = {
                image.id: image
                for image in self.session.scalars(
                    select(ImageORM).where(ImageORM.id.in_([item.image_id for item in batch]))
                )
            }
            results = self.vision_provider.analyze(batch)
            mapped_ids = {result.image_id for result in results}
            if mapped_ids != set(by_id):
                raise RuntimeError("Vision provider response did not map cleanly to image IDs")
            for result in results:
                image = by_id[result.image_id]
                positives = self.repo.persist_analysis(
                    image,
                    result,
                    analysis_version=self.settings.analysis_version,
                )
                summary.images_analyzed += 1
                summary.positive_matches += positives
            self.session.commit()

    def _send_digest(self, summary: RunSummary, options: RunOptions) -> None:
        detections = self.repo.unemailable_detections(limit=50)
        if options.dry_run:
            summary.email_status = "dry_run"
            return
        if not detections and not self.settings.email_send_on_no_matches:
            summary.email_status = "no_matches"
            return
        if not self.settings.email_enabled:
            summary.email_status = "disabled"
            return
        self.notifier.send_digest(detections)
        self.repo.mark_detections_emailed(detections)
        summary.email_status = "sent"
