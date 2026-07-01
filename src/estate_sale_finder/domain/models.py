from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class GalleryStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    OK = "ok"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class ImageStatus(StrEnum):
    DISCOVERED = "discovered"
    DOWNLOADED = "downloaded"
    ANALYZED = "analyzed"
    ERROR = "error"


@dataclass(frozen=True)
class PostalCodeLocation:
    postal_code: str
    latitude: float
    longitude: float
    city: str | None = None
    state: str | None = None


@dataclass(frozen=True)
class SaleDate:
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class SaleCandidate:
    source: str
    external_id: str
    latitude: float
    longitude: float
    city: str | None
    state: str | None
    postal_code: str | None
    sale_type: str
    first_start_at: datetime
    last_end_at: datetime
    distance_miles: float | None = None


@dataclass(frozen=True)
class Sale:
    source: str
    external_id: str
    title: str
    url: str
    organization_name: str | None
    address: str | None
    latitude: float
    longitude: float
    city: str | None
    state: str | None
    postal_code: str | None
    sale_type: str
    picture_count: int
    first_start_at: datetime
    last_end_at: datetime
    first_published_at: datetime | None
    remote_modified_at: datetime | None
    latest_pictures_added_count: int | None
    dates: list[SaleDate] = field(default_factory=list)
    distance_miles: float | None = None


@dataclass(frozen=True)
class SalePicture:
    source_id: str | None
    source_url: str
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    description: str | None = None


@dataclass(frozen=True)
class DetectedItem:
    category: str
    label: str
    confidence: float
    modern_likelihood: float
    visible_brand: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ImageAnalysisResult:
    image_id: int
    contains_target: bool
    items: list[DetectedItem]
    provider: str
    model_name: str
    prompt_version: str


@dataclass
class RunSummary:
    sales_discovered: int = 0
    sales_hydrated: int = 0
    sales_eligible: int = 0
    new_sales: int = 0
    changed_sales: int = 0
    images_discovered: int = 0
    images_downloaded: int = 0
    images_analyzed: int = 0
    positive_matches: int = 0
    email_status: str = "not_sent"
