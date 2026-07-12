from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from estate_sale_finder.config import Settings
from estate_sale_finder.domain.models import APPROVED_TARGET_CATEGORIES, DEFAULT_TARGET_CATEGORIES

LEGACY_WATCHLIST_ID = "golf_camera"
LEGACY_WATCHLIST_NAME = "Golf and Camera Finds"


class WatchlistConfigError(ValueError):
    pass


@dataclass(frozen=True)
class WatchlistProfile:
    id: str
    name: str
    recipients: tuple[str, ...]
    targets: frozenset[str]
    send_on_no_matches: bool = False
    active: bool = True
    config_hash: str = ""


def load_watchlists(
    settings: Settings,
    *,
    selected_id: str | None = None,
    require_recipients: bool = False,
) -> list[WatchlistProfile]:
    if settings.watchlist_config_path:
        profiles = _load_config_file(settings.watchlist_config_path)
    else:
        profiles = [legacy_watchlist(settings.email_to)]
    if selected_id:
        profiles = [profile for profile in profiles if profile.id == selected_id]
        if not profiles:
            raise WatchlistConfigError(f"Unknown watchlist id: {selected_id}")
    active_profiles = [profile for profile in profiles if profile.active]
    if not active_profiles:
        raise WatchlistConfigError("No active watchlists are configured")
    if require_recipients:
        for profile in active_profiles:
            if not profile.recipients:
                raise WatchlistConfigError(
                    f"Watchlist {profile.id!r} must have at least one recipient"
                )
    return active_profiles


def legacy_watchlist(recipients: list[str] | tuple[str, ...]) -> WatchlistProfile:
    return _profile(
        {
            "id": LEGACY_WATCHLIST_ID,
            "name": LEGACY_WATCHLIST_NAME,
            "recipients": list(recipients),
            "targets": sorted(DEFAULT_TARGET_CATEGORIES),
            "send_on_no_matches": False,
            "active": True,
        }
    )


def active_target_categories(profiles: list[WatchlistProfile]) -> frozenset[str]:
    categories: set[str] = set()
    for profile in profiles:
        categories.update(profile.targets)
    return frozenset(categories)


def validate_email_address(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def _load_config_file(path: Path) -> list[WatchlistProfile]:
    expanded = path.expanduser()
    if not expanded.is_file():
        raise WatchlistConfigError(f"Watchlist config file does not exist: {expanded}")
    if expanded.suffix.lower() != ".json":
        raise WatchlistConfigError("Watchlist config must be JSON; expected a .json file")
    try:
        payload = json.loads(expanded.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WatchlistConfigError(f"Watchlist config is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("watchlists"), list):
        raise WatchlistConfigError("Watchlist config must contain a 'watchlists' array")
    profiles = [_profile(raw) for raw in payload["watchlists"]]
    seen: set[str] = set()
    for profile in profiles:
        if profile.id in seen:
            raise WatchlistConfigError(f"Duplicate watchlist id: {profile.id}")
        seen.add(profile.id)
    return profiles


def _profile(raw: Any) -> WatchlistProfile:
    if not isinstance(raw, dict):
        raise WatchlistConfigError("Each watchlist must be an object")
    watchlist_id = _required_str(raw, "id")
    name = _required_str(raw, "name")
    recipients = _string_list(raw.get("recipients", []), "recipients")
    targets = frozenset(_string_list(raw.get("targets", []), "targets"))
    if not targets:
        raise WatchlistConfigError(f"Watchlist {watchlist_id!r} must include at least one target")
    invalid = sorted(targets - APPROVED_TARGET_CATEGORIES)
    if invalid:
        raise WatchlistConfigError(
            f"Watchlist {watchlist_id!r} has invalid target categories: {', '.join(invalid)}"
        )
    invalid_recipients = [email for email in recipients if not validate_email_address(email)]
    if invalid_recipients:
        raise WatchlistConfigError(
            f"Watchlist {watchlist_id!r} has invalid recipient email addresses"
        )
    active = bool(raw.get("active", True))
    send_on_no_matches = bool(raw.get("send_on_no_matches", False))
    canonical = {
        "id": watchlist_id,
        "name": name,
        "recipients": sorted(recipients),
        "targets": sorted(targets),
        "send_on_no_matches": send_on_no_matches,
        "active": active,
    }
    config_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return WatchlistProfile(
        id=watchlist_id,
        name=name,
        recipients=tuple(recipients),
        targets=targets,
        send_on_no_matches=send_on_no_matches,
        active=active,
        config_hash=config_hash,
    )


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WatchlistConfigError(f"Watchlist field {key!r} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, key: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise WatchlistConfigError(f"Watchlist field {key!r} must be a list")
    values = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise WatchlistConfigError(f"Watchlist field {key!r} must contain only strings")
        values.append(item.strip())
    return tuple(values)
