from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

POSITIVE_CONCEPTS = [
    "modern mirrorless digital camera",
    "modern DSLR camera",
    "modern compact digital camera",
    "modern interchangeable camera lens",
    "mirrorless camera lens",
    "DSLR camera lens",
    "golf clubs",
    "set of golf irons",
    "golf driver",
    "golf putter",
    "golf bag",
    "golf balls",
]

NEGATIVE_CONCEPTS = [
    "antique film camera",
    "vintage camera",
    "security camera",
    "webcam",
    "camcorder",
    "tripod",
    "camera bag without a camera",
    "camera accessories",
    "camera shown in a picture",
    "golf clothing",
    "golf shoes",
    "golf cart",
    "golf rangefinder",
    "miniature golf",
    "golf shown on a television",
    "decorative golf item",
    "empty product packaging",
    "ordinary household objects",
]


class DisabledPrefilter:
    def score(self, image_path: Path) -> tuple[bool, float]:
        return True, 1.0


class OpenClipPrefilter:
    def __init__(self, model_name: str, threshold: float):
        self.model_name = model_name
        self.threshold = threshold
        self._loaded = False

    def score(self, image_path: Path) -> tuple[bool, float]:
        # The optional open-clip-torch dependency is intentionally loaded lazily so normal
        # deployments can leave LOCAL_PREFILTER_ENABLED=false without carrying a heavy model.
        try:
            score = self._score_with_open_clip(image_path)
        except Exception as exc:
            logger.warning("local_prefilter_unavailable", extra={"error": str(exc)})
            return True, 1.0
        return score >= self.threshold, score

    def _score_with_open_clip(self, image_path: Path) -> float:
        import torch  # type: ignore[import-not-found]
        from open_clip import (  # type: ignore[import-not-found]
            create_model_and_transforms,
            get_tokenizer,
        )
        from PIL import Image

        if not hasattr(self, "_model"):
            name, _, pretrained = self.model_name.partition("/")
            self._model, _, self._preprocess = create_model_and_transforms(
                name,
                pretrained=pretrained or None,
            )
            self._tokenizer = get_tokenizer(name)
            self._model.eval()
        image = self._preprocess(Image.open(image_path)).unsqueeze(0)
        texts = self._tokenizer(POSITIVE_CONCEPTS + NEGATIVE_CONCEPTS)
        with torch.no_grad():
            image_features = self._model.encode_image(image)
            text_features = self._model.encode_text(texts)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            similarities = (100.0 * image_features @ text_features.T).softmax(dim=-1)[0]
        positive = float(similarities[: len(POSITIVE_CONCEPTS)].max().item())
        negative = float(similarities[len(POSITIVE_CONCEPTS) :].max().item())
        return max(0.0, positive - negative)
