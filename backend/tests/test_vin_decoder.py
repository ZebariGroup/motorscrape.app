from __future__ import annotations

import pytest
import respx
from app.schemas import VehicleListing
from app.services import vin_decoder
from httpx import Response


@pytest.fixture(autouse=True)
def _reset_vin_decoder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.vin_decoder._vin_decoder_client", None)
    monkeypatch.setattr("app.services.vin_decoder._vin_decoder_semaphore", None)
    vin_decoder._decode_cache.clear()
    monkeypatch.setattr("app.services.vin_decoder.settings.vin_decoder_enabled", True)
    monkeypatch.setattr("app.services.vin_decoder.settings.vin_decoder_timeout", 8.0)
    monkeypatch.setattr("app.services.vin_decoder.settings.vin_decoder_max_concurrency", 4)
    monkeypatch.setattr("app.services.vin_decoder.settings.vin_decoder_cache_ttl_seconds", 3600)


@respx.mock
@pytest.mark.asyncio
async def test_enrich_vehicle_listings_with_vin_data_adds_decoded_specs() -> None:
    vin = "3VVVC7B25SM037020"
    route = respx.get(vin_decoder.VPIC_DECODE_URL.format(vin=vin)).mock(
        return_value=Response(
            200,
            json={
                "Results": [
                    {
                        "Make": "Volkswagen",
                        "Model": "Taos",
                        "ModelYear": "2025",
                        "Trim": "SEL",
                        "BodyClass": "Sport Utility Vehicle (SUV)/Multi-Purpose Vehicle (MPV)",
                        "DriveType": "AWD/All-Wheel Drive",
                        "EngineCylinders": "4",
                        "DisplacementL": "1.5",
                        "FuelTypePrimary": "Gasoline",
                        "TransmissionStyle": "Automatic",
                    }
                ]
            },
        )
    )

    listing = VehicleListing(vehicle_category="car", vin=vin, raw_title="2025 Volkswagen Taos")
    [enriched] = await vin_decoder.enrich_vehicle_listings_with_vin_data([listing])

    assert route.called
    assert enriched.make == "Volkswagen"
    assert enriched.model == "Taos"
    assert enriched.year == 2025
    assert enriched.trim == "SEL"
    assert enriched.engine == "1.5L 4-cyl"
    assert enriched.drivetrain == "AWD/All-Wheel Drive"
    assert enriched.transmission == "Automatic"
    assert enriched.fuel_type == "Gasoline"


@respx.mock
@pytest.mark.asyncio
async def test_enrich_vehicle_listings_with_vin_data_uses_cache_and_skips_invalid_values() -> None:
    vin = "3VVVC7B25SM037020"
    route = respx.get(vin_decoder.VPIC_DECODE_URL.format(vin=vin)).mock(
        return_value=Response(
            200,
            json={
                "Results": [
                    {
                        "Make": "Volkswagen",
                        "Model": "Taos",
                        "ModelYear": "2025",
                        "Trim": "SEL",
                    }
                ]
            },
        )
    )

    listing = VehicleListing(vehicle_category="car", vin=vin, trim="Factory Trim")
    invalid = VehicleListing(vehicle_category="car", vehicle_identifier="stock-123")

    first = await vin_decoder.enrich_vehicle_listings_with_vin_data([listing, invalid])
    second = await vin_decoder.enrich_vehicle_listings_with_vin_data([listing])

    assert route.call_count == 1
    assert first[0].trim == "Factory Trim"
    assert first[1].vehicle_identifier == "stock-123"
    assert second[0].make == "Volkswagen"
