from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from estate_sale_finder.analysis.base import AnalysisImage
from estate_sale_finder.config import Settings
from estate_sale_finder.db.models import Base, DetectionORM, ImageORM, RunORM
from estate_sale_finder.domain.models import (
    DetectedItem,
    ImageAnalysisResult,
    PostalCodeLocation,
    Sale,
    SaleCandidate,
    SalePicture,
)
from estate_sale_finder.pipeline import Pipeline, RunOptions


class FakeSource:
    source_name = "fake"

    def __init__(self, picture_count: int = 5, picture_urls: list[str] | None = None):
        self.picture_count = picture_count
        self.picture_urls = picture_urls or ["https://example.test/match-1.jpg"]
        self.remote_modified_at = datetime(2026, 6, 20, tzinfo=UTC)
        self.gallery_calls = 0

    def resolve_postal_code(self, postal_code: str) -> PostalCodeLocation:
        return PostalCodeLocation(postal_code, 43.0, -78.0)

    def discover_sales(self, location: PostalCodeLocation) -> list[SaleCandidate]:
        return [
            SaleCandidate(
                source="fake",
                external_id="1",
                latitude=43.01,
                longitude=-78.0,
                city="Buffalo",
                state="NY",
                postal_code="14221",
                sale_type="EstateSales",
                first_start_at=datetime(2026, 7, 1, tzinfo=UTC),
                last_end_at=datetime(2026, 7, 2, tzinfo=UTC),
            )
        ]

    def hydrate_sales(self, sale_ids: list[str]) -> list[Sale]:
        return [
            Sale(
                source="fake",
                external_id="1",
                title="Fake sale",
                url="https://example.test/sale/1",
                organization_name="Org",
                address=None,
                latitude=43.01,
                longitude=-78.0,
                city="Buffalo",
                state="NY",
                postal_code="14221",
                sale_type="EstateSales",
                picture_count=self.picture_count,
                first_start_at=datetime(2026, 7, 1, tzinfo=UTC),
                last_end_at=datetime(2026, 7, 2, tzinfo=UTC),
                first_published_at=None,
                remote_modified_at=self.remote_modified_at,
                latest_pictures_added_count=len(self.picture_urls),
            )
        ]

    def get_sale_pictures(self, sale: Sale) -> list[SalePicture]:
        self.gallery_calls += 1
        return [SalePicture(str(index), url) for index, url in enumerate(self.picture_urls)]


class FakeDownloader:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def download_into_record(self, image: ImageORM) -> None:
        thumb = self.tmp_path / f"thumb-{image.id}-positive.jpg"
        Image.new("RGB", (16, 16), "blue").save(thumb, format="JPEG")
        image.local_thumbnail_path = str(thumb)
        image.status = "downloaded"
        image.sha256 = f"sha-{image.id}"
        image.perceptual_hash = "0" * 16
        image.width = 16
        image.height = 16
        image.mime_type = "image/jpeg"


class FakeVision:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, images: list[AnalysisImage]) -> list[ImageAnalysisResult]:
        self.calls += len(images)
        return [
            ImageAnalysisResult(
                image_id=image.image_id,
                contains_target=True,
                items=[DetectedItem("modern_camera", "digital camera", 0.9, 0.8, None, "match")],
                provider="fake",
                model_name="fake-model",
                prompt_version="test",
            )
            for image in images
        ]


class BadBatchVision:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def analyze(self, images: list[AnalysisImage]) -> list[ImageAnalysisResult]:
        self.batch_sizes.append(len(images))
        if len(images) > 1:
            return [
                ImageAnalysisResult(
                    image_id=0,
                    contains_target=False,
                    items=[],
                    provider="fake",
                    model_name="fake-model",
                    prompt_version="test",
                )
            ]
        return [
            ImageAnalysisResult(
                image_id=images[0].image_id,
                contains_target=False,
                items=[],
                provider="fake",
                model_name="fake-model",
                prompt_version="test",
            )
        ]


class BadSingleVision:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, images: list[AnalysisImage]) -> list[ImageAnalysisResult]:
        self.calls += len(images)
        return [
            ImageAnalysisResult(
                image_id=0,
                contains_target=False,
                items=[],
                provider="fake",
                model_name="fake-model",
                prompt_version="test",
            )
        ]


