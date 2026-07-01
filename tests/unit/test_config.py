from __future__ import annotations

from pathlib import Path

import pytest

from estate_sale_finder.config import Settings


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
