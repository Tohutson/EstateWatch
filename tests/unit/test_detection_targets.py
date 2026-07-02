from __future__ import annotations

import json

import pytest

from estate_sale_finder.analysis.errors import VisionResponseParseError
from estate_sale_finder.analysis.openai_vision import _parse_response
from estate_sale_finder.analysis.prompts import VISION_RESPONSE_SCHEMA
from estate_sale_finder.domain.models import APPROVED_TARGET_CATEGORIES, CAMERA_TARGET_CATEGORIES


def test_prompt_schema_allows_only_approved_categories() -> None:
    enum_values = set(
        VISION_RESPONSE_SCHEMA["properties"]["results"]["items"]["properties"]["items"]["items"][
            "properties"
        ]["category"]["enum"]
    )

    assert enum_values == APPROVED_TARGET_CATEGORIES
    assert enum_values == {
        "golf_clubs",
        "golf_bag",
        "golf_balls",
        "modern_camera",
        "modern_camera_lens",
    }


def test_openai_response_accepts_each_approved_category() -> None:
    payload = {
        "output_text": json.dumps(
            {
                "results": [
                    {
                        "image_ref": f"img_{index:04d}",
                        "contains_target": True,
                        "items": [
                            {
                                "category": category,
                                "label": "visible target",
                                "confidence": 0.9,
                                "modern_likelihood": 0.8
                                if category in CAMERA_TARGET_CATEGORIES
                                else 0.0,
                                "visible_brand": None,
                                "notes": "clear physical object",
                            }
                        ],
                    }
                    for index, category in enumerate(sorted(APPROVED_TARGET_CATEGORIES), start=1)
                ]
            }
        )
    }

    parsed = _parse_response(payload)

    assert {result.items[0].category for result in parsed.results} == APPROVED_TARGET_CATEGORIES


def test_openai_response_rejects_unexpected_category() -> None:
    payload = {
        "output_text": json.dumps(
            {
                "results": [
                    {
                        "image_ref": "img_0001",
                        "contains_target": True,
                        "items": [
                            {
                                "category": "unexpected_category",
                                "label": "not approved",
                                "confidence": 0.9,
                                "modern_likelihood": 0.0,
                                "visible_brand": None,
                                "notes": None,
                            }
                        ],
                    }
                ]
            }
        )
    }

    with pytest.raises(VisionResponseParseError):
        _parse_response(payload)


def test_non_match_result_is_explicit() -> None:
    payload = {
        "output_text": json.dumps(
            {"results": [{"image_ref": "img_0001", "contains_target": False, "items": []}]}
        )
    }

    parsed = _parse_response(payload)

    assert parsed.results[0].contains_target is False
    assert parsed.results[0].items == []


def test_openai_response_rejects_missing_image_ref() -> None:
    payload = {"output_text": json.dumps({"results": [{"contains_target": False, "items": []}]})}

    with pytest.raises(VisionResponseParseError):
        _parse_response(payload)