class FakePrefilter:
    def __init__(self, passed: bool) -> None:
        self.passed = passed
        self.calls = 0

    def score(self, image_path: Path) -> tuple[bool, float]:
        self.calls += 1
        return self.passed, 0.9 if self.passed else 0.1


class FakeNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.sent = 0
        self.fail = fail

    def send_digest(self, detections: list[DetectionORM]) -> None:
        if self.fail:
            raise RuntimeError("smtp failed")
        self.sent += len(detections)

    def send_failure(self, subject: str, body: str) -> None:
        return None


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, future=True)()


def _settings(tmp_path: Path, *, email: bool = True, version: str = "v1") -> Settings:
    return Settings(
        data_dir=tmp_path,
        email_enabled=email,
        smtp_host="smtp.example.test" if email else None,
        email_from="from@example.test" if email else None,
        email_to="to@example.test" if email else "",
        analysis_version=version,
    )


def test_first_run_then_idempotent_second_run(tmp_path: Path) -> None:
    session = _session()
    source = FakeSource()
    vision = FakeVision()
    notifier = FakeNotifier()
    pipeline = Pipeline(
        settings=_settings(tmp_path),
        session=session,
        source=source,
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
        notifier=notifier,
    )
    first = pipeline.run(RunOptions())
    second = pipeline.run(RunOptions())
    assert first.images_analyzed == 1
    assert second.images_analyzed == 0
    assert vision.calls == 1
    assert notifier.sent == 1


def test_newly_added_image_only_is_analyzed(tmp_path: Path) -> None:
    session = _session()
    source = FakeSource(picture_urls=["https://example.test/match-1.jpg"])
    vision = FakeVision()
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=source,
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
    )
    pipeline.run(RunOptions())
    source.picture_urls.append("https://example.test/match-2.jpg")
    source.picture_count = 6
    pipeline.run(RunOptions())
    assert vision.calls == 2
    assert len(list(session.scalars(select(ImageORM)))) == 2


def test_below_minimum_later_becomes_eligible(tmp_path: Path) -> None:
    session = _session()
    source = FakeSource(picture_count=4)
    vision = FakeVision()
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=source,
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
    )
    first = pipeline.run(RunOptions())
    source.picture_count = 5
    source.picture_urls = [f"https://example.test/match-{index}.jpg" for index in range(200)]
    source.remote_modified_at = datetime(2026, 6, 22, tzinfo=UTC)
    second = pipeline.run(RunOptions())
    assert first.sales_eligible == 0
    assert second.sales_eligible == 1
    assert len(list(session.scalars(select(ImageORM)))) == 200
    assert second.images_analyzed == 200


def test_changed_modified_date_with_same_images_is_idempotent(tmp_path: Path) -> None:
    session = _session()
    source = FakeSource(picture_urls=["https://example.test/match-1.jpg"])
    vision = FakeVision()
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=source,
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
    )
    pipeline.run(RunOptions())
    source.remote_modified_at = datetime(2026, 6, 23, tzinfo=UTC)
    second = pipeline.run(RunOptions())
    assert source.gallery_calls == 2
    assert second.images_analyzed == 0
    assert vision.calls == 1


def test_failed_gallery_scan_is_retried(tmp_path: Path) -> None:
    class FailingOnceSource(FakeSource):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        def get_sale_pictures(self, sale: Sale) -> list[SalePicture]:
            self.gallery_calls += 1
            if not self.failed:
                self.failed = True
                raise RuntimeError("temporary gallery failure")
            return [SalePicture(str(index), url) for index, url in enumerate(self.picture_urls)]

    session = _session()
    source = FailingOnceSource()
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=source,
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=FakeVision(),
    )
    first = pipeline.run(RunOptions())
    second = pipeline.run(RunOptions())
    assert first.images_analyzed == 0
    assert second.images_analyzed == 1
    assert source.gallery_calls == 2


def test_failed_email_does_not_mark_sent(tmp_path: Path) -> None:
    session = _session()
    pipeline = Pipeline(
        settings=_settings(tmp_path),
        session=session,
        source=FakeSource(),
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=FakeVision(),
        notifier=FakeNotifier(fail=True),
    )
    with suppress(RuntimeError):
        pipeline.run(RunOptions())
    detections = list(session.scalars(select(DetectionORM)))
    assert detections
    assert detections[0].included_in_email is False


