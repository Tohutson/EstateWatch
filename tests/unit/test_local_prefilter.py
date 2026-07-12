from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from estate_sale_finder.analysis.local_prefilter import (
    OpenClipPrefilter,
    assert_open_clip_available,
)


def test_assert_open_clip_available_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> object:
        if name == "torch":
            raise ImportError("No module named 'torch'")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    with pytest.raises(RuntimeError, match="LOCAL_PREFILTER_ENABLED=true requires"):
        assert_open_clip_available()


def test_open_clip_prefilter_unavailable_error_is_cached(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = 0
    prefilter = OpenClipPrefilter("ViT-B-32/laion2b_s34b_b79k", 0.95)

    def fail_score(image_path: Path) -> float:
        nonlocal calls
        calls += 1
        raise ImportError("No module named 'torch'")

    monkeypatch.setattr(prefilter, "_score_with_open_clip", fail_score)

    assert prefilter.score(tmp_path / "image-1.jpg") == (True, 1.0)
    assert prefilter.score(tmp_path / "image-2.jpg") == (True, 1.0)
    assert calls == 1
