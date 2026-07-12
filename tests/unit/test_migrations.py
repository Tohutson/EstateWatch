from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from estate_sale_finder.db.migrations import alembic_config, upgrade_to_head
from estate_sale_finder.db.models import DetectionNotificationORM
from estate_sale_finder.db.repository import Repository
from estate_sale_finder.watchlists import WatchlistProfile


def test_fresh_database_migrates_to_watchlist_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    database_url = f"sqlite:///{db_path}"

    upgrade_to_head(database_url)

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    assert "watchlists" in inspector.get_table_names()
    assert "watchlist_targets" in inspector.get_table_names()
    assert "detection_notifications" in inspector.get_table_names()
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("detection_notifications")
    }
    assert "uq_detection_notifications_detection_watchlist_recipient" in unique_constraints


def test_old_emailed_detections_can_seed_primary_watchlist_notifications(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "old.db"
    database_url = f"sqlite:///{db_path}"
    config = alembic_config(database_url)
    command.upgrade(config, "0002_vision_retry_state")
    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into sales (
                    id, source, external_id, title, url, latitude, longitude, type,
                    picture_count, first_start_at, last_end_at, first_seen_at, last_seen_at,
                    active, gallery_status
                )
                values (
                    1, 'test', '1', 'Sale', 'https://example.test/sale/1', 43, -78,
                    'EstateSales', 5, '2026-07-01', '2026-07-02', '2026-06-30',
                    '2026-06-30', 1, 'ok'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                insert into images (
                    id, sale_id, source_url, normalized_url, first_seen_at, status,
                    analysis_attempt_count
                )
                values (
                    1, 1, 'https://example.test/a.jpg', 'https://example.test/a.jpg',
                    '2026-06-30', 'analyzed', 0
                )
                """
            )
        )
        conn.execute(
            text(
                """
                insert into detections (
                    id, image_id, category, label, confidence, modern_likelihood,
                    model_provider, model_name, prompt_version, analysis_version,
                    created_at, included_in_email, email_sent_at
                )
                values (
                    1, 1, 'modern_camera', 'camera', 0.9, 0.8, 'mock', 'mock',
                    'old', 'old', '2026-07-01', 1, '2026-07-02'
                )
                """
            )
        )
    command.upgrade(config, "head")
    factory = sessionmaker(engine, expire_on_commit=False, future=True)
    session = factory()
    repo = Repository(session)
    profile = WatchlistProfile(
        id="golf_camera",
        name="Golf and Camera Finds",
        recipients=("legacy@example.test",),
        targets=frozenset({"modern_camera"}),
        config_hash="test",
    )
    repo.sync_watchlists([profile])
    repo.seed_legacy_notification_state([profile])
    session.commit()

    notifications = list(session.query(DetectionNotificationORM).all())

    assert [(row.detection_id, row.watchlist_id, row.recipient_email) for row in notifications] == [
        (1, "golf_camera", "legacy@example.test")
    ]
    assert notifications[0].sent_at is not None
