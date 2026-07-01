from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from estate_sale_finder.db.models import Base
from estate_sale_finder.db.repository import Repository, sale_has_changed
from estate_sale_finder.domain.models import DetectedItem, ImageAnalysisResult, Sale, SalePicture


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, future=True)()


def _sale(pictures: int = 5, modified: datetime | None = None) -> Sale:
    return Sale(
        source="test",
        external_id="1",
        title="Test sale",
        url="https://example.test/sale/1",
        organization_name=None,
        address=None,
        latitude=43,
        longitude=-78,
        city="Buffalo",
        state="NY",
        postal_code="14221",
        sale_type="EstateSales",
        picture_count=pictures,
        first_start_at=datetime(2026, 7, 1, tzinfo=UTC),
        last_end_at=datetime(2026, 7, 2, tzinfo=UTC),
        first_published_at=None,
        remote_modified_at=modified,
        latest_pictures_added_count=0,
    )


def test_sale_upsert_and_change_detection() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, is_new, changed = repo.upsert_sale(_sale())
    assert is_new is True
    assert changed is False
    assert not sale_has_changed(sale_orm, _sale())
    _, is_new, changed = repo.upsert_sale(_sale(pictures=6))
    assert is_new is False
    assert changed is True


def test_image_deduplication() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, _, _ = repo.upsert_sale(_sale())
    image1, new1 = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    image2, new2 = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    assert image1.id == image2.id
    assert new1 is True
    assert new2 is False


def test_detection_persistence_and_email_status() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, _, _ = repo.upsert_sale(_sale())
    image, _ = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    image.status = "downloaded"
    repo.persist_analysis(
        image,
        ImageAnalysisResult(
            image_id=image.id,
            contains_target=True,
            items=[DetectedItem("camera", "mirrorless camera", 0.9, 0.8, "Sony", "visible body")],
            provider="mock",
            model_name="mock",
            prompt_version="mock",
        ),
        analysis_version="v1",
    )
    detections = repo.unemailable_detections(limit=10)
    assert len(detections) == 1
    repo.mark_detections_emailed(detections)
    assert repo.unemailable_detections(limit=10) == []


def test_analysis_version_logic() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, _, _ = repo.upsert_sale(_sale())
    image, _ = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    image.status = "downloaded"
    image.analysis_version = "v1"
    image.analyzed_at = datetime(2026, 7, 1, tzinfo=UTC)
    image.status = "analyzed"
    assert (
        repo.images_to_analyze(analysis_version="v1", reanalyze=False, version_mismatch=False) == []
    )
    assert repo.images_to_analyze(
        analysis_version="v2", reanalyze=False, version_mismatch=True
    ) == [image]
