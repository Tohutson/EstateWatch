from __future__ import annotations

import logging
from collections import Counter
from dataclasses import replace

from estate_sale_finder.analysis.errors import VisionResponseMappingError, VisionResponseParseError
from estate_sale_finder.domain.models import APPROVED_TARGET_CATEGORIES, ImageAnalysisResult

logger = logging.getLogger(__name__)


def validate_vision_result_mapping[T](
    reference_to_image: dict[str, T],
    results: list[ImageAnalysisResult],
    *,
    log_context: dict[str, object] | None = None,
    allow_single_image_correction: bool = True,
) -> list[tuple[T, ImageAnalysisResult]]:
    expected_refs = set(reference_to_image)
    returned_refs = [str(result.image_ref) for result in results]
    counts = Counter(returned_refs)
    missing_refs = expected_refs - set(returned_refs)
    unexpected_refs = set(returned_refs) - expected_refs
    duplicate_refs = {ref for ref, count in counts.items() if count > 1}

    if (
        allow_single_image_correction
        and len(expected_refs) == 1
        and len(results) == 1
        and (missing_refs or unexpected_refs)
        and not duplicate_refs
    ):
        expected_ref = next(iter(expected_refs))
        returned_ref = returned_refs[0] if returned_refs else None
        logger.warning(
            "vision_single_result_ref_corrected",
            extra={
                **(log_context or {}),
                "expected_ref": expected_ref,
                "returned_ref": returned_ref,
            },
        )
        results = [replace(results[0], image_ref=expected_ref)]
        returned_refs = [expected_ref]
        missing_refs = set()
        unexpected_refs = set()

    if (
        len(returned_refs) != len(expected_refs)
        or missing_refs
        or unexpected_refs
        or duplicate_refs
    ):
        raise VisionResponseMappingError(
            expected_refs=expected_refs,
            returned_refs=returned_refs,
            missing_refs=missing_refs,
            unexpected_refs=unexpected_refs,
            duplicate_refs=duplicate_refs,
        )

    for result in results:
        if result.contains_target != bool(result.items):
            raise VisionResponseParseError(
                "contains_target must match whether approved items are present"
            )
        unexpected_categories = {
            item.category
            for item in result.items
            if item.category not in APPROVED_TARGET_CATEGORIES
        }
        if unexpected_categories:
            raise VisionResponseParseError(
                "Vision result contained unexpected categories: "
                + ", ".join(sorted(unexpected_categories))
            )

    return [(reference_to_image[str(result.image_ref)], result) for result in results]
