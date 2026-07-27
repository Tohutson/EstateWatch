from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DateTimeWindow:
    start_at: datetime
    end_at: datetime


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
    return ensure_utc(end_at) > ensure_utc(window_start) and ensure_utc(start_at) < ensure_utc(
        window_end
    )


def sale_search_window(
    now: datetime,
    *,
    mode: str,
    timezone_name: str,
    lookahead_days: int,
) -> DateTimeWindow:
    now_utc = ensure_utc(now)
    if mode == "rolling":
        return DateTimeWindow(now_utc, now_utc + timedelta(days=lookahead_days))
    if mode != "upcoming_weekend":
        raise ValueError(f"Unsupported sale window mode: {mode}")

    timezone = ZoneInfo(timezone_name)
    local_now = now_utc.astimezone(timezone)
    thursday = _current_or_next_thursday(local_now.date())
    start_local = datetime.combine(thursday, time.min, tzinfo=timezone)
    end_local = datetime.combine(thursday + timedelta(days=4), time.min, tzinfo=timezone)
    return DateTimeWindow(start_local.astimezone(UTC), end_local.astimezone(UTC))


def _current_or_next_thursday(current_date: date) -> date:
    thursday_weekday = 3
    if current_date.weekday() <= thursday_weekday:
        days_until_thursday = thursday_weekday - current_date.weekday()
        return current_date + timedelta(days=days_until_thursday)
    return current_date - timedelta(days=current_date.weekday() - thursday_weekday)
