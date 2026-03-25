"""Orchestrator unit tests with external I/O mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.schemas import DealershipFound
from app.services.orchestrator import stream_search


@pytest.mark.asyncio
async def test_stream_search_places_error_surfaces_search_error() -> None:
    with patch(
        "app.services.orchestrator.find_car_dealerships",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Places missing"),
    ):
        chunks: list[str] = []
        async for c in stream_search("Detroit", "Toyota", ""):
            chunks.append(c)
    text = "".join(chunks)
    assert "search_error" in text
    assert "Places missing" in text
    assert '"ok": false' in text


@pytest.mark.asyncio
async def test_stream_search_done_includes_fetch_metrics() -> None:
    dealers = [
        DealershipFound(
            name="Test Dealer",
            place_id="p1",
            address="1 Main St",
            website="https://example-dealer.test",
        )
    ]

    async def fake_fetch(*_args, **_kwargs):
        return "<html></html>", "direct"

    with (
        patch(
            "app.services.orchestrator.find_car_dealerships",
            new_callable=AsyncMock,
            return_value=dealers,
        ),
        patch(
            "app.services.orchestrator.fetch_page_html",
            new_callable=AsyncMock,
            side_effect=fake_fetch,
        ),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        from app.schemas import ExtractionResult, VehicleListing

        mock_llm.return_value = ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2023,
                    make="Toyota",
                    model="Camry",
                    price=25000,
                    listing_url="https://example-dealer.test/vdp/1",
                )
            ],
            next_page_url=None,
        )

        chunks: list[str] = []
        async for c in stream_search(
            "Detroit",
            "",
            "",
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert "fetch_metrics" in tail
    assert "fetch_direct" in tail
    assert "extraction_metrics" in tail
    assert "pages_llm" in tail
