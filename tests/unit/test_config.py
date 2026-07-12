from __future__ import annotations

import json
from pathlib import Path

import pytest

from estate_sale_finder.config import Settings
from estate_sale_finder.watchlists import WatchlistConfigError, load_watchlists


def test_csv_settings_parse(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        allowed_sale_types="EstateSales,MovingSales",
        email_to="a@b.test",
    )
    assert settings.allowed_sale_types == ["EstateSales", "MovingSales"]
    assert settings.email_to == ["a@b.test"]


def test_email_validation_requires_smtp(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Missing email settings"):
        Settings(_env_file=None, data_dir=tmp_path, email_enabled=True)


def test_openai_requires_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="VISION_API_KEY"):
        Settings(_env_file=None, data_dir=tmp_path, analysis_provider="openai")


def test_vision_retry_settings_are_bounded(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)
    assert settings.vision_batch_size == 4
    assert settings.vision_max_batch_attempts == 2
    assert settings.vision_max_single_image_attempts == 2
    assert settings.vision_retry_backoff_seconds == 1.0

    with pytest.raises(ValueError, match="Vision retry settings"):
        Settings(_env_file=None, data_dir=tmp_path, vision_max_single_image_attempts=0)


def test_valid_two_watchlist_config_loads(tmp_path: Path) -> None:
    path = _write_watchlists(tmp_path)
    settings = Settings(_env_file=None, data_dir=tmp_path, watchlist_config_path=path)

    profiles = load_watchlists(settings, require_recipients=True)

    assert [profile.id for profile in profiles] == ["golf_camera", "perfume_jewelry"]
    assert profiles[1].targets == frozenset({"collectible_perfume_bottle", "jewelry"})


def test_duplicate_watchlist_ids_fail(tmp_path: Path) -> None:
    path = _write_watchlists(
        tmp_path,
        [
            _watchlist("same", ["golf_bag"]),
            _watchlist("same", ["jewelry"]),
        ],
    )
    settings = Settings(_env_file=None, data_dir=tmp_path, watchlist_config_path=path)

    with pytest.raises(WatchlistConfigError, match="Duplicate watchlist id"):
        load_watchlists(settings)


def test_invalid_category_fails(tmp_path: Path) -> None:
    path = _write_watchlists(tmp_path, [_watchlist("bad", ["frying_pan"])])
    settings = Settings(_env_file=None, data_dir=tmp_path, watchlist_config_path=path)

    with pytest.raises(WatchlistConfigError, match="invalid target"):
        load_watchlists(settings)


def test_empty_recipients_fail_when_required(tmp_path: Path) -> None:
    path = _write_watchlists(tmp_path, [_watchlist("empty", ["jewelry"], recipients=[])])
    settings = Settings(_env_file=None, data_dir=tmp_path, watchlist_config_path=path)

    with pytest.raises(WatchlistConfigError, match="recipient"):
        load_watchlists(settings, require_recipients=True)


def test_empty_targets_fail(tmp_path: Path) -> None:
    path = _write_watchlists(tmp_path, [_watchlist("empty", [])])
    settings = Settings(_env_file=None, data_dir=tmp_path, watchlist_config_path=path)

    with pytest.raises(WatchlistConfigError, match="at least one target"):
        load_watchlists(settings)


def test_missing_config_path_fails_clearly(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        watchlist_config_path=tmp_path / "missing.json",
    )

    with pytest.raises(WatchlistConfigError, match="does not exist"):
        load_watchlists(settings)


def test_legacy_fallback_uses_email_to(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path, email_to="legacy@example.test")

    profiles = load_watchlists(settings, require_recipients=True)

    assert len(profiles) == 1
    assert profiles[0].id == "golf_camera"
    assert profiles[0].recipients == ("legacy@example.test",)
    assert "modern_camera" in profiles[0].targets


def test_config_hash_changes_when_targets_change(tmp_path: Path) -> None:
    first = _write_watchlists(tmp_path, [_watchlist("one", ["jewelry"])], filename="a.json")
    second = _write_watchlists(
        tmp_path,
        [_watchlist("one", ["jewelry", "collectible_perfume_bottle"])],
        filename="b.json",
    )

    first_hash = load_watchlists(
        Settings(_env_file=None, data_dir=tmp_path, watchlist_config_path=first)
    )[0].config_hash
    second_hash = load_watchlists(
        Settings(_env_file=None, data_dir=tmp_path, watchlist_config_path=second)
    )[0].config_hash

    assert first_hash != second_hash


def _write_watchlists(
    tmp_path: Path,
    watchlists: list[dict[str, object]] | None = None,
    *,
    filename: str = "watchlists.json",
) -> Path:
    path = tmp_path / filename
    path.write_text(
        json.dumps(
            {
                "watchlists": watchlists
                or [
                    _watchlist(
                        "golf_camera",
                        [
                            "golf_clubs",
                            "golf_bag",
                            "golf_balls",
                            "modern_camera",
                            "modern_camera_lens",
                        ],
                        name="Golf and Camera Finds",
                    ),
                    _watchlist(
                        "perfume_jewelry",
                        ["collectible_perfume_bottle", "jewelry"],
                        name="Perfume and Jewelry Finds",
                    ),
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _watchlist(
    watchlist_id: str,
    targets: list[str],
    *,
    name: str = "Test Watchlist",
    recipients: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": watchlist_id,
        "name": name,
        "recipients": recipients if recipients is not None else ["user@example.test"],
        "targets": targets,
        "send_on_no_matches": False,
    }
