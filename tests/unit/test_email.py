from __future__ import annotations

from datetime import UTC, datetime

from jinja2 import Environment, PackageLoader, select_autoescape

from estate_sale_finder.db.models import DetectionORM, ImageORM, SaleORM
from estate_sale_finder.notifications.smtp import render_digest
from estate_sale_finder.watchlists import WatchlistProfile


def test_digest_renders_approved_categories_and_missing_thumbnail() -> None:
    sale = SaleORM(
        source="test",
        external_id="1",
        title="Estate sale with targets",
        organization_name=None,
        url="https://example.test/sale/1",
        address=None,
        city="Buffalo",
        state="NY",
        postal_code="14221",
        latitude=43.0,
        longitude=-78.0,
        type="EstateSales",
        picture_count=5,
        first_start_at=datetime(2026, 7, 1, tzinfo=UTC),
        last_end_at=datetime(2026, 7, 2, tzinfo=UTC),
        first_published_at=None,
        remote_modified_at=None,
        latest_pictures_added_count=None,
        first_seen_at=datetime(2026, 6, 30, tzinfo=UTC),
        last_seen_at=datetime(2026, 6, 30, tzinfo=UTC),
        last_gallery_refresh_at=None,
        active=True,
        gallery_status="ok",
        gallery_error=None,
        distance_miles=12.3,
    )
    image = ImageORM(
        sale=sale,
        source_url="https://example.test/image.jpg",
        normalized_url="https://example.test/image.jpg",
        first_seen_at=datetime(2026, 6, 30, tzinfo=UTC),
        local_thumbnail_path="/missing/thumb.jpg",
        status="analyzed",
    )
    detections = [
        DetectionORM(
            image=image,
            category="golf_balls",
            label="visible golf balls",
            confidence=0.91,
            modern_likelihood=0.0,
            visible_brand=None,
            notes="Actual balls are visible.",
            model_provider="mock",
            model_name="mock",
            prompt_version="targets-multi-v1",
            analysis_version="multi-watchlist-v1",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
            included_in_email=False,
        ),
        DetectionORM(
            image=image,
            category="modern_camera_lens",
            label="interchangeable zoom lens",
            confidence=0.88,
            modern_likelihood=0.84,
            visible_brand="Canon",
            notes="A modern autofocus lens is visible.",
            model_provider="mock",
            model_name="mock",
            prompt_version="targets-multi-v1",
            analysis_version="multi-watchlist-v1",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
            included_in_email=False,
        ),
    ]
    env = Environment(
        loader=PackageLoader("estate_sale_finder.notifications", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )

    profile = WatchlistProfile(
        id="golf_camera",
        name="Golf and Camera Finds",
        recipients=("to@example.test",),
        targets=frozenset({"golf_balls", "modern_camera_lens"}),
    )

    rendered = render_digest(env, profile, detections)

    assert rendered.cid_paths == {}
    assert rendered.subject == "EstateWatch: Golf and Camera Finds - 2 new matches"
    assert "Targets: golf_balls, modern_camera_lens" in rendered.text
    assert "Estate sale with targets" in rendered.text
    assert "12.3 mi" in rendered.text
    assert "golf_balls: visible golf balls (confidence 91%)" in rendered.text
    assert "modern_camera_lens: interchangeable zoom lens" in rendered.text
    assert "modern 84%" in rendered.text


def test_digest_body_contains_only_watchlist_relevant_categories() -> None:
    sale = _sale()
    image = ImageORM(
        sale=sale,
        source_url="https://example.test/image.jpg",
        normalized_url="https://example.test/image.jpg",
        first_seen_at=datetime(2026, 6, 30, tzinfo=UTC),
        status="analyzed",
    )
    profile = WatchlistProfile(
        id="perfume_jewelry",
        name="Perfume and Jewelry Finds",
        recipients=("to@example.test",),
        targets=frozenset({"collectible_perfume_bottle", "jewelry"}),
    )
    detections = [
        DetectionORM(
            image=image,
            category="jewelry",
            label="tray of rings",
            confidence=0.92,
            modern_likelihood=0.0,
            visible_brand=None,
            notes="Several rings are visible.",
            model_provider="mock",
            model_name="mock",
            prompt_version="targets-multi-v1",
            analysis_version="multi-watchlist-v1",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
            included_in_email=False,
        )
    ]
    env = Environment(
        loader=PackageLoader("estate_sale_finder.notifications", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )

    rendered = render_digest(env, profile, detections)

    assert "jewelry: tray of rings" in rendered.text
    assert "modern " not in rendered.text
    assert "golf_bag" not in rendered.text
    assert "modern_camera" not in rendered.text


def test_no_match_email_obeys_watchlist_setting() -> None:
    profile = WatchlistProfile(
        id="perfume_jewelry",
        name="Perfume and Jewelry Finds",
        recipients=("to@example.test",),
        targets=frozenset({"collectible_perfume_bottle", "jewelry"}),
        send_on_no_matches=True,
    )
    env = Environment(
        loader=PackageLoader("estate_sale_finder.notifications", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )

    rendered = render_digest(env, profile, [])

    assert rendered.subject == "EstateWatch: Perfume and Jewelry Finds - no new matches"
    assert "No new matches for this watchlist." in rendered.text


def _sale() -> SaleORM:
    return SaleORM(
        source="test",
        external_id="1",
        title="Estate sale with targets",
        organization_name=None,
        url="https://example.test/sale/1",
        address=None,
        city="Buffalo",
        state="NY",
        postal_code="14221",
        latitude=43.0,
        longitude=-78.0,
        type="EstateSales",
        picture_count=5,
        first_start_at=datetime(2026, 7, 1, tzinfo=UTC),
        last_end_at=datetime(2026, 7, 2, tzinfo=UTC),
        first_published_at=None,
        remote_modified_at=None,
        latest_pictures_added_count=None,
        first_seen_at=datetime(2026, 6, 30, tzinfo=UTC),
        last_seen_at=datetime(2026, 6, 30, tzinfo=UTC),
        last_gallery_refresh_at=None,
        active=True,
        gallery_status="ok",
        gallery_error=None,
        distance_miles=12.3,
    )
