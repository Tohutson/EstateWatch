from __future__ import annotations

from typing import Protocol

from estate_sale_finder.domain.models import PostalCodeLocation, Sale, SaleCandidate, SalePicture


class GalleryUnavailableError(RuntimeError):
    """Raised when a sale gallery cannot be retrieved from dependable public data."""


class SaleSource(Protocol):
    source_name: str

    def resolve_postal_code(self, postal_code: str) -> PostalCodeLocation: ...

    def discover_sales(self, location: PostalCodeLocation) -> list[SaleCandidate]: ...

    def hydrate_sales(self, sale_ids: list[str]) -> list[Sale]: ...

    def get_sale_pictures(self, sale: Sale) -> list[SalePicture]: ...
