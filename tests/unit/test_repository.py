from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from estate_sale_finder.db.models import Base, DetectionNotificationORM, DetectionORM
from estate_sale_finder.db.repository import Repository, sale_has_changed
from estate_sale_finder.domain.models import DetectedItem, ImageAnalysisResult, Sale, SalePicture
from estate_sale_finder.routing import matching_watchlists
from estate_sale_finder.utils.dates import utc_now
from estate_sale_finder.watchlists import WatchlistProfile


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, future=True)()


def _sale(
    *,
    external_id: str = "1",
    pictures: int = 5,
    modified: datetime | None = None,
    last_end_at: datetime | None = None,
) -> Sale:
    return Sale(
        source="test",
        external_id=external_id,
        title="Test sale",
        url=f"https://example.test/sale/{external_id}",
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
        last_end_at=last_end_at or datetime(2026, 7, 2, tzinfo=UTC),
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


def test_active_only_analysis_ignores_stale_active_flag_for_ended_sales() -> None:
    session = _session()
    repo = Repository(session)
    now = utc_now()
    ended_sale, _, _ = repo.upsert_sale(
        _sale(external_id="ended", last_end_at=now - timedelta(days=7))
    )
    future_sale, _, _ = repo.upsert_sale(
        _sale(external_id="future", last_end_at=now + timedelta(days=7))
    )
    ended_sale.active = True
    ended_image, _ = repo.upsert_image(
        ended_sale, SalePicture(None, "https://example.test/ended.jpg")
    )
    future_image, _ = repo.upsert_image(
        future_sale, SalePicture(None, "https://example.test/future.jpg")
    )
    for image in [ended_image, future_image]:
        image.status = "analyzed"
        image.analyzed_at = now - timedelta(days=1)
        image.analysis_version = "old-version"
    session.flush()

    images = repo.images_to_analyze(
        analysis_version="new-version",
        reanalyze=False,
        version_mismatch=True,
        active_only=True,
    )

    assert images == [future_image]


def test_detection_persistence_and_email_status() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, _, _ = repo.upsert_sale(_sale())
    image, _ = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    image.status = "downloaded"
    repo.persist_analysis(
        image,
        ImageAnalysisResult(
            image_ref="img_0001",
            contains_target=True,
            items=[
                DetectedItem("modern_camera", "mirrorless camera", 0.9, 0.8, "Sony", "visible body")
            ],
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


def test_watchlist_routing_by_category() -> None:
    golf = _profile("golf_camera", ["golf_bag", "modern_camera"])
    jewelry = _profile("perfume_jewelry", ["collectible_perfume_bottle", "jewelry"])

    assert matching_watchlists("golf_bag", [golf, jewelry]) == [golf]
    assert matching_watchlists("jewelry", [golf, jewelry]) == [jewelry]
    assert matching_watchlists("modern_camera", [golf, jewelry]) == [golf]
    assert matching_watchlists("legacy_category", [golf, jewelry]) == []


def test_pending_notifications_are_per_watchlist_and_recipient() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, _, _ = repo.upsert_sale(_sale())
    image, _ = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    image.status = "downloaded"
    repo.persist_analysis(
        image,
        ImageAnalysisResult(
            image_ref="img_0001",
            contains_target=True,
            items=[
                DetectedItem("golf_bag", "golf bag", 0.9, 0.0, None, "visible"),
                DetectedItem("jewelry", "rings", 0.9, 0.0, None, "visible"),
            ],
            provider="mock",
            model_name="mock",
            prompt_version="mock",
        ),
        analysis_version="v1",
    )
    golf = _profile("golf_camera", ["golf_bag"])
    jewelry = _profile("perfume_jewelry", ["jewelry"])
    repo.sync_watchlists([golf, jewelry])
    session.commit()

    golf_pending = repo.pending_detections_for_watchlist(golf, "golf@example.test", limit=10)
    jewelry_pending = repo.pending_detections_for_watchlist(
        jewelry, "jewelry@example.test", limit=10
    )

    assert [detection.category for detection in golf_pending] == ["golf_bag"]
    assert [detection.category for detection in jewelry_pending] == ["jewelry"]

    repo.mark_notifications_sent(
        golf_pending,
        watchlist_id=golf.id,
        recipient="golf@example.test",
        email_run_id=None,
    )
    session.commit()

    assert repo.pending_detections_for_watchlist(golf, "golf@example.test", limit=10) == []
    assert repo.pending_detections_for_watchlist(golf, "other@example.test", limit=10)


def test_same_detection_can_be_sent_to_multiple_matching_watchlists() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, _, _ = repo.upsert_sale(_sale())
    image, _ = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    image.status = "downloaded"
    repo.persist_analysis(
        image,
        ImageAnalysisResult(
            image_ref="img_0001",
            contains_target=True,
            items=[DetectedItem("jewelry", "rings", 0.9, 0.0, None, "visible")],
            provider="mock",
            model_name="mock",
            prompt_version="mock",
        ),
        analysis_version="v1",
    )
    first = _profile("perfume_jewelry", ["jewelry"])
    second = _profile("collector", ["jewelry"])
    repo.sync_watchlists([first, second])
    session.commit()

    assert repo.pending_detections_for_watchlist(first, "a@example.test", limit=10)
    assert repo.pending_detections_for_watchlist(second, "b@example.test", limit=10)


def test_legacy_email_state_is_seeded_for_primary_watchlist_only() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, _, _ = repo.upsert_sale(_sale())
    image, _ = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    detection = DetectionORM(
        image_id=image.id,
        category="modern_camera",
        label="camera",
        confidence=0.9,
        modern_likelihood=0.8,
        visible_brand=None,
        notes=None,
        model_provider="mock",
        model_name="mock",
        prompt_version="old",
        analysis_version="old",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        included_in_email=True,
        email_sent_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    session.add(detection)
    golf = _profile("golf_camera", ["modern_camera"], recipients=("legacy@example.test",))
    other = _profile("new_camera_watch", ["modern_camera"], recipients=("new@example.test",))
    repo.sync_watchlists([golf, other])
    repo.seed_legacy_notification_state([golf, other])
    session.commit()

    notifications = list(session.query(DetectionNotificationORM).all())

    assert [(row.watchlist_id, row.recipient_email) for row in notifications] == [
        ("golf_camera", "legacy@example.test")
    ]
    assert repo.pending_detections_for_watchlist(golf, "legacy@example.test", limit=10) == []
    assert repo.pending_detections_for_watchlist(other, "new@example.test", limit=10)


def test_unknown_detection_categories_are_not_persisted() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, _, _ = repo.upsert_sale(_sale())
    image, _ = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    image.status = "downloaded"
    positives = repo.persist_analysis(
        image,
        ImageAnalysisResult(
            image_ref="img_0001",
            contains_target=True,
            items=[
                DetectedItem(
                    "unexpected_category", "non-target item", 0.9, 0.0, None, "not target"
                ),
                DetectedItem("legacy_category", "non-target item", 0.8, 0.0, None, "not target"),
            ],
            provider="mock",
            model_name="mock",
            prompt_version="mock",
        ),
        analysis_version="v1",
    )
    assert positives == 0
    assert repo.unemailable_detections(limit=10) == []


def test_unapproved_existing_detections_are_not_emailed() -> None:
    session = _session()
    repo = Repository(session)
    sale_orm, _, _ = repo.upsert_sale(_sale())
    image, _ = repo.upsert_image(sale_orm, SalePicture(None, "https://example.test/a.jpg"))
    detection = DetectionORM(
        image_id=image.id,
        category="legacy_category",
        label="not approved",
        confidence=0.9,
        modern_likelihood=0.0,
        visible_brand=None,
        notes=None,
        model_provider="mock",
        model_name="mock",
        prompt_version="old",
        analysis_version="old",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        included_in_email=False,
    )
    session.add(detection)
    session.commit()

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


def _profile(
    watchlist_id: str,
    targets: list[str],
    *,
    recipients: tuple[str, ...] = ("user@example.test",),
) -> WatchlistProfile:
    return WatchlistProfile(
        id=watchlist_id,
        name=watchlist_id,
        recipients=recipients,
        targets=frozenset(targets),
        config_hash=watchlist_id,
    )
