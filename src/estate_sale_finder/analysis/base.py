from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from estate_sale_finder.domain.models import ImageAnalysisResult


@dataclass(frozen=True)
class AnalysisImage:
    image_id: int
    thumbnail_path: Path
    source_url: str


class VisionProvider(Protocol):
    provider_name: str
    model_name: str

    def analyze(self, images: list[AnalysisImage]) -> list[ImageAnalysisResult]: ...


class LocalPrefilter(Protocol):
    def score(self, image_path: Path) -> tuple[bool, float]: ...
