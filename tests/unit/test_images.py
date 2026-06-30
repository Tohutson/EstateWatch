from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from estate_sale_finder.images.hashing import sha256_bytes
from estate_sale_finder.images.processing import process_image_bytes, validate_content_type


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "red").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_sha256_hashing() -> None:
    assert (
        sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_process_image_creates_thumbnail_and_phash(tmp_path: Path) -> None:
    processed = process_image_bytes(
        _jpeg_bytes(),
        mime_type="image/jpeg",
        max_pixels=1000,
        thumbnails_dir=tmp_path / "thumbs",
        images_dir=tmp_path / "images",
        keep_original=False,
        filename_stem="sample",
    )
    assert processed.thumbnail_path.exists()
    assert len(processed.perceptual_hash) == 16
    assert processed.width == 20


def test_reject_content_type() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        validate_content_type("text/html")
