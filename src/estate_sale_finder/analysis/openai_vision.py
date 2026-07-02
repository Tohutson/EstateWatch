from __future__ import annotations

import base64
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from estate_sale_finder.analysis.base import AnalysisImage
from estate_sale_finder.analysis.errors import VisionProviderError, VisionResponseParseError
from estate_sale_finder.analysis.prompts import (
    VISION_RESPONSE_SCHEMA,
    VISION_SYSTEM_PROMPT,
    VISION_USER_PROMPT,
)
from estate_sale_finder.config import Settings
from estate_sale_finder.domain.models import (
    APPROVED_TARGET_CATEGORIES,
    DetectedItem,
    ImageAnalysisResult,
)

logger = logging.getLogger(__name__)


class ItemPayload(BaseModel):
    category: str
    label: str
    confidence: float = Field(ge=0, le=1)
    modern_likelihood: float = Field(ge=0, le=1)
    visible_brand: str | None
    notes: str | None

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in APPROVED_TARGET_CATEGORIES:
            raise ValueError(f"Unexpected detection category: {value}")
        return value


class VisionImageResult(BaseModel):
    image_ref: str
    contains_target: bool
    items: list[ItemPayload]

    @model_validator(mode="after")
    def validate_target_consistency(self) -> VisionImageResult:
        if self.contains_target != bool(self.items):
            raise ValueError("contains_target must match whether approved items are present")
        return self


