from __future__ import annotations

from datetime import UTC, datetime

from jinja2 import Environment, PackageLoader, select_autoescape

from estate_sale_finder.db.models import DetectionORM, ImageORM, SaleORM
from estate_sale_finder.notifications.smtp import render_digest


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
            prompt_version="targets-v2",
            analysis_version="golf-camera-v2",
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
            prompt_version="targets-v2",
            analysis_version="golf-camera-v2",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
            included_in_email=False,
        ),
    ]
    env = Environment(
        loader=PackageLoader("estate_sale_finder.notifications", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )

    rendered = render_digest(env, detections)

    assert rendered.cid_paths == {}
    assert "Estate sale with targets" in rendered.text
    assert "12.3 mi" in rendered.text
    assert "golf_balls: visible golf balls (confidence 91%)" in rendered.text
    assert "modern_camera_lens: interchangeable zoom lens" in rendered.text
    assert "modern 84%" in rendered.text
