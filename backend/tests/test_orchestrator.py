"""Orchestrator unit tests with external I/O mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.schemas import DealershipFound
from app.services.orchestrator import (
    _bounded_phase_timeout,
    _effective_search_concurrency,
    _effective_max_pages_for_route,
    _guess_franchise_inventory_srp_url,
    _prefer_https_website_url,
    stream_search,
)
from app.services.provider_router import ProviderRoute


def test_prefer_https_website_url() -> None:
    assert _prefer_https_website_url("http://example.com/") == "https://example.com/"
    assert _prefer_https_website_url("https://x.test") == "https://x.test"
    assert _prefer_https_website_url("  http://a.b  ") == "https://a.b"


def test_guess_franchise_inventory_srp_url() -> None:
    assert (
        _guess_franchise_inventory_srp_url("http://dealer.example/", "new")
        == "https://www.dealer.example/inventory/new"
    )
    assert (
        _guess_franchise_inventory_srp_url("https://www.dealer.example", "used")
        == "https://www.dealer.example/inventory/used"
    )
    assert _guess_franchise_inventory_srp_url("https://www.dealer.example", "all") == (
        "https://www.dealer.example/inventory/new"
    )


def test_effective_max_pages_for_route_respects_requested_pages() -> None:
    route = None
    assert _effective_max_pages_for_route(1, route) == 1
    assert _effective_max_pages_for_route(3, route) == 3


def test_bounded_phase_timeout_caps_to_remaining_budget() -> None:
    timeout = _bounded_phase_timeout(
        base_timeout=275.0,
        dealer_timeout=240.0,
        elapsed_seconds=100.0,
        reserve_seconds=10.0,
        min_timeout=5.0,
    )
    assert timeout == 130.0


def test_bounded_phase_timeout_returns_none_when_budget_exhausted() -> None:
    timeout = _bounded_phase_timeout(
        base_timeout=90.0,
        dealer_timeout=120.0,
        elapsed_seconds=116.0,
        reserve_seconds=8.0,
        min_timeout=5.0,
    )
    assert timeout is None


def test_effective_search_concurrency_uses_config_without_managed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.orchestrator.settings.search_concurrency", 7)
    monkeypatch.setattr("app.services.orchestrator.settings.zenrows_api_key", "")
    monkeypatch.setattr("app.services.orchestrator.settings.scrapingbee_api_key", "")
    assert _effective_search_concurrency() == 7


def test_effective_search_concurrency_caps_to_managed_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.orchestrator.settings.search_concurrency", 12)
    monkeypatch.setattr("app.services.orchestrator.settings.zenrows_api_key", "zr")
    monkeypatch.setattr("app.services.orchestrator.settings.scrapingbee_api_key", "")
    monkeypatch.setattr("app.services.orchestrator.settings.zenrows_max_concurrency", 2)
    monkeypatch.setattr("app.services.orchestrator.settings.managed_scraper_max_concurrency", 3)
    monkeypatch.setattr("app.services.orchestrator.settings.search_workers_per_managed_slot", 2)
    assert _effective_search_concurrency() == 4


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
            "app.services.orchestrator.get_cached_inventory_listings",
            return_value=None,
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


@pytest.mark.asyncio
async def test_stream_search_auto_expands_pagination_from_site_counts() -> None:
    from app.schemas import ExtractionResult, PaginationInfo, VehicleListing

    dealers = [
        DealershipFound(
            name="Test Dealer",
            place_id="p1",
            address="1 Main St",
            website="https://example-dealer.test",
        )
    ]
    homepage_html = '<html><body><a href="/inventory?page=1">Inventory</a></body></html>'
    inventory_html = "<html><body><div>Inventory</div></body></html>"

    async def fake_fetch(url, *_args, **_kwargs):
        if url == "https://example-dealer.test":
            return homepage_html, "direct"
        return inventory_html, "direct"

    structured_results = [
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2024,
                    make="Toyota",
                    model="Camry",
                    price=25001,
                    listing_url="https://example-dealer.test/vdp/1",
                )
            ],
            next_page_url="https://example-dealer.test/inventory?page=2",
            pagination=PaginationInfo(
                current_page=1,
                total_pages=3,
                page_size=24,
                total_results=72,
                source="inventory_api",
            ),
        ),
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2024,
                    make="Toyota",
                    model="Camry",
                    price=25002,
                    listing_url="https://example-dealer.test/vdp/2",
                )
            ],
            next_page_url="https://example-dealer.test/inventory?page=3",
            pagination=PaginationInfo(
                current_page=2,
                total_pages=3,
                page_size=24,
                total_results=72,
                source="inventory_api",
            ),
        ),
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2024,
                    make="Toyota",
                    model="Camry",
                    price=25003,
                    listing_url="https://example-dealer.test/vdp/3",
                )
            ],
            next_page_url=None,
            pagination=PaginationInfo(
                current_page=3,
                total_pages=3,
                page_size=24,
                total_results=72,
                source="inventory_api",
            ),
        ),
    ]

    with (
        patch(
            "app.services.orchestrator.find_car_dealerships",
            new_callable=AsyncMock,
            return_value=dealers,
        ),
        patch(
            "app.services.orchestrator.get_cached_inventory_listings",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.set_cached_inventory_listings",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.fetch_page_html",
            new_callable=AsyncMock,
            side_effect=fake_fetch,
        ),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            side_effect=structured_results,
        ) as mock_structured,
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
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
    assert mock_structured.call_count == 3
    assert mock_llm.await_count == 0
    assert tail.count("https://example-dealer.test/vdp/") == 3
    assert '"listings_found": 3' in tail
    assert '"pages_scraped": 3' in tail


@pytest.mark.asyncio
async def test_stream_search_retries_empty_dealer_dot_com_make_query_with_generic_srp() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Golling Alfa Romeo FIAT",
            place_id="p1",
            address="34500 Woodward Ave",
            website="https://www.alfaromeoofbirmingham.com",
        )
    ]
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="structured_api",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-inventory",),
        inventory_url_hint="https://www.alfaromeoofbirmingham.com/new-inventory/index.htm",
    )

    async def fake_fetch(*_args, **_kwargs):
        return "<html><body>Inventory</body></html>", "direct"

    provider_results = [
        ExtractionResult(
            vehicles=[],
            next_page_url=None,
            pagination=None,
        ),
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2024,
                    make="Alfa Romeo",
                    model="Giulia",
                    price=48995,
                    listing_url="https://www.alfaromeoofbirmingham.com/vdp/giulia-1",
                )
            ],
            next_page_url=None,
            pagination=None,
        ),
    ]

    with (
        patch(
            "app.services.orchestrator.find_car_dealerships",
            new_callable=AsyncMock,
            return_value=dealers,
        ),
        patch(
            "app.services.orchestrator.get_cached_inventory_listings",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.set_cached_inventory_listings",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.fetch_page_html",
            new_callable=AsyncMock,
            side_effect=fake_fetch,
        ),
        patch(
            "app.services.orchestrator.detect_or_lookup_provider",
            return_value=route,
        ),
        patch(
            "app.services.orchestrator.resolve_inventory_url_for_provider",
            return_value="https://www.alfaromeoofbirmingham.com/new-inventory/index.htm?make=Alfa+Romeo",
        ),
        patch(
            "app.services.orchestrator.extract_with_provider",
            side_effect=provider_results,
        ) as mock_provider_extract,
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "Birmingham, MI",
            "Alfa Romeo",
            "",
            vehicle_condition="new",
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_provider_extract.call_count == 2
    assert mock_llm.await_count == 0
    assert "https://www.alfaromeoofbirmingham.com/vdp/giulia-1" in tail
    assert '"listings_found": 1' in tail
