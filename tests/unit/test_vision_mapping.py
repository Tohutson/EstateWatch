from __future__ import annotations

import pytest

from estate_sale_finder.analysis.errors import VisionResponseMappingError
from estate_sale_finder.analysis.mapping import validate_vision_result_mapping
from estate_sale_finder.domain.models import ImageAnalysisResult


def _result(image_ref: object) -> ImageAnalysisResult:
    return ImageAnalysisResult(
        image_ref=str(image_ref),
        contains_target=False,
        items=[],
        provider="test",
        model_name="test",
        prompt_version="test",
    )


def test_exact_matching_references_succeed() -> None:
    mapped = validate_vision_result_mapping({"img_0001": 1}, [_result("img_0001")])

    assert mapped == [(1, _result("img_0001"))]


def test_controlled_string_normalization_succeeds() -> None:
    mapped = validate_vision_result_mapping({"1": 1}, [_result(1)])

    assert mapped == [(1, _result("1"))]


def test_missing_reference_fails() -> None:
    with pytest.raises(VisionResponseMappingError) as exc_info:
        validate_vision_result_mapping({"img_0001": 1, "img_0002": 2}, [_result("img_0001")])

    assert exc_info.value.missing_refs == {"img_0002"}


def test_unexpected_reference_fails() -> None:
    with pytest.raises(VisionResponseMappingError) as exc_info:
        validate_vision_result_mapping(
            {"img_0001": 1},
            [_result("img_unknown")],
            allow_single_image_correction=False,
        )

    assert exc_info.value.unexpected_refs == {"img_unknown"}


def test_duplicate_reference_fails() -> None:
    with pytest.raises(VisionResponseMappingError) as exc_info:
        validate_vision_result_mapping(
            {"img_0001": 1, "img_0002": 2},
            [_result("img_0001"), _result("img_0001")],
        )

    assert exc_info.value.duplicate_refs == {"img_0001"}


def test_too_many_results_fails_even_if_refs_are_expected() -> None:
    with pytest.raises(VisionResponseMappingError):
        validate_vision_result_mapping({"img_0001": 1}, [_result("img_0001"), _result("img_0001")])


def test_empty_response_fails_for_non_empty_batch() -> None:
    with pytest.raises(VisionResponseMappingError):
        validate_vision_result_mapping({"img_0001": 1}, [])


def test_result_order_does_not_matter() -> None:
    mapped = validate_vision_result_mapping(
        {"img_0001": 1, "img_0002": 2},
        [_result("img_0002"), _result("img_0001")],
    )

    assert mapped == [(2, _result("img_0002")), (1, _result("img_0001"))]


def test_multi_image_positional_fallback_is_never_used() -> None:
    with pytest.raises(VisionResponseMappingError):
        validate_vision_result_mapping(
            {"img_0001": 1, "img_0002": 2},
            [_result("img_0002"), _result("img_unknown")],
        )


def test_single_image_correction_is_allowed_only_when_unambiguous() -> None:
    corrected = validate_vision_result_mapping({"img_0001": 1}, [_result("wrong_ref")])

    assert corrected == [(1, _result("img_0001"))]

    with pytest.raises(VisionResponseMappingError):
        validate_vision_result_mapping(
            {"img_0001": 1},
            [_result("wrong_ref"), _result("another_wrong_ref")],
        )
