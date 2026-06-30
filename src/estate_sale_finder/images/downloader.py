from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from estate_sale_finder.config import Settings
from estate_sale_finder.db.models import ImageORM
from estate_sale_finder.utils.dates import utc_now

from .processing import process_image_bytes, validate_content_type

logger = logging.getLogger(__name__)


class ImageDownloader:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent, "Accept": "image/*"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def download_into_record(self, image: ImageORM) -> None:
        try:
            data, content_type = self._download(image.source_url)
            mime_type = validate_content_type(content_type)
            processed = process_image_bytes(
                data,
                mime_type=mime_type,
                max_pixels=self.settings.max_image_pixels,
                thumbnails_dir=self.settings.thumbnails_dir,
                images_dir=self.settings.images_dir,
                keep_original=self.settings.keep_original_images,
                filename_stem=f"image-{image.id}",
            )
            image.sha256 = processed.sha256
            image.perceptual_hash = processed.perceptual_hash
            image.width = processed.width
            image.height = processed.height
            image.mime_type = processed.mime_type
            image.local_thumbnail_path = str(processed.thumbnail_path)
            image.local_original_path = (
                str(processed.original_path) if processed.original_path else None
            )
            image.downloaded_at = utc_now()
            image.status = "downloaded"
            image.error_message = None
        except Exception as exc:
            image.status = "error"
            image.error_message = str(exc)
            logger.warning("image_download_failed", extra={"image_id": image.id, "error": str(exc)})

    def _download(self, url: str) -> tuple[bytes, str | None]:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.http_max_retries + 1):
            try:
                with self.client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type")
                    total = 0
                    chunks: list[bytes] = []
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.settings.max_image_bytes:
                            raise ValueError("Image exceeds MAX_IMAGE_BYTES")
                        chunks.append(chunk)
                    return b"".join(chunks), content_type
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "image_download_retry",
                    extra={"url": url, "attempt": attempt, "error": str(exc)},
                )
                if attempt < self.settings.http_max_retries:
                    time.sleep(min(8.0, 0.5 * 2 ** (attempt - 1)))
        raise RuntimeError(f"Image download failed: {last_error}") from last_error


def thumbnail_bytes(path: str | Path) -> bytes:
    return Path(path).read_bytes()
