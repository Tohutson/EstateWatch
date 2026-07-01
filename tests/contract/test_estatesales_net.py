from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from estate_sale_finder.config import Settings
from estate_sale_finder.sources.base import GalleryUnavailableError
from estate_sale_finder.sources.estatesales_net import (
    EstateSalesNetClient,
    extract_gallery_from_html,
)


def test_gallery_extraction_from_fixture() -> None:
    html = (Path(__file__).parents[1] / "fixtures" / "sale_page_gallery.html").read_text()
    pictures = extract_gallery_from_html(html, "4975674")
    assert len(pictures) == 3
    assert all("4975674" in picture.source_url for picture in pictures)


@respx.mock
def test_postal_lookup_decodes_wrapped_dates(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, estatesales_base_url="https://example.test")
    respx.get("https://example.test/api/postal-code-details").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "postalCodeNumber": "14221",
                    "latitude": 42.98525,
                    "longitude": -78.722374,
                    "cityName": "Buffalo",
                    "stateCode": "NY",
                }
            ],
            headers={"content-type": "application/json"},
        )
    )
    location = EstateSalesNetClient(settings).resolve_postal_code("14221")
    assert location.latitude == 42.98525


@respx.mock
def test_discover_and_hydrate_sales(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, estatesales_base_url="https://example.test")
    respx.get("https://example.test/api/sale-details").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "latitude": 43.0,
                        "longitude": -78.7,
                        "cityName": "Buffalo",
                        "stateCode": "NY",
                        "postalCodeNumber": "14221",
                        "type": 1,
                        "firstUtcStartDate": {
                            "_type": "DateTime",
                            "_value": "2026-07-01T12:00:00Z",
                        },
                        "lastUtcEndDate": {"_type": "DateTime", "_value": "2026-07-02T18:00:00Z"},
                    }
                ],
                headers={"content-type": "application/json"},
            ),
            httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "Test sale",
                        "latitude": 43.0,
                        "longitude": -78.7,
                        "cityName": "Buffalo",
                        "stateCode": "NY",
                        "postalCodeNumber": "14221",
                        "type": 1,
                        "pictureCount": 6,
                        "dates": [],
                        "firstUtcStartDate": {
                            "_type": "DateTime",
                            "_value": "2026-07-01T12:00:00Z",
                        },
                        "lastUtcEndDate": {"_type": "DateTime", "_value": "2026-07-02T18:00:00Z"},
                        "utcDateFirstPublished": {
                            "_type": "DateTime",
                            "_value": "2026-06-20T12:00:00Z",
                        },
                        "utcDateModified": {"_type": "DateTime", "_value": "2026-06-21T12:00:00Z"},
                        "latestPicturesAddedCount": 2,
                    }
                ],
                headers={"content-type": "application/json"},
            ),
        ]
    )
    client = EstateSalesNetClient(settings)
    candidates = client.discover_sales(type("Loc", (), {"latitude": 42.9, "longitude": -78.7})())
    assert candidates[0].first_start_at == datetime(2026, 7, 1, 12, tzinfo=UTC)
    sales = client.hydrate_sales(["1"])
    assert sales[0].picture_count == 6


@respx.mock
def test_gallery_unavailable(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, estatesales_base_url="https://example.test")
    client = EstateSalesNetClient(settings)
    sale = client._sale_from_payload(
        {
            "id": 1,
            "name": "No gallery",
            "latitude": 43.0,
            "longitude": -78.7,
            "cityName": "Buffalo",
            "stateCode": "NY",
            "postalCodeNumber": "14221",
            "type": 1,
            "pictureCount": 6,
            "dates": [],
            "firstUtcStartDate": datetime(2026, 7, 1, 12, tzinfo=UTC),
            "lastUtcEndDate": datetime(2026, 7, 2, 18, tzinfo=UTC),
        }
    )
    respx.get(sale.url).mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(GalleryUnavailableError):
        client.get_sale_pictures(sale)
