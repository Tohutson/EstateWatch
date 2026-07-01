from __future__ import annotations

import html
import json
import logging
import re
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import httpx

from estate_sale_finder.config import Settings
from estate_sale_finder.domain.models import (
    PostalCodeLocation,
    Sale,
    SaleCandidate,
    SaleDate,
    SalePicture,
)
from estate_sale_finder.utils.dates import decode_datetime_wrappers, ensure_utc

from .base import GalleryUnavailableError

logger = logging.getLogger(__name__)

TYPE_NAME_BY_ID = {
    1: "EstateSales",
    2: "Auctions",
    4: "MovingSales",
    8: "OnlineOnlyAuctions",
}


class EstateSalesNetClient:
    source_name = "estatesales.net"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.base_url = settings.estatesales_base_url.rstrip("/")
        self.client = client or httpx.Client(
            base_url=self.base_url,
            timeout=settings.http_timeout_seconds,
            headers={
                "User-Agent": settings.http_user_agent,
                "Accept": "application/json,text/html",
            },
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def resolve_postal_code(self, postal_code: str) -> PostalCodeLocation:
        payload = self._get_json(
            "/api/postal-code-details",
            params={
                "filter": f"byfield:postalcodenumber_{postal_code}",
                "explicitTypes": "DateTime",
            },
        )
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"Postal code lookup returned no results for {postal_code}")
        item = payload[0]
        return PostalCodeLocation(
            postal_code=str(item["postalCodeNumber"]),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
            city=item.get("cityName"),
            state=item.get("stateCode"),
        )

    def discover_sales(self, location: PostalCodeLocation) -> list[SaleCandidate]:
        payload = self._get_json(
            "/api/sale-details",
            params={
                "bypass": (
                    f"bycoordinatesanddistance:{location.latitude}_{location.longitude}_250"
                ),
                "include": "saleschedule",
                "select": ",".join(
                    [
                        "id",
                        "stateCode",
                        "cityName",
                        "postalCodeNumber",
                        "primaryMetroAreaId",
                        "latitude",
                        "longitude",
                        "utcOffset",
                        "observesDaylightSavingTime",
                        "type",
                        "isMarketplaceSale",
                        "firstUtcStartDate",
                        "firstLocalStartDate",
                        "lastUtcEndDate",
                        "lastLocalEndDate",
                        "utcDateFirstPublished",
                        "saleSchedule",
                    ]
                ),
                "explicitTypes": "DateTime",
            },
        )
        if not isinstance(payload, list):
            raise ValueError("Sale discovery response was not a list")
        return [self._candidate_from_payload(item) for item in payload]

    def hydrate_sales(self, sale_ids: list[str]) -> list[Sale]:
        if not sale_ids:
            return []
        hydrated: list[Sale] = []
        for batch in _chunks(sale_ids, self.settings.sale_detail_batch_size):
            payload = self._get_json(
                "/api/sale-details",
                params={
                    "bypass": "byids:" + ",".join(batch),
                    "include": "mainpicture,dates",
                    "select": ",".join(
                        [
                            "id",
                            "name",
                            "orgName",
                            "address",
                            "latitude",
                            "longitude",
                            "cityName",
                            "postalCodeNumber",
                            "stateCode",
                            "type",
                            "pictureCount",
                            "mainPicture",
                            "dates",
                            "firstUtcStartDate",
                            "lastUtcEndDate",
                            "utcDateFirstPublished",
                            "utcDateModified",
                            "latestPicturesAddedCount",
                            "auctionUrl",
                            "isMarketplaceSale",
                        ]
                    ),
                    "explicitTypes": "DateTime",
                },
            )
            if not isinstance(payload, list):
                raise ValueError("Sale hydration response was not a list")
            hydrated.extend(self._sale_from_payload(item) for item in payload)
        return hydrated

    def get_sale_pictures(self, sale: Sale) -> list[SalePicture]:
        response = self._request("GET", sale.url, expected_json=False)
        pictures = extract_gallery_from_html(response.text, sale.external_id)
        if not pictures:
            raise GalleryUnavailableError(
                "No complete gallery metadata found in sale HTML. "
                "EstateSales.NET page structure may have changed."
            )
        return pictures

    def _get_json(self, path: str, params: dict[str, str]) -> Any:
        response = self._request("GET", path, params=params, expected_json=True)
        return decode_datetime_wrappers(response.json())

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        expected_json: bool,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.http_max_retries + 1):
            start = time.monotonic()
            try:
                response = self.client.request(method, url, params=params)
                response.raise_for_status()
                if expected_json and "json" not in response.headers.get("content-type", ""):
                    raise ValueError(f"Expected JSON response from {url}")
                elapsed = time.monotonic() - start
                logger.debug("http_success", extra={"url": str(response.url), "duration": elapsed})
                if self.settings.http_request_delay_seconds > 0:
                    time.sleep(self.settings.http_request_delay_seconds)
                return response
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "http_retry",
                    extra={"url": url, "attempt": attempt, "error": str(exc)},
                )
                if attempt < self.settings.http_max_retries:
                    time.sleep(min(8.0, 0.5 * 2 ** (attempt - 1)))
        raise RuntimeError(f"HTTP request failed for {url}: {last_error}") from last_error

    def _candidate_from_payload(self, item: dict[str, Any]) -> SaleCandidate:
        sale_type = _sale_type_name(item)
        return SaleCandidate(
            source=self.source_name,
            external_id=str(item["id"]),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
            city=item.get("cityName"),
            state=item.get("stateCode"),
            postal_code=item.get("postalCodeNumber"),
            sale_type=sale_type,
            first_start_at=_required_datetime(item, "firstUtcStartDate"),
            last_end_at=_required_datetime(item, "lastUtcEndDate"),
        )

    def _sale_from_payload(self, item: dict[str, Any]) -> Sale:
        sale_type = _sale_type_name(item)
        url = sale_url(self.base_url, item, sale_type)
        dates = [
            SaleDate(
                start_at=_required_datetime(date, "utcStartDate"),
                end_at=_required_datetime(date, "utcEndDate"),
            )
            for date in item.get("dates", [])
            if date.get("utcStartDate") and date.get("utcEndDate")
        ]
        return Sale(
            source=self.source_name,
            external_id=str(item["id"]),
            title=str(item.get("name") or f"Estate sale {item['id']}"),
            url=url,
            organization_name=item.get("orgName"),
            address=item.get("address"),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
            city=item.get("cityName"),
            state=item.get("stateCode"),
            postal_code=item.get("postalCodeNumber"),
            sale_type=sale_type,
            picture_count=int(item.get("pictureCount") or 0),
            first_start_at=_required_datetime(item, "firstUtcStartDate"),
            last_end_at=_required_datetime(item, "lastUtcEndDate"),
            first_published_at=_optional_datetime(item.get("utcDateFirstPublished")),
            remote_modified_at=_optional_datetime(item.get("utcDateModified")),
            latest_pictures_added_count=item.get("latestPicturesAddedCount"),
            dates=dates,
        )


