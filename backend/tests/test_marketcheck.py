from __future__ import annotations

import pytest
from app.schemas import VehicleListing
from app.services import marketcheck


@pytest.fixture(autouse=True)
def _reset_marketcheck(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.marketcheck._marketcheck_client", None)
    monkeypatch.setattr("app.services.marketcheck._marketcheck_semaphore", None)
    marketcheck._decode_cache.clear()
    monkeypatch.setattr("app.services.marketcheck.settings.marketcheck_api_key", "mc_test_key")
    monkeypatch.setattr("app.services.marketcheck.settings.marketcheck_max_concurrency", 2)
    monkeypatch.setattr("app.services.marketcheck.settings.marketcheck_max_vins_per_batch", 2)
    monkeypatch.setattr("app.services.marketcheck.settings.marketcheck_cache_ttl_seconds", 3600)


@pytest.mark.asyncio
async def test_enrich_with_marketcheck_limits_unique_vins_per_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int | None]] = []

    async def fake_fetch(vin: str, miles: int | None) -> dict[str, object] | None:
        calls.append((vin, miles))
        return {
            "marketcheck_trim": f"decoded-{vin[-4:]}",
            "estimated_market_value": 12345.0,
        }

    monkeypatch.setattr("app.services.marketcheck._fetch_marketcheck_data", fake_fetch)

    listings = [
        VehicleListing(vin="1HGCM82633A000001", mileage=10000, trim="Base"),
        VehicleListing(vin="1HGCM82633A000001", mileage=10000, trim="Base"),
        VehicleListing(vin="1HGCM82633A000002", mileage=11000, trim="Base"),
        VehicleListing(vin="1HGCM82633A000003", mileage=12000, trim="Base"),
    ]

    enriched = await marketcheck.enrich_with_marketcheck(listings)

    assert calls == [
        ("1HGCM82633A000001", 10000),
        ("1HGCM82633A000002", 11000),
    ]
    assert enriched[0].marketcheck_trim == "decoded-0001"
    assert enriched[1].marketcheck_trim == "decoded-0001"
    assert enriched[2].marketcheck_trim == "decoded-0002"
    assert enriched[3].marketcheck_trim is None
    assert enriched[0].estimated_market_value == 12345.0
    assert enriched[3].estimated_market_value is None
