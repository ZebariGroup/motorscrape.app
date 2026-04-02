from __future__ import annotations

import pytest
import respx
from app.schemas import VehicleListing
from app.services import black_book_valuation
from httpx import Response


@pytest.fixture(autouse=True)
def _reset_black_book(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.black_book_valuation._client", None)
    monkeypatch.setattr("app.services.black_book_valuation._semaphore", None)
    black_book_valuation._valuation_cache.clear()
    monkeypatch.setattr("app.services.black_book_valuation.settings.black_book_enabled", False)
    monkeypatch.setattr("app.services.black_book_valuation.settings.black_book_vin_url_template", "")
    monkeypatch.setattr("app.services.black_book_valuation.settings.black_book_api_key", "")
    monkeypatch.setattr("app.services.black_book_valuation.settings.black_book_auth_header", "X-API-Key")
    monkeypatch.setattr("app.services.black_book_valuation.settings.black_book_timeout", 8.0)
    monkeypatch.setattr("app.services.black_book_valuation.settings.black_book_max_concurrency", 4)
    monkeypatch.setattr("app.services.black_book_valuation.settings.black_book_cache_ttl_seconds", 3600)


@pytest.mark.asyncio
async def test_black_book_enrichment_noop_when_not_configured() -> None:
    listing = VehicleListing(vehicle_category="car", vin="3VVVC7B25SM037020", price=25000)
    enriched = await black_book_valuation.enrich_vehicle_listings_with_black_book_values([listing])
    assert enriched[0].external_retail_value is None
    assert enriched[0].external_valuation_provider is None


@respx.mock
@pytest.mark.asyncio
async def test_black_book_enrichment_sets_external_values(monkeypatch: pytest.MonkeyPatch) -> None:
    vin = "3VVVC7B25SM037020"
    monkeypatch.setattr("app.services.black_book_valuation.settings.black_book_enabled", True)
    monkeypatch.setattr(
        "app.services.black_book_valuation.settings.black_book_vin_url_template",
        "https://blackbook.example/valuation/{vin}",
    )
    monkeypatch.setattr("app.services.black_book_valuation.settings.black_book_api_key", "test-key")

    route = respx.get(f"https://blackbook.example/valuation/{vin}").mock(
        return_value=Response(
            200,
            json={
                "retailValue": 27125,
                "tradeInValue": 24880,
                "rangeLow": 26200,
                "rangeHigh": 27900,
                "confidenceScore": 88,
            },
        )
    )

    listing = VehicleListing(vehicle_category="car", vin=vin, price=26995)
    [enriched] = await black_book_valuation.enrich_vehicle_listings_with_black_book_values([listing])
    assert route.called
    assert enriched.external_valuation_provider == "black_book"
    assert enriched.external_retail_value == pytest.approx(27125)
    assert enriched.external_trade_in_value == pytest.approx(24880)
    assert enriched.external_valuation_range_low == pytest.approx(26200)
    assert enriched.external_valuation_range_high == pytest.approx(27900)
    assert enriched.external_valuation_confidence == pytest.approx(0.88)
