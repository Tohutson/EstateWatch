from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from PIL import Image

from estate_sale_finder.analysis.base import AnalysisImage
from estate_sale_finder.analysis.errors import VisionProviderError
from estate_sale_finder.analysis.openai_vision import OpenAIVisionProvider
from estate_sale_finder.config import Settings


def test_http_errors_do_not_split_batch_into_individual_requests(tmp_path: Path) -> None:
    thumb = tmp_path / "thumb.jpg"
    Image.new("RGB", (16, 16), "blue").save(thumb, format="JPEG")
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            429,
            json={"error": {"message": "rate limit"}},
            request=request,
        )

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        analysis_provider="openai",
        vision_api_key="test-key",
        http_max_retries=2,
    )
    provider = OpenAIVisionProvider(
        settings,
        client=httpx.Client(
            base_url="https://api.openai.test/v1",
            transport=httpx.MockTransport(handler),
        ),
    )

    with pytest.raises(VisionProviderError, match="429 Too Many Requests"):
        provider.analyze(
            [
                AnalysisImage(1, thumb, "https://example.test/1.jpg", "img_0001"),
                AnalysisImage(2, thumb, "https://example.test/2.jpg", "img_0002"),
            ]
        )

    assert requests == 2
