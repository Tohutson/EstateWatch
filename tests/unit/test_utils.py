from __future__ import annotations

from datetime import UTC, datetime, timedelta

from estate_sale_finder.utils.dates import (
    decode_datetime_wrappers,
    overlaps_window,
    sale_search_window,
)
from estate_sale_finder.utils.geo import haversine_miles
from estate_sale_finder.utils.urls import normalize_url


def test_decode_datetime_wrappers_recursive() -> None:
    decoded = decode_datetime_wrappers(
        {"outer": [{"_type": "DateTime", "_value": "2026-07-03T13:00:00Z"}]}
    )
    assert decoded["outer"][0] == datetime(2026, 7, 3, 13, tzinfo=UTC)


def test_haversine_distance_buffalo_to_rochester() -> None:
    distance = haversine_miles(42.8864, -78.8784, 43.1566, -77.6088)
    assert 65 < distance < 75


def test_date_window_overlap() -> None:
    now = datetime(2026, 6, 30, tzinfo=UTC)
    assert overlaps_window(
        now + timedelta(days=1), now + timedelta(days=2), now, now + timedelta(days=15)
    )
    assert not overlaps_window(
        now + timedelta(days=20),
        now + timedelta(days=21),
        now,
        now + timedelta(days=15),
    )
    assert not overlaps_window(
        now - timedelta(days=1),
        now,
        now,
        now + timedelta(days=15),
    )
    assert not overlaps_window(
        now + timedelta(days=15),
        now + timedelta(days=16),
        now,
        now + timedelta(days=15),
    )


def test_upcoming_weekend_window_from_wednesday() -> None:
    window = sale_search_window(
        datetime(2026, 7, 29, 13, tzinfo=UTC),
        mode="upcoming_weekend",
        timezone_name="America/New_York",
        lookahead_days=15,
    )

    assert window.start_at == datetime(2026, 7, 30, 4, tzinfo=UTC)
    assert window.end_at == datetime(2026, 8, 3, 4, tzinfo=UTC)


def test_upcoming_weekend_window_uses_current_weekend_after_thursday() -> None:
    window = sale_search_window(
        datetime(2026, 8, 2, 14, tzinfo=UTC),
        mode="upcoming_weekend",
        timezone_name="America/New_York",
        lookahead_days=15,
    )

    assert window.start_at == datetime(2026, 7, 30, 4, tzinfo=UTC)
    assert window.end_at == datetime(2026, 8, 3, 4, tzinfo=UTC)


def test_rolling_sale_window_preserves_configured_lookahead() -> None:
    now = datetime(2026, 7, 29, 13, tzinfo=UTC)

    window = sale_search_window(
        now,
        mode="rolling",
        timezone_name="America/New_York",
        lookahead_days=7,
    )

    assert window.start_at == now
    assert window.end_at == now + timedelta(days=7)


def test_url_normalization() -> None:
    assert normalize_url("HTTPS://Example.COM/a?b=2&a=1#frag") == "https://example.com/a?a=1&b=2"
