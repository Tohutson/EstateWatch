from __future__ import annotations

import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .hashing import perceptual_hash, sha256_bytes

SUPPORTED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


@dataclass(frozen=True)
class ProcessedImage:
    sha256: str
    perceptual_hash: str
    width: int
    height: int
    mime_type: str
    thumbnail_path: Path
    original_path: Path | None


def validate_content_type(content_type: str | None) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in SUPPORTED_MIME_TYPES:
        raise ValueError(f"Unsupported image content type: {content_type}")
    return mime


def process_image_bytes(
    data: bytes,
    *,
    mime_type: str,
    max_pixels: int,
    thumbnails_dir: Path,
    images_dir: Path,
    keep_original: bool,
    filename_stem: str,
) -> ProcessedImage:
    if not data:
        raise ValueError("Empty image response")
    sha = sha256_bytes(data)
    try:
        with Image.open(BytesIO(data)) as original:
            if original.format not in SUPPORTED_FORMATS:
                raise ValueError(f"Unsupported image format: {original.format}")
            width, height = original.size
            if width * height > max_pixels:
                raise ValueError(f"Image has too many pixels: {width}x{height}")
            image = ImageOps.exif_transpose(original).convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError("Invalid image data") from exc

    phash = perceptual_hash(image)
    thumbnail_path = thumbnails_dir / f"{filename_stem}.jpg"
    _atomic_save_jpeg(image, thumbnail_path, max_size=(640, 640), quality=82)

    original_path: Path | None = None
    if keep_original:
        original_path = images_dir / f"{sha}.jpg"
        _atomic_save_jpeg(image, original_path, quality=90)

    return ProcessedImage(
        sha256=sha,
        perceptual_hash=phash,
        width=image.width,
        height=image.height,
        mime_type=mime_type,
        thumbnail_path=thumbnail_path,
        original_path=original_path,
    )


def _atomic_save_jpeg(
    image: Image.Image,
    path: Path,
    *,
    max_size: tuple[int, int] | None = None,
    quality: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    working = image.copy()
    if max_size:
        working.thumbnail(max_size)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp)
    try:
        with open(fd, "wb", closefd=True) as handle:
            working.save(handle, format="JPEG", quality=quality, optimize=True)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
