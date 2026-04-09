from __future__ import annotations

import pytest
import respx
from app.services import marketcheck
from httpx import Response


@pytest.fixture(autouse=True)
def _reset_marketcheck(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.marketcheck._marketcheck_client", None)
    monkeypatch.setattr("app.services.marketcheck._marketcheck_semaphore", None)
    marketcheck._details_cache.clear()
    monkeypatch.setattr("app.services.marketcheck.settings.marketcheck_api_key", "mc_test_key")
    monkeypatch.setattr("app.services.marketcheck.settings.marketcheck_max_concurrency", 2)
    monkeypatch.setattr("app.services.marketcheck.settings.marketcheck_cache_ttl_seconds", 3600)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_marketcheck_details_returns_decode_and_predict_fields() -> None:
    vin = "3MW89CW07T8F92425"
    decode_route = respx.get(marketcheck.MARKETCHECK_DECODE_URL.format(vin=vin)).mock(
        return_value=Response(
            200,
            json={
                "year": 2026,
                "make": "BMW",
                "model": "3 Series",
                "trim": "330i",
                "body_type": "Sedan",
                "vehicle_type": "Car",
                "transmission": "Automatic",
                "drivetrain": "4WD",
                "fuel_type": "Premium Unleaded",
                "engine": "2.0L I4",
                "installed_options": [
                    {"name": "Driving Assistance Package"},
                    "Heated Seats",
                    {"description": "Parking Assistance Package"},
                ],
            },
        )
    )
    predict_route = respx.get(marketcheck.MARKETCHECK_PREDICT_URL).mock(
        return_value=Response(200, json={"predicted_price": 48172})
    )

    details = await marketcheck.fetch_marketcheck_details(vin, 4058)

    assert decode_route.called
    assert predict_route.called
    assert details == {
        "vin": vin,
        "year": 2026,
        "make": "BMW",
        "model": "3 Series",
        "marketcheck_trim": "330i",
        "body_style": "Sedan",
        "vehicle_type": "Car",
        "transmission": "Automatic",
        "drivetrain": "4WD",
        "fuel_type": "Premium Unleaded",
        "engine": "2.0L I4",
        "marketcheck_features": [
            "Driving Assistance Package",
            "Heated Seats",
            "Parking Assistance Package",
        ],
        "estimated_market_value": 48172.0,
    }


@respx.mock
@pytest.mark.asyncio
async def test_fetch_marketcheck_details_caches_by_vin_and_miles() -> None:
    vin = "3MW89CW07T8F92425"
    decode_route = respx.get(marketcheck.MARKETCHECK_DECODE_URL.format(vin=vin)).mock(
        return_value=Response(200, json={"trim": "330i"})
    )
    predict_route = respx.get(marketcheck.MARKETCHECK_PREDICT_URL).mock(
        return_value=Response(200, json={"predicted_price": 48172})
    )

    no_miles_first = await marketcheck.fetch_marketcheck_details(vin)
    no_miles_second = await marketcheck.fetch_marketcheck_details(vin)
    with_miles = await marketcheck.fetch_marketcheck_details(vin, 4058)

    assert no_miles_first == {"vin": vin, "marketcheck_trim": "330i", "marketcheck_features": []}
    assert no_miles_second == no_miles_first
    assert with_miles == {
        "vin": vin,
        "marketcheck_trim": "330i",
        "marketcheck_features": [],
        "estimated_market_value": 48172.0,
    }
    assert decode_route.call_count == 2
    assert predict_route.call_count == 1