def sale_url(base_url: str, item: dict[str, Any], sale_type: str) -> str:
    city = _url_part(str(item.get("cityName") or "Sale"))
    state = str(item.get("stateCode") or "US")
    postal = str(item.get("postalCodeNumber") or "")
    return f"{base_url.rstrip('/')}/{state}/{city}/{postal}/{item['id']}"


def extract_gallery_from_html(page_html: str, sale_id: str) -> list[SalePicture]:
    pictures = _extract_json_ld_pictures(page_html, sale_id)
    pictures.extend(_extract_cdn_pairs(page_html, sale_id))
    deduped: dict[str, SalePicture] = {}
    for picture in pictures:
        deduped.setdefault(picture.source_url, picture)
    return sorted(deduped.values(), key=lambda item: item.source_url)


def _extract_json_ld_pictures(page_html: str, sale_id: str) -> list[SalePicture]:
    pictures: list[SalePicture] = []
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw = html.unescape(match.group(1)).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for url in _walk_for_urls(payload):
            if _is_sale_image(url, sale_id):
                pictures.append(SalePicture(source_id=_image_id_from_url(url), source_url=url))
    return pictures


def _extract_cdn_pairs(page_html: str, sale_id: str) -> list[SalePicture]:
    urls = [
        html.unescape(match.group(0))
        for match in re.finditer(
            rf"https://picturescdn\.estatesales\.net/{re.escape(sale_id)}/1-1/[A-Za-z0-9-]+\.jpg",
            page_html,
        )
    ]
    by_slug: dict[str, str] = {}
    for url in urls:
        slug = _image_id_from_url(url) or url
        by_slug.setdefault(slug, url)
    return [
        SalePicture(
            source_id=slug,
            source_url=url,
        )
        for slug, url in by_slug.items()
    ]


def _walk_for_urls(payload: Any) -> Iterable[str]:
    if isinstance(payload, str):
        if payload.startswith("https://picturescdn.estatesales.net/"):
            yield payload
    elif isinstance(payload, dict):
        for value in payload.values():
            yield from _walk_for_urls(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _walk_for_urls(item)


def _is_sale_image(url: str, sale_id: str) -> bool:
    return f"picturescdn.estatesales.net/{sale_id}/" in url and url.lower().endswith(".jpg")


def _image_id_from_url(url: str) -> str | None:
    match = re.search(r"/([A-Za-z0-9-]+)\.(?:jpg|jpeg|png|webp)$", url, re.IGNORECASE)
    return match.group(1) if match else None


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _sale_type_name(item: dict[str, Any]) -> str:
    if isinstance(item.get("typeName"), str):
        return str(item["typeName"])
    raw = item.get("type")
    return TYPE_NAME_BY_ID.get(int(raw), str(raw)) if raw is not None else "Unknown"


def _required_datetime(item: dict[str, Any], key: str) -> datetime:
    value = item.get(key)
    if not isinstance(value, datetime):
        raise ValueError(f"Missing or invalid required DateTime field: {key}")
    return ensure_utc(value)


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("Invalid optional DateTime field")
    return ensure_utc(value)


def _url_part(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return clean or "Sale"
