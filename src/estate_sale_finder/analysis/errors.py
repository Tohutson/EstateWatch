from __future__ import annotations


class VisionProviderError(Exception):
    """Expected provider-side failure that can be retried or isolated."""


class VisionResponseParseError(VisionProviderError):
    """Provider returned an incomplete, refused, or invalid structured response."""


class VisionResponseMappingError(VisionProviderError):
    def __init__(
        self,
        *,
        expected_refs: set[str],
        returned_refs: list[str],
        missing_refs: set[str],
        unexpected_refs: set[str],
        duplicate_refs: set[str],
    ) -> None:
        self.expected_refs = expected_refs
        self.returned_refs = returned_refs
        self.missing_refs = missing_refs
        self.unexpected_refs = unexpected_refs
        self.duplicate_refs = duplicate_refs
        super().__init__(
            "Vision provider response did not map cleanly to image_ref values: "
            f"expected={sorted(expected_refs)} returned={returned_refs} "
            f"missing={sorted(missing_refs)} unexpected={sorted(unexpected_refs)} "
            f"duplicate={sorted(duplicate_refs)}"
        )