class VisionBatchResponse(BaseModel):
    results: list[VisionImageResult]


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
                logger.info(
                    "openai_vision_request_sent",
                    extra={
                        "attempt": attempt,
                        "model": self.model_name,
                        "batch_size": len(images),
                    },
                )
                response = self.client.post("/responses", json=payload)
                response_payload = _response_json(response)
                self._save_response_snapshot(
                    images,
                    attempt=attempt,
                    status_code=response.status_code,
                    request_id=response.headers.get("x-request-id"),
                    response_payload=response_payload,
                    response_text=response.text if response_payload is None else None,
                )
                response.raise_for_status()
                logger.info(
                    "openai_vision_request_succeeded",
                    extra={
                        "attempt": attempt,
                        "model": self.model_name,
                        "batch_size": len(images),
                        "status_code": response.status_code,
                        "request_id": response.headers.get("x-request-id"),
                    },
                )
                if response_payload is None:
                    raise json.JSONDecodeError("OpenAI response was not JSON", response.text, 0)
                parsed = _parse_response(response_payload)
                return _to_results(
                    parsed,
                    provider=self.provider_name,
                    model=self.model_name,
                    prompt_version=self.settings.prompt_version,
                )
            except (
                httpx.HTTPError,
                VisionProviderError,
                ValidationError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                self._save_error_snapshot(images, attempt=attempt, exc=exc)
                logger.warning(
                    "openai_vision_request_failed",
                    extra={
                        "attempt": attempt,
                        "model": self.model_name,
                        "batch_size": len(images),
                        "error": str(exc),
                        "status_code": _status_code(exc),
                    },
                )
                if attempt < self.settings.http_max_retries:
                    time.sleep(min(8.0, 0.5 * 2 ** (attempt - 1)))
        raise _provider_error_from_exception(last_error) from last_error

    def _save_response_snapshot(
        self,
        images: list[AnalysisImage],
        *,
        attempt: int,
        status_code: int,
        request_id: str | None,
        response_payload: dict[str, Any] | None,
        response_text: str | None,
    ) -> None:
        if not self.settings.openai_save_responses:
            return
        snapshot: dict[str, Any] = {
            "created_at": datetime.now(UTC).isoformat(),
            "provider": self.provider_name,
            "model": self.model_name,
            "attempt": attempt,
            "status_code": status_code,
            "request_id": request_id,
            "image_refs": [image.image_ref for image in images],
            "response": response_payload,
            "response_text": response_text,
        }
        self._write_snapshot("response", snapshot)

    def _save_error_snapshot(
        self,
        images: list[AnalysisImage],
        *,
        attempt: int,
        exc: Exception,
    ) -> None:
        if not self.settings.openai_save_responses:
            return
        response_payload: dict[str, Any] | None = None
        response_text: str | None = None
        status_code = _status_code(exc)
        request_id: str | None = None
        if isinstance(exc, httpx.HTTPStatusError):
            response_payload = _response_json(exc.response)
            response_text = exc.response.text if response_payload is None else None
            request_id = exc.response.headers.get("x-request-id")
        snapshot: dict[str, Any] = {
            "created_at": datetime.now(UTC).isoformat(),
            "provider": self.provider_name,
            "model": self.model_name,
            "attempt": attempt,
            "status_code": status_code,
            "request_id": request_id,
            "image_refs": [image.image_ref for image in images],
            "error_type": type(exc).__name__,
            "error": str(exc),
            "response": response_payload,
            "response_text": response_text,
        }
        self._write_snapshot("error", snapshot)

    def _write_snapshot(self, kind: str, snapshot: dict[str, Any]) -> None:
        directory = self.settings.openai_response_log_dir or (
            self.settings.logs_dir / "openai-responses"
        )
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        image_refs = "-".join(str(image_ref) for image_ref in snapshot["image_refs"])
        filename = f"{timestamp}-{kind}-{image_refs[:80]}-{uuid4().hex[:8]}.json"
        path = directory / filename
        path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
        logger.info(
            "openai_vision_response_saved",
            extra={"path": str(path), "kind": kind, "image_refs": snapshot["image_refs"]},
        )

    def _request_payload(self, images: list[AnalysisImage]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": VISION_USER_PROMPT}]
        for image in images:
            content.append(
                {
                    "type": "input_text",
                    "text": (
                        f'The following image has immutable reference "{image.image_ref}". '
                        "Return this exact value in image_ref."
                    ),
                }
            )
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


def _status_code(exc: Exception) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _response_json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return {"payload": payload}


def _parse_response(payload: dict[str, Any]) -> VisionBatchResponse:
    if payload.get("status") == "incomplete":
        raise VisionResponseParseError("OpenAI response was incomplete")
    refusal = _find_refusal(payload.get("output", []))
    if refusal:
        raise VisionResponseParseError("OpenAI refused vision analysis")
    text = payload.get("output_text")
    if not text:
        text = _find_text(payload.get("output", []))
    if not isinstance(text, str):
        raise VisionResponseParseError("OpenAI response did not contain output text")
    try:
        return VisionBatchResponse.model_validate_json(text)
    except ValidationError as exc:
        raise VisionResponseParseError(f"OpenAI structured response was invalid: {exc}") from exc


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


def _find_refusal(output: Any) -> str | None:
    if isinstance(output, list):
        for item in output:
            found = _find_refusal(item)
            if found:
                return found
    if isinstance(output, dict):
        if output.get("type") == "refusal":
            refusal = output.get("refusal") or output.get("text") or "refusal"
            return str(refusal)
        return _find_refusal(output.get("content"))
    return None


def _provider_error_from_exception(exc: Exception | None) -> VisionProviderError:
    if isinstance(exc, VisionProviderError):
        return exc
    if exc is None:
        return VisionProviderError("OpenAI vision analysis failed without an exception")
    if isinstance(exc, (ValidationError, ValueError, KeyError, json.JSONDecodeError)):
        return VisionResponseParseError(f"OpenAI vision analysis failed: {exc}")
    return VisionProviderError(f"OpenAI vision analysis failed: {exc}")


def _to_results(
    parsed: VisionBatchResponse,
    *,
    provider: str,
    model: str,
    prompt_version: str,
) -> list[ImageAnalysisResult]:
    return [
        ImageAnalysisResult(
            image_ref=str(result.image_ref),
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