def test_analysis_version_change_reanalyzes_when_requested(tmp_path: Path) -> None:
    session = _session()
    source = FakeSource()
    vision = FakeVision()
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False, version="v1"),
        session=session,
        source=source,
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
    )
    pipeline.run(RunOptions())
    pipeline.settings.analysis_version = "v2"
    second = pipeline.run(RunOptions(reanalyze_version_mismatch=True))
    assert second.images_analyzed == 1


def test_local_prefilter_counts_passed_and_rejected_images(tmp_path: Path) -> None:
    session = _session()
    source = FakeSource(picture_urls=["https://example.test/rejected.jpg"])
    vision = FakeVision()
    prefilter = FakePrefilter(passed=False)
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=source,
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
        prefilter=prefilter,
    )
    summary = pipeline.run(RunOptions())
    image = session.scalar(select(ImageORM))

    assert prefilter.calls == 1
    assert summary.images_prefiltered == 1
    assert summary.images_prefilter_passed == 0
    assert summary.images_prefilter_rejected == 1
    assert summary.vision_batches_sent == 0
    assert summary.vision_batches_succeeded == 0
    assert summary.images_analyzed == 0
    assert vision.calls == 0
    assert image is not None
    assert image.local_prefilter_passed is False


def test_vision_batch_counts_when_prefilter_passes(tmp_path: Path) -> None:
    session = _session()
    source = FakeSource(picture_urls=["https://example.test/match-1.jpg"])
    vision = FakeVision()
    prefilter = FakePrefilter(passed=True)
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=source,
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
        prefilter=prefilter,
    )
    summary = pipeline.run(RunOptions())

    assert summary.images_prefiltered == 1
    assert summary.images_prefilter_passed == 1
    assert summary.images_prefilter_rejected == 0
    assert summary.vision_batches_sent == 1
    assert summary.vision_batches_succeeded == 1
    assert summary.vision_batches_failed == 0
    assert summary.images_analyzed == 1
    assert vision.calls == 1


def test_bad_batch_mapping_retries_images_individually(tmp_path: Path) -> None:
    session = _session()
    source = FakeSource(
        picture_urls=[
            "https://example.test/image-1.jpg",
            "https://example.test/image-2.jpg",
        ]
    )
    vision = BadBatchVision()
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=source,
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
    )
    pipeline.settings.vision_batch_size = 2
    summary = pipeline.run(RunOptions())

    assert vision.batch_sizes == [2, 1, 1]
    assert summary.vision_batches_sent == 3
    assert summary.vision_batches_failed == 1
    assert summary.vision_batches_succeeded == 2
    assert summary.images_analyzed == 2


def test_single_image_bad_id_is_remapped(tmp_path: Path) -> None:
    session = _session()
    vision = BadSingleVision()
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=FakeSource(),
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
    )
    summary = pipeline.run(RunOptions())
    image = session.scalar(select(ImageORM))

    assert vision.calls == 1
    assert summary.vision_batches_failed == 0
    assert summary.images_analyzed == 1
    assert image is not None
    assert image.status == "analyzed"


def test_vision_max_images_per_run_limits_analysis(tmp_path: Path) -> None:
    session = _session()
    vision = FakeVision()
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=FakeSource(
            picture_urls=[
                "https://example.test/image-1.jpg",
                "https://example.test/image-2.jpg",
                "https://example.test/image-3.jpg",
            ]
        ),
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=vision,
    )
    pipeline.settings.vision_max_images_per_run = 2
    first = pipeline.run(RunOptions())
    second = pipeline.run(RunOptions())

    assert first.images_analyzed == 2
    assert second.images_analyzed == 1
    assert vision.calls == 3


def test_stale_running_runs_are_marked_failed(tmp_path: Path) -> None:
    session = _session()
    stale = RunORM(start_time=datetime(2026, 6, 30, tzinfo=UTC), status="running")
    session.add(stale)
    session.commit()
    pipeline = Pipeline(
        settings=_settings(tmp_path, email=False),
        session=session,
        source=FakeSource(),
        downloader=FakeDownloader(tmp_path),  # type: ignore[arg-type]
        vision_provider=FakeVision(),
    )

    pipeline.run(RunOptions())
    session.refresh(stale)

    assert stale.status == "failed"
    assert stale.completion_time is not None
    assert stale.error_summary is not None
