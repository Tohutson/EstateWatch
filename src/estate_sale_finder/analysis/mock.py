from __future__ import annotations

from estate_sale_finder.analysis.base import AnalysisImage
from estate_sale_finder.domain.models import DetectedItem, ImageAnalysisResult


class MockVisionProvider:
    provider_name = "mock"
    model_name = "mock-vision"

    def analyze(self, images: list[AnalysisImage]) -> list[ImageAnalysisResult]:
        results: list[ImageAnalysisResult] = []
        for image in images:
            if "positive" in image.thumbnail_path.name or "match" in image.source_url:
                items = [
                    DetectedItem(
                        category="camera",
                        label="digital camera equipment",
                        confidence=0.9,
                        modern_likelihood=0.8,
                        visible_brand=None,
                        notes="Mock positive result",
                    )
                ]
            else:
                items = []
            results.append(
                ImageAnalysisResult(
                    image_id=image.image_id,
                    contains_target=bool(items),
                    items=items,
                    provider=self.provider_name,
                    model_name=self.model_name,
                    prompt_version="mock",
                )
            )
        return results
