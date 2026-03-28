"""Orchestrator unit tests with external I/O mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.config import settings
from app.db.account_store import get_account_store
from app.schemas import DealershipFound
from app.services.orchestrator import (
    _dealer_on_multi_model_inventory_urls,
    _dealer_inspire_model_inventory_urls,
    _find_inventory_url,
    _inventory_url_recovery_candidates,
    _team_velocity_inventory_url_from_model_hub,
    _team_velocity_model_inventory_urls,
    _bounded_phase_timeout,
    _effective_dealer_timeout,
    _effective_max_pages_for_route,
    stream_search,
)
from app.services.orchestrator_utils import (
    effective_max_pages_for_route,
    effective_search_concurrency,
    guess_franchise_inventory_srp_url,
    html_mentions_make,
    prefer_https_website_url,
)
from app.services.provider_router import ProviderRoute
from app.services.scrape_logging import create_scrape_run_recorder


def test_prefer_https_website_url() -> None:
    assert prefer_https_website_url("http://example.com/") == "https://example.com/"
    assert prefer_https_website_url("https://x.test") == "https://x.test"
    assert prefer_https_website_url("  http://a.b  ") == "https://a.b"


def test_guess_franchise_inventory_srp_url() -> None:
    assert (
        guess_franchise_inventory_srp_url("http://dealer.example/", "new")
        == "https://www.dealer.example/inventory/new"
    )
    assert (
        guess_franchise_inventory_srp_url("https://www.dealer.example", "used")
        == "https://www.dealer.example/inventory/used"
    )
    assert guess_franchise_inventory_srp_url("https://www.dealer.example", "all") == (
        "https://www.dealer.example/inventory/new"
    )


def test_effective_max_pages_for_route_respects_requested_pages() -> None:
    route = None
    assert effective_max_pages_for_route(1, route) == 1
    assert effective_max_pages_for_route(3, route) == 3


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


def test_effective_dealer_timeout_scales_for_deep_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.orchestrator.settings.dealership_timeout", 150.0)
    assert _effective_dealer_timeout(3) == 150.0
    assert _effective_dealer_timeout(5) == 180.0
    assert _effective_dealer_timeout(10) == 210.0


def test_effective_max_pages_for_route_caps_render_heavy_dealer_platforms() -> None:
    route = ProviderRoute(
        platform_id="dealer_on",
        confidence=1.0,
        extraction_mode="rendered_dom",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory",),
    )
    assert _effective_max_pages_for_route(10, route) == 3


def test_dealer_inspire_model_inventory_urls_filters_to_requested_model() -> None:
    html = """
    <html><body>
      <a href="/new-vehicles/chevrolet-blazer/">Chevrolet Blazer</a>
      <a href="/new-vehicles/chevrolet-equinox/">Chevrolet Equinox</a>
      <a href="/new-vehicles/">All New Vehicles</a>
    </body></html>
    """
    urls = _dealer_inspire_model_inventory_urls(
        html,
        "https://www.serrachevrolet.com/new-vehicles/",
        vehicle_condition="new",
        model="Blazer",
    )
    assert urls == ["https://www.serrachevrolet.com/new-vehicles/chevrolet-blazer/"]


def test_team_velocity_model_inventory_urls_filter_to_requested_model() -> None:
    html = """
    <html><body>
      <a href="/inventory/new/chevrolet-blazer">Chevrolet Blazer</a>
      <a href="/inventory/new/chevrolet-equinox">Chevrolet Equinox</a>
      <a href="/--inventory?condition=new&make=Chevrolet&model=Blazer">Filtered Blazer</a>
    </body></html>
    """
    urls = _team_velocity_model_inventory_urls(
        html,
        "https://www.example.com/inventory/new",
        vehicle_condition="new",
        model="Blazer",
    )
    assert "https://www.example.com/inventory/new/chevrolet-blazer" in urls
    assert "https://www.example.com/--inventory?condition=new&make=Chevrolet&model=Blazer" in urls
    assert all("equinox" not in url for url in urls)


def test_team_velocity_inventory_url_from_model_hub_preserves_model_path() -> None:
    rerouted = _team_velocity_inventory_url_from_model_hub(
        "https://www.example.com/new-vehicles/chevrolet-blazer",
        vehicle_condition="new",
    )
    assert rerouted == "https://www.example.com/inventory/new/chevrolet-blazer"


def test_dealer_on_multi_model_inventory_urls_builds_model_and_trim_filters() -> None:
    urls = _dealer_on_multi_model_inventory_urls(
        "https://www.serrachevrolet.com/searchnew.aspx?Make=Chevrolet&page=3",
        make="Chevrolet",
        model="Blazer,Blazer EV",
    )
    assert urls == [
        "https://www.serrachevrolet.com/searchnew.aspx?Make=Chevrolet&Model=Blazer&ModelAndTrim=Blazer",
        "https://www.serrachevrolet.com/searchnew.aspx?Make=Chevrolet&Model=Blazer+EV&ModelAndTrim=Blazer+EV",
    ]


def test_dealer_on_multi_model_inventory_urls_skips_single_model_inputs() -> None:
    assert _dealer_on_multi_model_inventory_urls(
        "https://www.serrachevrolet.com/searchnew.aspx?Make=Chevrolet",
        make="Chevrolet",
        model="Blazer EV",
    ) == []


def test_inventory_url_recovery_candidates_builds_dealer_inspire_filtered_srp() -> None:
    route = ProviderRoute(
        platform_id="dealer_inspire",
        confidence=1.0,
        extraction_mode="structured_json",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-vehicles",),
        inventory_url_hint="https://dealer.example/new-vehicles/",
    )
    candidates = _inventory_url_recovery_candidates(
        inv_url="https://dealer.example/new-vehicles/pacifica/",
        base_url="https://dealer.example/",
        route=route,
        make="Chrysler",
        model="Pacifica",
        vehicle_condition="new",
    )
    assert candidates
    assert candidates[0].startswith("https://dealer.example/new-vehicles/?")
    assert any("_dFR%5Bmodel%5D%5B0%5D=Pacifica" in c for c in candidates)


def test_inventory_url_recovery_candidates_builds_dealer_dot_com_canonical_path() -> None:
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="structured_api",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-inventory/index.htm",),
        inventory_url_hint="https://dealer.example/new-vehicles/",
    )
    candidates = _inventory_url_recovery_candidates(
        inv_url="https://dealer.example/new-vehicles/",
        base_url="https://dealer.example/",
        route=route,
        make="GMC",
        model="Sierra 1500,Sierra 2500 HD",
        vehicle_condition="new",
    )
    assert any(c.startswith("https://dealer.example/new-inventory/index.htm?") for c in candidates)
    assert any("make=GMC" in c for c in candidates)


def test_effective_search_concurrency_uses_config_without_managed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.orchestrator_utils.settings.search_concurrency", 7)
    monkeypatch.setattr("app.services.orchestrator_utils.settings.zenrows_api_key", "")
    monkeypatch.setattr("app.services.orchestrator_utils.settings.scrapingbee_api_key", "")
    assert effective_search_concurrency() == 7


def test_effective_search_concurrency_caps_to_managed_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.orchestrator_utils.settings.search_concurrency", 12)
    monkeypatch.setattr("app.services.orchestrator_utils.settings.zenrows_api_key", "zr")
    monkeypatch.setattr("app.services.orchestrator_utils.settings.scrapingbee_api_key", "")
    monkeypatch.setattr("app.services.orchestrator_utils.settings.zenrows_max_concurrency", 2)
    monkeypatch.setattr("app.services.orchestrator_utils.settings.managed_scraper_max_concurrency", 3)
    monkeypatch.setattr("app.services.orchestrator_utils.settings.search_workers_per_managed_slot", 2)
    assert effective_search_concurrency() == 4


def test_effective_search_concurrency_reduces_fanout_for_deep_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.orchestrator_utils.settings.search_concurrency", 12)
    monkeypatch.setattr("app.services.orchestrator_utils.settings.zenrows_api_key", "zr")
    monkeypatch.setattr("app.services.orchestrator_utils.settings.scrapingbee_api_key", "")
    monkeypatch.setattr("app.services.orchestrator_utils.settings.zenrows_max_concurrency", 3)
    monkeypatch.setattr("app.services.orchestrator_utils.settings.managed_scraper_max_concurrency", 3)
    monkeypatch.setattr("app.services.orchestrator_utils.settings.search_workers_per_managed_slot", 2)
    assert effective_search_concurrency(requested_pages=10) == 3


def test_html_mentions_make_accepts_brand_aliases() -> None:
    assert html_mentions_make("<html><body>BMW motorcycles in stock</body></html>", "BMW Motorrad")
    assert html_mentions_make("<html><body>Indian bikes</body></html>", "Indian Motorcycle")


def test_find_inventory_url_prefers_real_inventory_over_model_list() -> None:
    html = """
    <html><body>
      <a href="/Brands/Manufacturer-Models/Model-List/Triumph">Triumph Models</a>
      <a href="/Inventory/All-Inventory-In-Stock">View Inventory</a>
    </body></html>
    """
    assert _find_inventory_url(html, "https://www.werkspowersports.com/") == (
        "https://www.werkspowersports.com/Inventory/All-Inventory-In-Stock"
    )


def test_find_inventory_url_prefers_unfiltered_inventory_over_fragment_scoped_shortcuts() -> None:
    html = """
    <html><body>
      <a href="/default.asp?page=xallinventory#page=xallinventory&vc=Cruiser">Cruiser View Inventory</a>
      <a href="/default.asp?page=xallinventory#page=xallinventory&make=polaris%20slingshot">Slingshot View Inventory</a>
      <a href="/default.asp?page=xallinventory">Shop Inventory</a>
    </body></html>
    """
    assert _find_inventory_url(html, "https://www.indianoftoledo.com/") == (
        "https://www.indianoftoledo.com/default.asp?page=xallinventory"
    )


def test_find_inventory_url_allows_onewater_external_inventory_link() -> None:
    html = """
    <html><body>
      <a href="/portfolio/">Brands</a>
      <a href="https://www.onewaterinventory.com/search/" target="_blank">Inventory</a>
    </body></html>
    """
    assert _find_inventory_url(html, "https://www.onewatermarine.com/") == (
        "https://www.onewaterinventory.com/search/"
    )


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
async def test_stream_search_persists_partial_failure_run() -> None:
    dealers = [
        DealershipFound(
            name="Timeout Motors",
            place_id="p1",
            address="1 Main St",
            website="https://timeout-motors.example",
        )
    ]
    store = get_account_store(settings.accounts_db_path)
    correlation_id = "test-partial-run"
    recorder = create_scrape_run_recorder(
        store=store,
        correlation_id=correlation_id,
        trigger_source="test",
        location="Detroit",
        make="Ford",
        model="",
        vehicle_category="car",
        vehicle_condition="all",
        inventory_scope="all",
        radius_miles=25,
        requested_max_dealerships=1,
        requested_max_pages_per_dealer=1,
        anon_key="test-anon-key",
    )

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
            side_effect=RuntimeError("homepage blocked"),
        ),
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "Detroit",
            "Ford",
            "",
            max_dealerships=1,
            max_pages_per_dealer=1,
            correlation_id=correlation_id,
            recorder=recorder,
        ):
            chunks.append(c)

    text = "".join(chunks)
    assert '"status": "error"' in text
    run = store.get_scrape_run(correlation_id, anon_key="test-anon-key")
    assert run is not None
    assert run.status == "partial_failure"
    assert run.dealerships_failed == 1
    assert run.dealerships_attempted == 1


@pytest.mark.asyncio
async def test_stream_search_recovers_from_homepage_failure_with_guessed_inventory_srp() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Bill Brown Ford",
            place_id="p1",
            address="32222 Plymouth Rd",
            website="https://www.billbrownford.net/",
        )
    ]

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if url == "https://www.billbrownford.net/" and page_kind == "homepage":
            raise RuntimeError("homepage blocked")
        if url == "https://www.billbrownford.net/inventory/new" and page_kind == "inventory":
            return "<html><body><div class='vehicle-card'>Inventory</div></body></html>", "zenrows_rendered"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

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
            return_value=ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2024,
                        make="Ford",
                        model="F-150",
                        price=55000,
                        listing_url="https://www.billbrownford.net/vdp/1",
                    )
                ],
                next_page_url=None,
            ),
        ),
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "Livonia, MI",
            "Ford",
            "",
            vehicle_condition="new",
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_llm.await_count == 0
    assert "https://www.billbrownford.net/vdp/1" in tail
    assert '"listings_found": 1' in tail
    assert '"status": "error"' not in tail


@pytest.mark.asyncio
async def test_stream_search_reroutes_team_velocity_model_hub_to_inventory_srp() -> None:
    from app.schemas import ExtractionResult, VehicleListing
    from app.services.dealer_platforms import PlatformProfile

    dealers = [
        DealershipFound(
            name="Jeffrey Acura",
            place_id="p1",
            address="30800 Gratiot Ave",
            website="https://www.jeffreyacura.com/",
        )
    ]
    homepage_html = """
    <html><body>
      <a href="/inventory/new">New Inventory</a>
      <footer>Website by Team Velocity</footer>
    </body></html>
    """
    model_hub_html = """
    <html><body>
      <div>Results: 56 Vehicles</div>
      <footer>Website by Team Velocity - https://www.teamvelocitymarketing.com/</footer>
    </body></html>
    """
    inventory_html = "<html><body><li class='v7list-results__item'>Inventory</li></body></html>"
    fetch_calls: list[tuple[str, str]] = []

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        fetch_calls.append((url, page_kind))
        if url == "https://www.jeffreyacura.com/" and page_kind == "homepage":
            return homepage_html, "direct"
        if url == "https://www.jeffreyacura.com/new-vehicles/" and page_kind == "inventory":
            return model_hub_html, "playwright"
        if url == "https://www.jeffreyacura.com/inventory/new" and page_kind == "inventory":
            return inventory_html, "playwright"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    detected_route = ProviderRoute(
        platform_id="dealer_inspire",
        confidence=0.85,
        extraction_mode="structured_json",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-vehicles", "inventory/new"),
        inventory_url_hint="https://www.jeffreyacura.com/new-vehicles/",
    )

    def fake_inventory_profile(_html: str, page_url: str = ""):
        if page_url.rstrip("/").endswith("/new-vehicles"):
            return PlatformProfile(
                platform_id="team_velocity",
                confidence=0.95,
                extraction_mode="hybrid",
                requires_render=True,
                inventory_path_hints=("inventory/new", "inventory/used"),
                detection_source="html_fingerprint",
            )
        return None

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
            return_value=detected_route,
        ),
        patch(
            "app.services.orchestrator.resolve_inventory_url_for_provider",
            return_value="https://www.jeffreyacura.com/new-vehicles/",
        ),
        patch(
            "app.services.orchestrator.detect_platform_profile",
            side_effect=fake_inventory_profile,
        ),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            return_value=ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2026,
                        make="Acura",
                        model="MDX",
                        price=59995,
                        listing_url="https://www.jeffreyacura.com/viewdetails/new/5J8YE1H39TL005887",
                    )
                ],
                next_page_url=None,
            ),
        ) as mock_extract,
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "Roseville, MI",
            "Acura",
            "",
            vehicle_condition="new",
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert ("https://www.jeffreyacura.com/inventory/new", "inventory") in fetch_calls
    assert mock_extract.call_args is not None
    assert mock_extract.call_args.kwargs["page_url"] == "https://www.jeffreyacura.com/inventory/new"
    assert mock_llm.await_count == 0
    assert '"listings_found": 1' in tail


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
        metrics = _kwargs.get("metrics")
        if isinstance(metrics, dict):
            metrics["playwright_recipe_used"] = metrics.get("playwright_recipe_used", 0) + 1
            metrics["playwright_recipe_platform_dealer_on"] = (
                metrics.get("playwright_recipe_platform_dealer_on", 0) + 1
            )
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
    assert "playwright_recipe_used" in tail
    assert "playwright_recipe_platform_dealer_on" in tail
    assert "extraction_metrics" in tail
    assert "pages_llm" in tail


@pytest.mark.asyncio
async def test_stream_search_boats_does_not_skip_only_because_homepage_lacks_make() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Test Marina",
            place_id="p1",
            address="1 Lake Dr",
            website="https://example-marine.test",
        )
    ]

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if url == "https://example-marine.test" and page_kind == "homepage":
            return "<html><body><h1>Welcome to the marina</h1><a href='/boats-for-sale/'>Inventory</a></body></html>", "direct"
        if url == "https://example-marine.test/boats-for-sale/" and page_kind == "inventory":
            return "<html><body><h1>Sylvan boats for sale</h1><div class='inv-card'>Inventory</div></body></html>", "direct"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    with (
        patch(
            "app.services.orchestrator.find_dealerships",
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
            return_value=ExtractionResult(
                vehicles=[
                    VehicleListing(
                        vehicle_category="boat",
                        year=2024,
                        make="Sylvan",
                        model="Mirage",
                        price=39999,
                        listing_url="https://example-marine.test/boats-for-sale/sylvan-mirage",
                    )
                ],
                next_page_url=None,
            ),
        ),
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "Detroit, MI",
            "Sylvan",
            "",
            vehicle_category="boat",
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_llm.await_count == 0
    assert "boats-for-sale/sylvan-mirage" in tail
    assert '"listings_found": 1' in tail
    assert 'dealer homepage; skipped' not in tail


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
async def test_stream_search_auto_expands_dealer_on_pagination_beyond_initial_route_budget() -> None:
    from app.schemas import ExtractionResult, PaginationInfo, VehicleListing

    dealers = [
        DealershipFound(
            name="DealerOn Test",
            place_id="p1",
            address="1 Main St",
            website="https://dealeron-example.test",
        )
    ]
    route = ProviderRoute(
        platform_id="dealer_on",
        confidence=1.0,
        extraction_mode="rendered_dom",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory",),
        inventory_url_hint="https://dealeron-example.test/inventory",
    )

    async def fake_fetch(url, *_args, **_kwargs):
        if url == "https://dealeron-example.test":
            return '<html><body><a href="/inventory?page=1">Inventory</a></body></html>', "direct"
        return "<html><body><div>Inventory</div></body></html>", "zenrows_rendered"

    structured_results = [
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2024,
                    make="Chevrolet",
                    model="Blazer",
                    price=32001,
                    listing_url="https://dealeron-example.test/vdp/1",
                )
            ],
            next_page_url="https://dealeron-example.test/inventory?page=2",
            pagination=PaginationInfo(current_page=1, total_pages=10, page_size=24, total_results=240, source="api"),
        ),
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2024,
                    make="Chevrolet",
                    model="Blazer",
                    price=32002,
                    listing_url="https://dealeron-example.test/vdp/2",
                )
            ],
            next_page_url="https://dealeron-example.test/inventory?page=3",
            pagination=PaginationInfo(current_page=2, total_pages=10, page_size=24, total_results=240, source="api"),
        ),
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2024,
                    make="Chevrolet",
                    model="Blazer",
                    price=32003,
                    listing_url="https://dealeron-example.test/vdp/3",
                )
            ],
            next_page_url="https://dealeron-example.test/inventory?page=4",
            pagination=PaginationInfo(current_page=3, total_pages=10, page_size=24, total_results=240, source="api"),
        ),
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2024,
                    make="Chevrolet",
                    model="Blazer",
                    price=32004,
                    listing_url="https://dealeron-example.test/vdp/4",
                )
            ],
            next_page_url=None,
            pagination=PaginationInfo(current_page=4, total_pages=10, page_size=24, total_results=240, source="api"),
        ),
    ]

    with (
        patch(
            "app.services.orchestrator.find_car_dealerships",
            new_callable=AsyncMock,
            return_value=dealers,
        ),
        patch("app.services.orchestrator.detect_or_lookup_provider", return_value=route),
        patch(
            "app.services.orchestrator.resolve_inventory_url_for_provider",
            return_value="https://dealeron-example.test/inventory?page=1",
        ),
        patch("app.services.orchestrator.get_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.set_cached_inventory_listings", return_value=None),
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
            "Chevrolet",
            "Blazer",
            max_dealerships=1,
            max_pages_per_dealer=10,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_structured.call_count == 4
    assert mock_llm.await_count == 0
    assert tail.count("https://dealeron-example.test/vdp/") == 4
    assert '"listings_found": 4' in tail
    assert '"pages_scraped": 4' in tail


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
