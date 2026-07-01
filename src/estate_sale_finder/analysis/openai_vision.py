from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from estate_sale_finder.analysis.base import AnalysisImage
from estate_sale_finder.analysis.prompts import (
    VISION_RESPONSE_SCHEMA,
    VISION_SYSTEM_PROMPT,
    VISION_USER_PROMPT,
)
from estate_sale_finder.config import Settings
from estate_sale_finder.domain.models import DetectedItem, ImageAnalysisResult

logger = logging.getLogger(__name__)


class ItemPayload(BaseModel):
    category: str
    label: str
    confidence: float = Field(ge=0, le=1)
    modern_likelihood: float = Field(ge=0, le=1)
    visible_brand: str | None
    notes: str | None


class ResultPayload(BaseModel):
    image_id: int
    contains_target: bool
    items: list[ItemPayload]


class ResponsePayload(BaseModel):
    results: list[ResultPayload]


class OpenAIVisionProvider:
    provider_name = "openai"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if not settings.vision_api_key:
            raise ValueError("VISION_API_KEY is required for OpenAI vision provider")
        self.settings = settings
        self.model_name = settings.vision_model
        self.client = client or httpx.Client(
            base_url="https://api.openai.com/v1",
            timeout=settings.http_timeout_seconds,
            headers={
                "Authorization": f"Bearer {settings.vision_api_key}",
                "Content-Type": "application/json",
            },
        )

    def analyze(self, images: list[AnalysisImage]) -> list[ImageAnalysisResult]:
        if not images:
            return []
        return self._analyze_batch(images)

    def _analyze_batch(self, images: list[AnalysisImage]) -> list[ImageAnalysisResult]:
        payload = self._request_payload(images)
        last_error: Exception | None = None
        for attempt in range(1, self.settings.http_max_retries + 1):
            try:
                response = self.client.post("/responses", json=payload)
                response.raise_for_status()
                parsed = _parse_response(response.json())
                return _to_results(
                    parsed,
                    provider=self.provider_name,
                    model=self.model_name,
                    prompt_version=self.settings.prompt_version,
                )
            except (
                httpx.HTTPError,
                ValidationError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                logger.warning("vision_retry", extra={"attempt": attempt, "error": str(exc)})
                if attempt < self.settings.http_max_retries:
                    time.sleep(min(8.0, 0.5 * 2 ** (attempt - 1)))
        if len(images) > 1:
            results: list[ImageAnalysisResult] = []
            for image in images:
                results.extend(self._analyze_batch([image]))
            return results
        raise RuntimeError(f"OpenAI vision analysis failed: {last_error}") from last_error

    def _request_payload(self, images: list[AnalysisImage]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": VISION_USER_PROMPT}]
        for image in images:
            content.append({"type": "input_text", "text": f"image_id={image.image_id}"})
            content.append(
                {
                    "type": "input_image",
                    "image_url": _data_url(image.thumbnail_path),
                    "detail": "low",
                }
            )
        return {
            "model": self.model_name,
            "store": False,
            "instructions": VISION_SYSTEM_PROMPT,
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "estate_sale_image_results",
                    "strict": True,
                    "schema": VISION_RESPONSE_SCHEMA,
                }
            },
        }


def _data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _parse_response(payload: dict[str, Any]) -> ResponsePayload:
    text = payload.get("output_text")
    if not text:
        text = _find_text(payload.get("output", []))
    if not isinstance(text, str):
        raise ValueError("OpenAI response did not contain output text")
    return ResponsePayload.model_validate_json(text)


def _find_text(output: Any) -> str | None:
    if isinstance(output, list):
        for item in output:
            found = _find_text(item)
            if found:
                return found
    if isinstance(output, dict):
        if output.get("type") in {"output_text", "text"} and isinstance(output.get("text"), str):
            text: str = output["text"]
            return text
        return _find_text(output.get("content"))
    return None


def _to_results(
    parsed: ResponsePayload,
    *,
    provider: str,
    model: str,
    prompt_version: str,
) -> list[ImageAnalysisResult]:
    return [
        ImageAnalysisResult(
            image_id=result.image_id,
            contains_target=result.contains_target,
            items=[
                DetectedItem(
                    category=item.category,
                    label=item.label,
                    confidence=item.confidence,
                    modern_likelihood=item.modern_likelihood,
                    visible_brand=item.visible_brand,
                    notes=item.notes,
                )
                for item in result.items
            ],
            provider=provider,
            model_name=model,
            prompt_version=prompt_version,
        )
        for result in parsed.results
    ]
