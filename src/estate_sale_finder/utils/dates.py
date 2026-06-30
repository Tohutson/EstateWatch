from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return ensure_utc(datetime.fromisoformat(normalized))


def decode_datetime_wrappers(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("_type") == "DateTime" and isinstance(value.get("_value"), str):
            return parse_datetime(value["_value"])
        return {key: decode_datetime_wrappers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_datetime_wrappers(item) for item in value]
    return value


def overlaps_window(
    start_at: datetime, end_at: datetime, window_start: datetime, window_end: datetime
) -> bool:
    return ensure_utc(end_at) >= ensure_utc(window_start) and ensure_utc(start_at) <= ensure_utc(
        window_end
    )
