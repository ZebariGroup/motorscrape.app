"""Orchestrator unit tests with external I/O mocked."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from app.config import settings
from app.db.account_store import get_account_store
from app.schemas import DealershipFound, ExtractionResult, PaginationInfo, VehicleListing
from app.services.dealer_bias import dealer_preference_bias
from app.services.orchestrator_market import historical_market_points_for_listing
from app.services.orchestrator import (
    _bounded_phase_timeout,
    _cap_unknown_platform_fetch_timeout,
    _dealer_inspire_model_inventory_urls,
    _dealer_on_multi_model_inventory_urls,
    _effective_absolute_page_cap,
    _effective_dealer_timeout,
    _effective_max_pages_for_route,
    _find_inventory_url,
    _generic_vehicle_detail_overlay,
    _inventory_url_uses_scoped_filters,
    _inventory_url_recovery_candidates,
    _looks_like_model_index_batch,
    _needs_vdp_usage_enrichment,
    _oneaudi_all_inventory_urls,
    _room58_detail_overlay,
    _route_supports_team_velocity_style_inventory_reroute,
    _tesla_inventory_urls,
    _team_velocity_inventory_url_from_model_hub,
    _team_velocity_model_inventory_urls,
    stream_search,
)
from app.services.orchestrator_utils import (
    effective_max_pages_for_route,
    effective_search_concurrency,
    guess_franchise_inventory_srp_url,
    guess_franchise_inventory_srp_urls,
    html_mentions_make,
    prefer_https_website_url,
)
from app.services.platform_store import PlatformCacheEntry
from app.services.provider_router import ProviderRoute, speculative_inventory_urls_for_unknown_site
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


def test_guess_franchise_inventory_srp_urls_returns_multiple_candidates() -> None:
    candidates = guess_franchise_inventory_srp_urls("https://www.mhchevy.com/", "new")
    assert len(candidates) == 2
    assert candidates[0] == "https://www.mhchevy.com/inventory/new"
    assert candidates[1] == "https://www.mhchevy.com/new-vehicles/"

    used = guess_franchise_inventory_srp_urls("https://www.mhchevy.com/", "used")
    assert len(used) == 2
    assert used[0] == "https://www.mhchevy.com/inventory/used"
    assert used[1] == "https://www.mhchevy.com/used-vehicles/"


def test_dealer_preference_bias_penalizes_major_groups_and_favors_independents() -> None:
    major = dealer_preference_bias(
        "AutoNation Ford Bellevue",
        "https://www.autonationfordbellevue.com/",
        search_make="Smart",
    )
    independent = dealer_preference_bias(
        "City Smart Auto Sales",
        "https://www.citysmartauto.example/",
        search_make="Smart",
    )

    assert major < 0
    assert independent > 0
    assert independent > major


def test_unknown_site_speculative_inventory_urls_cover_small_dealer_patterns() -> None:
    candidates = speculative_inventory_urls_for_unknown_site(
        "https://smallcars.example/",
        "used",
        make="Smart",
        model="Fortwo",
    )

    assert "https://smallcars.example/used-cars-for-sale/" in candidates
    assert "https://smallcars.example/inventory/?make=Smart" in candidates


def test_unknown_site_speculative_inventory_urls_include_query_filtered_cars_for_sale_candidates() -> None:
    candidates = speculative_inventory_urls_for_unknown_site(
        "https://www.clawsonautosales.com/",
        "all",
        make="Cadillac",
        model="Escalade",
    )

    assert (
        "https://www.clawsonautosales.com/cars-for-sale/?Make=Cadillac&Model=Escalade"
        in candidates
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
    assert _effective_dealer_timeout(5) == 195.0
    assert _effective_dealer_timeout(10) == 240.0


def test_cap_unknown_platform_fetch_timeout_reduces_untyped_fetch_budgets() -> None:
    assert _cap_unknown_platform_fetch_timeout(95.0, page_kind="homepage", platform_id=None) == 45.0
    assert _cap_unknown_platform_fetch_timeout(95.0, page_kind="inventory", platform_id=None) == 55.0
    assert _cap_unknown_platform_fetch_timeout(95.0, page_kind="inventory", platform_id="dealer_on") == 95.0


def test_needs_vdp_usage_enrichment_flags_used_listings_missing_mileage() -> None:
    listings = [
        VehicleListing(
            vehicle_category="car",
            year=2022,
            make="Toyota",
            model="Camry",
            vehicle_condition="used",
            listing_url="https://dealer.example/used/1",
            usage_value=None,
            mileage=None,
        ),
        VehicleListing(
            vehicle_category="car",
            year=2021,
            make="Toyota",
            model="Camry",
            vehicle_condition="used",
            listing_url="https://dealer.example/used/2",
            usage_value=None,
            mileage=None,
        ),
    ]
    assert _needs_vdp_usage_enrichment(listings) is True


def test_historical_market_points_exclude_special_edition_trim_mismatches() -> None:
    listing = VehicleListing(
        vehicle_category="car",
        vehicle_condition="new",
        year=2024,
        make="Cadillac",
        model="CT5-V",
        trim="Blackwing",
        raw_title="2024 Cadillac CT5-V Blackwing",
        listing_url="https://dealer.example/ct5v-blackwing-1",
    )
    historical_pool = [
        {
            "vehicle_category": "car",
            "vehicle_condition": "new",
            "year": 2024,
            "make": "Cadillac",
            "model": "CT5-V",
            "trim": "Blackwing",
            "raw_title": "2024 Cadillac CT5-V Blackwing",
            "price": 94995,
            "listing_url": "https://dealer.example/ct5v-blackwing-2",
        },
        {
            "vehicle_category": "car",
            "vehicle_condition": "new",
            "year": 2024,
            "make": "Cadillac",
            "model": "CT5-V",
            "trim": "Blackwing",
            "raw_title": "2024 Cadillac CT5-V Blackwing",
            "price": 96995,
            "listing_url": "https://dealer.example/ct5v-blackwing-3",
        },
        {
            "vehicle_category": "car",
            "vehicle_condition": "new",
            "year": 2024,
            "make": "Cadillac",
            "model": "CT5-V",
            "trim": "V-Series",
            "raw_title": "2024 Cadillac CT5-V",
            "price": 75995,
            "listing_url": "https://dealer.example/ct5v-base-1",
        },
    ]

    points = historical_market_points_for_listing(listing, historical_pool)

    assert [point["price"] for point in points] == [94995.0, 96995.0]


def test_historical_market_points_skip_used_listings() -> None:
    listing = VehicleListing(
        vehicle_category="car",
        vehicle_condition="used",
        year=2024,
        make="Honda",
        model="Accord",
        trim="Sport",
        listing_url="https://dealer.example/accord-used-1",
    )
    historical_pool = [
        {
            "vehicle_category": "car",
            "vehicle_condition": "used",
            "year": 2024,
            "make": "Honda",
            "model": "Accord",
            "trim": "Sport",
            "price": 27995,
            "listing_url": "https://dealer.example/accord-used-2",
        },
        {
            "vehicle_category": "car",
            "vehicle_condition": "used",
            "year": 2024,
            "make": "Honda",
            "model": "Accord",
            "trim": "Sport",
            "price": 28495,
            "listing_url": "https://dealer.example/accord-used-3",
        },
        {
            "vehicle_category": "car",
            "vehicle_condition": "used",
            "year": 2024,
            "make": "Honda",
            "model": "Accord",
            "trim": "Sport",
            "price": 28995,
            "listing_url": "https://dealer.example/accord-used-4",
        },
    ]

    assert historical_market_points_for_listing(listing, historical_pool) == []


def test_needs_vdp_usage_enrichment_ignores_new_listings_missing_mileage() -> None:
    listings = [
        VehicleListing(
            vehicle_category="car",
            year=2026,
            make="Toyota",
            model="Camry",
            vehicle_condition="new",
            listing_url="https://dealer.example/new/1",
            usage_value=None,
            mileage=None,
        ),
        VehicleListing(
            vehicle_category="car",
            year=2026,
            make="Toyota",
            model="Camry",
            vehicle_condition="new",
            listing_url="https://dealer.example/new/2",
            usage_value=None,
            mileage=None,
        ),
    ]
    assert _needs_vdp_usage_enrichment(listings) is False


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


def test_effective_absolute_page_cap_extends_harley_shift_digital_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = ProviderRoute(
        platform_id="shift_digital",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory",),
    )
    monkeypatch.setattr("app.services.orchestrator.settings.harley_search_max_pages_per_dealer_cap", 24)
    assert _effective_absolute_page_cap(12, make="Harley-Davidson", route=route) == 24


def test_room58_detail_overlay_extracts_price_and_tracking_fields() -> None:
    html = """
    <html><body>
      <span class="inventoryModel-details-priceOld">$16,484</span>
      <span class="inventoryModel-details-price">Now $12,888</span>
      <script>
        var TRACKING_DATA_LAYER = {
          "dealerName":"Motown Harley-Davidson",
          "dealerCity":"Taylor",
          "dealerState":"MI",
          "vehicleDetails":{
            "status":"New",
            "year":"2026",
            "make":"Harley-Davidson",
            "model":"Road Glide Limited",
            "exteriorColor":"Vivid Black",
            "vin":"1HD1ALN18TB618713",
            "msrp":0,
            "displayedPrice":0
          }
        };
        window.TRACKING_FORM_DISPLAY_DATA = {};
      </script>
    </body></html>
    """
    from app.schemas import VehicleListing

    overlay = _room58_detail_overlay(
        VehicleListing(
            vehicle_category="motorcycle",
            listing_url="https://motownharley.com/inventory/962780/2026-harley-davidson-road-glide-limited-fltrxl",
            make="Harley-Davidson",
            model="Road Glide Limited",
        ),
        html,
    )
    assert overlay is not None
    assert overlay.price == 12888
    assert overlay.msrp == 16484
    assert overlay.vin == "1HD1ALN18TB618713"
    assert overlay.exterior_color == "Vivid Black"
    assert overlay.vehicle_condition == "new"
    assert overlay.inventory_location == "Motown Harley-Davidson (Taylor, MI)"


def test_generic_vehicle_detail_overlay_extracts_real_vdp_usage_fields() -> None:
    html = """
    <html><body>
      <h1>Certified Pre-Owned 2022 Toyota Tacoma 4x4</h1>
      <section>
        <h2>The overview</h2>
        <p>
          Exterior Color Lunar Rock
          Interior Color Cement
          Odometer 50,099 miles
          Body/Seating Truck Double Cab/5 seats
          Fuel Economy 18/22 MPG City/Hwy
          Details
          Transmission 6-Speed
          Drivetrain 4x4
          Engine V-6 cyl
          VIN 3TMCZ5ANXNM509639
          Stock Number NM509639P
        </p>
      </section>
    </body></html>
    """
    overlay = _generic_vehicle_detail_overlay(
        VehicleListing(
            vehicle_category="car",
            listing_url=(
                "https://www.suburbantoyotaoffarmingtonhills.com/certified/Toyota/"
                "2022-Toyota-Tacoma-049bf024ac1823e7d7937e3e246d2117.htm"
            ),
        ),
        html,
    )
    assert overlay is not None
    assert overlay.raw_title == "Certified Pre-Owned 2022 Toyota Tacoma 4x4"
    assert overlay.year == 2022
    assert overlay.make == "Toyota"
    assert overlay.model == "Tacoma"
    assert overlay.mileage == 50099
    assert overlay.usage_value == 50099
    assert overlay.usage_unit == "miles"
    assert overlay.vin == "3TMCZ5ANXNM509639"
    assert overlay.vehicle_identifier == "3TMCZ5ANXNM509639"
    assert overlay.vehicle_condition == "used"


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


def test_team_velocity_model_inventory_urls_acura_integra_style_paths() -> None:
    """OEM-style /inventory/new/{make}/{model} links (e.g. Jeffrey Acura) must be discoverable."""
    html = """
    <html><body>
      <a href="/inventory/new/acura/integra?paymenttype=lease&amp;years=2026&amp;instock=true&amp;intransit=true&amp;inproduction=true">Integra</a>
      <a href="/inventory/new/acura/integra">Integra</a>
      <a href="/inventory/new/acura/mdx">MDX</a>
    </body></html>
    """
    urls = _team_velocity_model_inventory_urls(
        html,
        "https://www.dealer.example/inventory/new",
        vehicle_condition="new",
        model="Integra",
    )
    assert urls == ["https://www.dealer.example/inventory/new/acura/integra"]
    assert not any("/acura/mdx" in u.lower() for u in urls)


def test_looks_like_model_index_batch_detects_acura_inventory_hub_rows() -> None:
    rows = [
        {
            "vin": "5J8YE1H33TL011152",
            "price": 55950,
            "listing_url": "https://www.jeffreyacura.com/inventory/new/acura/mdx?paymenttype=lease",
        },
        {
            "vin": "5J8TC2H42TL000402",
            "price": 47050,
            "listing_url": "https://www.jeffreyacura.com/inventory/new/acura/rdx?paymenttype=lease",
        },
    ]
    assert _looks_like_model_index_batch(rows, "https://www.jeffreyacura.com/inventory/new") is True


def test_looks_like_model_index_batch_rejects_true_vdp_rows() -> None:
    rows = [
        {
            "vin": "5J8YE1H33TL011152",
            "price": 55950,
            "listing_url": "https://www.jeffreyacura.com/viewdetails/new/5j8ye1h33tl011152/2026-acura-mdx-sport-utility",
        },
        {
            "vin": "5J8YE1H48TL023547",
            "price": 61450,
            "listing_url": "https://www.jeffreyacura.com/viewdetails/new/5j8ye1h48tl023547/2026-acura-mdx-sport-utility",
        },
    ]
    assert _looks_like_model_index_batch(rows, "https://www.jeffreyacura.com/inventory/new/acura/mdx") is False


def test_team_velocity_inventory_url_from_model_hub_preserves_model_path() -> None:
    rerouted = _team_velocity_inventory_url_from_model_hub(
        "https://www.example.com/new-vehicles/chevrolet-blazer",
        vehicle_condition="new",
    )
    assert rerouted == "https://www.example.com/inventory/new/chevrolet-blazer"


def test_route_supports_team_velocity_style_inventory_reroute() -> None:
    tv = ProviderRoute(
        platform_id="team_velocity",
        confidence=0.9,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-vehicles",),
        inventory_url_hint=None,
    )
    assert _route_supports_team_velocity_style_inventory_reroute(tv) is True
    di_hybrid = ProviderRoute(
        platform_id="dealer_inspire",
        confidence=0.85,
        extraction_mode="structured_json",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-vehicles", "inventory/new"),
        inventory_url_hint="https://www.example.com/new-vehicles/",
    )
    assert _route_supports_team_velocity_style_inventory_reroute(di_hybrid) is True
    di_plain = ProviderRoute(
        platform_id="dealer_inspire",
        confidence=0.85,
        extraction_mode="structured_json",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-vehicles", "new-inventory"),
        inventory_url_hint="https://www.example.com/new-vehicles/",
    )
    assert _route_supports_team_velocity_style_inventory_reroute(di_plain) is False


@pytest.mark.asyncio
async def test_stream_search_honda_acura_inventory_hub_falls_through_to_model_pages() -> None:
    dealers = [
        DealershipFound(
            name="Jeffrey Acura",
            place_id="p1",
            address="30800 Gratiot Ave",
            website="https://www.jeffreyacura.com/",
        )
    ]
    homepage_html = "<html><body><a href='/inventory/new'>New Inventory</a></body></html>"
    inventory_hub_html = """
    <html><body>
      <a href="/inventory/new/acura/mdx?paymenttype=lease">MDX</a>
      <a href="/inventory/new/acura/rdx?paymenttype=lease">RDX</a>
    </body></html>
    """
    fetch_calls: list[tuple[str, str]] = []

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        fetch_calls.append((url, page_kind))
        if url == "https://www.jeffreyacura.com/" and page_kind == "homepage":
            return homepage_html, "direct"
        if url == "https://www.jeffreyacura.com/inventory/new" and page_kind == "inventory":
            return inventory_hub_html, "direct"
        if url == "https://www.jeffreyacura.com/inventory/new/acura/mdx" and page_kind == "inventory":
            return "<html><body><div>MDX inventory</div></body></html>", "direct"
        if url == "https://www.jeffreyacura.com/inventory/new/acura/rdx" and page_kind == "inventory":
            return "<html><body><div>RDX inventory</div></body></html>", "direct"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    route = ProviderRoute(
        platform_id="honda_acura_inventory",
        confidence=1.0,
        extraction_mode="structured_json",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory/new", "inventory/used"),
        inventory_url_hint="https://www.jeffreyacura.com/inventory/new",
    )

    def fake_extract(platform_id, **kwargs):
        page_url = kwargs["page_url"]
        if platform_id == "honda_acura_inventory" and page_url == "https://www.jeffreyacura.com/inventory/new":
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2026,
                        make="Acura",
                        model="MDX",
                        price=55950,
                        vin="5J8YE1H33TL011152",
                        listing_url="https://www.jeffreyacura.com/inventory/new/acura/mdx?paymenttype=lease",
                    ),
                    VehicleListing(
                        year=2026,
                        make="Acura",
                        model="RDX",
                        price=47050,
                        vin="5J8TC2H42TL000402",
                        listing_url="https://www.jeffreyacura.com/inventory/new/acura/rdx?paymenttype=lease",
                    ),
                ],
                next_page_url=None,
                pagination=None,
            )
        if platform_id == "honda_acura_inventory" and page_url == "https://www.jeffreyacura.com/inventory/new/acura/mdx":
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2026,
                        make="Acura",
                        model="MDX",
                        price=61450,
                        vin="5J8YE1H48TL023547",
                        listing_url="https://www.jeffreyacura.com/viewdetails/new/5j8ye1h48tl023547/2026-acura-mdx-sport-utility",
                    )
                ],
                next_page_url=None,
                pagination=None,
            )
        if platform_id == "honda_acura_inventory" and page_url == "https://www.jeffreyacura.com/inventory/new/acura/rdx":
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2026,
                        make="Acura",
                        model="RDX",
                        price=47050,
                        vin="5J8TC2H42TL000402",
                        listing_url="https://www.jeffreyacura.com/viewdetails/new/5j8tc2h42tl000402/2026-acura-rdx-suv",
                    )
                ],
                next_page_url=None,
                pagination=None,
            )
        return None

    with (
        patch("app.services.orchestrator.find_car_dealerships", new_callable=AsyncMock, return_value=dealers),
        patch("app.services.orchestrator.get_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.set_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.fetch_page_html", new_callable=AsyncMock, side_effect=fake_fetch),
        patch("app.services.orchestrator.detect_or_lookup_provider", return_value=route),
        patch(
            "app.services.orchestrator.resolve_inventory_url_for_provider",
            return_value="https://www.jeffreyacura.com/inventory/new",
        ),
        patch("app.services.orchestrator.extract_with_provider", side_effect=fake_extract),
        patch("app.services.orchestrator.remember_provider_success", return_value=None),
        patch("app.services.orchestrator.record_provider_failure", return_value=None),
    ):
        chunks: list[str] = []
        async for c in stream_search("48235", "Acura", "", max_dealerships=1, max_pages_per_dealer=1):
            chunks.append(c)

    tail = "".join(chunks)
    assert ("https://www.jeffreyacura.com/inventory/new/acura/mdx", "inventory") in fetch_calls
    assert ("https://www.jeffreyacura.com/inventory/new/acura/rdx", "inventory") in fetch_calls
    assert "inventory/new/acura/mdx?paymenttype=lease" not in tail
    assert '"listings_found": 2' in tail


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


def test_oneaudi_all_inventory_urls_expands_new_and_used() -> None:
    assert _oneaudi_all_inventory_urls("https://www.audidealer.example/en/inventory/new/audi-q5/") == [
        "https://www.audidealer.example/en/inventory/new/",
        "https://www.audidealer.example/en/inventory/used/",
    ]


def test_tesla_inventory_urls_expand_model_variants_when_model_not_specified() -> None:
    urls = _tesla_inventory_urls(
        "https://www.tesla.com/inventory/new?arrangeby=relevance",
        vehicle_condition="all",
        model="",
    )
    assert "https://www.tesla.com/inventory/new/m3?arrangeby=relevance" in urls
    assert "https://www.tesla.com/inventory/used/m3?arrangeby=relevance" in urls
    assert any("/inventory/new/my" in url for url in urls)


def test_tesla_inventory_urls_adds_zip_and_range_when_missing() -> None:
    urls = _tesla_inventory_urls(
        "https://www.tesla.com/findus/location/store/centurycity",
        vehicle_condition="new",
        model="Model Y",
        fallback_zip="10250 Santa Monica Blvd Los Angeles, CA 90067",
        fallback_range_miles=25,
    )
    assert urls == [
        "https://www.tesla.com/inventory/new/my?arrangeby=relevance&zip=90067&range=25",
    ]


def test_inventory_url_uses_scoped_filters_recognizes_tesla_zip_scope() -> None:
    assert _inventory_url_uses_scoped_filters(
        "https://www.tesla.com/inventory/new/m3?arrangeby=relevance&zip=60606&range=25",
        make="Tesla",
        model="",
    )
    assert not _inventory_url_uses_scoped_filters(
        "https://www.tesla.com/inventory/new/m3?arrangeby=relevance",
        make="Tesla",
        model="",
    )


def test_inventory_url_recovery_candidates_builds_tesla_model_paths() -> None:
    route = ProviderRoute(
        platform_id="tesla_inventory",
        confidence=1.0,
        extraction_mode="provider",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory/new", "inventory/used"),
        inventory_url_hint="https://www.tesla.com/inventory/new?arrangeby=relevance",
    )
    candidates = _inventory_url_recovery_candidates(
        inv_url="https://www.tesla.com/inventory/new?arrangeby=relevance",
        base_url="https://www.tesla.com/findus/location/store/centurycity",
        route=route,
        make="Tesla",
        model="",
        vehicle_condition="all",
    )
    assert "https://www.tesla.com/inventory/new/m3?arrangeby=relevance" in candidates
    assert "https://www.tesla.com/inventory/used/my?arrangeby=relevance" in candidates


def test_inventory_url_recovery_candidates_adds_tesla_zip_context() -> None:
    route = ProviderRoute(
        platform_id="tesla_inventory",
        confidence=1.0,
        extraction_mode="provider",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory/new", "inventory/used"),
        inventory_url_hint="https://www.tesla.com/findus/location/store/centurycity",
    )
    candidates = _inventory_url_recovery_candidates(
        inv_url="https://www.tesla.com/findus/location/store/centurycity",
        base_url="https://www.tesla.com/findus/location/store/centurycity",
        route=route,
        make="Tesla",
        model="",
        vehicle_condition="all",
        fallback_zip="Los Angeles, CA 90067",
        fallback_range_miles=25,
    )
    assert "https://www.tesla.com/inventory/new/m3?arrangeby=relevance&zip=90067&range=25" in candidates
    assert "https://www.tesla.com/inventory/used/my?arrangeby=relevance&zip=90067&range=25" in candidates


@pytest.mark.asyncio
async def test_stream_search_tesla_fails_fast_as_unsupported() -> None:
    with patch(
        "app.services.orchestrator.find_car_dealerships",
        new_callable=AsyncMock,
        side_effect=AssertionError("Tesla should not reach dealership discovery"),
    ) as mock_find_dealers:
        chunks: list[str] = []
        async for c in stream_search(
            "60606",
            "Tesla",
            "Model 3",
            vehicle_condition="new",
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_find_dealers.await_count == 0
    assert "Tesla inventory is temporarily unsupported." in tail
    assert '"ok": false' in tail


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


def test_inventory_url_recovery_candidates_builds_family_model_srp_for_unrecognized_route() -> None:
    candidates = _inventory_url_recovery_candidates(
        inv_url="https://www.mossyford.com",
        base_url="https://www.mossyford.com/",
        route=None,
        make="Ford",
        model="Bronco",
        vehicle_condition="new",
    )
    # Slash-style is now preferred; both variants should be present in candidates
    assert (
        "https://www.mossyford.com/inventory/new/ford/bronco" in candidates
        or "https://www.mossyford.com/inventory/new/ford-bronco" in candidates
    )


def test_inventory_url_recovery_candidates_include_ford_family_slash_variant() -> None:
    route = ProviderRoute(
        platform_id="ford_family_inventory",
        confidence=1.0,
        extraction_mode="structured_html",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory/new", "inventory/used"),
        inventory_url_hint="https://www.chulavistaford.com/inventory/new/ford-bronco",
    )
    candidates = _inventory_url_recovery_candidates(
        inv_url="https://www.chulavistaford.com/inventory/new/ford-bronco",
        base_url="https://www.chulavistaford.com/",
        route=route,
        make="Ford",
        model="Bronco",
        vehicle_condition="new",
    )
    assert "https://www.chulavistaford.com/inventory/new/ford/bronco" in candidates
    assert "https://www.chulavistaford.com/inventory/new" in candidates


def test_inventory_url_recovery_candidates_add_www_ddc_path_for_express_hosts() -> None:
    route = ProviderRoute(
        platform_id="dealer_inspire",
        confidence=1.0,
        extraction_mode="structured_json",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-vehicles",),
        inventory_url_hint="https://express.mbbloomfield.com/new-vehicles/",
    )
    candidates = _inventory_url_recovery_candidates(
        inv_url="https://express.mbbloomfield.com/new-vehicles/",
        base_url="https://www.mbbloomfield.com/",
        route=route,
        make="Mercedes-Benz",
        model="",
        vehicle_condition="new",
    )
    assert "https://www.mbbloomfield.com/new-inventory/index.htm" in candidates


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


def test_find_inventory_url_skips_featured_detail_links_for_harley_homepages() -> None:
    html = """
    <html><body>
      <a href="/inventory/951738/2021-harley-davidson-road-king-special-flhrxs">Find out more</a>
      <a href="/new-inventory">New Harleys</a>
      <a href="/used-inventory">Used Harleys</a>
    </body></html>
    """
    assert _find_inventory_url(html, "https://motorcityharley.com/", vehicle_condition="all") == (
        "https://motorcityharley.com/new-inventory"
    )


def test_find_inventory_url_ignores_mailto_links() -> None:
    html = """
    <html><body>
      <a href="mailto:recepcionventaslandrover@movilcar.com">Nuevos vehiculos</a>
      <a href="/inventory/new">Inventory</a>
    </body></html>
    """
    assert _find_inventory_url(html, "https://movilcar.landrover.es/") == (
        "https://movilcar.landrover.es/inventory/new"
    )


def test_find_inventory_url_all_condition_prefers_unscoped_inventory_over_preowned_empty_filters() -> None:
    html = """
    <html><body>
      <a href="/inventory/?type=&amp;make=&amp;condition=pre-owned">Used Inventory</a>
      <a href="/inventory/">All Inventory</a>
    </body></html>
    """
    assert _find_inventory_url(html, "https://www.koopersmarine.com/", vehicle_condition="all") == (
        "https://www.koopersmarine.com/inventory/"
    )


def test_find_inventory_url_all_condition_sanitizes_preowned_empty_query_when_only_option_exists() -> None:
    html = """
    <html><body>
      <a href="/inventory/?type=&amp;make=&amp;condition=pre-owned">Inventory</a>
    </body></html>
    """
    assert _find_inventory_url(html, "https://www.koopersmarine.com/", vehicle_condition="all") == (
        "https://www.koopersmarine.com/inventory/"
    )


def test_find_inventory_url_eu_prefers_oem_used_search_over_news_model_pages() -> None:
    html = """
    <html><body>
      <a href="/passengercars/news/models/suv/der-neue-vollelektrische-mercedes-benz-glc.html">Der neue GLC</a>
      <a href="https://gebrauchtwagen.mercedes-benz.de/hammer">Gebrauchtwagensuche</a>
    </body></html>
    """
    assert _find_inventory_url(
        html,
        "https://www.mercedes-benz-hammer.de/",
        vehicle_condition="all",
        market_region="eu",
    ) == "https://gebrauchtwagen.mercedes-benz.de/hammer"


@pytest.mark.asyncio
async def test_stream_search_does_not_skip_make_when_dealer_context_matches() -> None:
    dealers = [
        DealershipFound(
            name="Volkswagen Zentrum Example",
            place_id="p1",
            address="100 Main St",
            website="https://www.example-vw.de/",
        )
    ]

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if url == "https://www.example-vw.de/" and page_kind == "homepage":
            return '<html><body><a href="/inventar">Inventar</a></body></html>', "direct"
        if page_kind == "inventory":
            # Intentionally no explicit "Volkswagen" token in HTML to exercise make gating fallback.
            return "<html><body><div>Fahrzeugliste</div></body></html>", "direct"
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
            "app.services.orchestrator.detect_or_lookup_provider",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.extract_with_provider",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
            return_value=ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2023,
                        make="Volkswagen",
                        model="Golf",
                        price=24995,
                        listing_url="https://www.example-vw.de/vdp/golf-1",
                    )
                ],
                next_page_url=None,
                pagination=None,
            ),
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "Germany",
            "Volkswagen",
            "",
            market_region="eu",
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_llm.await_count == 1
    assert "https://www.example-vw.de/vdp/golf-1" in tail
    assert '"listings_found": 1' in tail


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
async def test_stream_search_prefers_smaller_dealers_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.orchestrator.settings.inventory_cache_enabled", False)
    dealers = [
        DealershipFound(
            name="AutoNation Ford Bellevue",
            place_id="p1",
            address="1 Main St",
            website="https://www.autonationfordbellevue.com/",
        ),
        DealershipFound(
            name="City Smart Auto Sales",
            place_id="p2",
            address="2 Main St",
            website="https://www.citysmartauto.example/",
        ),
    ]

    async def first_visited_url(*, prefer_small_dealers: bool) -> str:
        visited: list[str] = []

        async def fake_fetch(url: str, *_args, **_kwargs) -> str:
            visited.append(url)
            raise RuntimeError("stop after first fetch")

        with (
            patch(
                "app.services.orchestrator.find_car_dealerships",
                new_callable=AsyncMock,
                return_value=dealers,
            ),
            patch("app.services.orchestrator.get_scores", return_value={}),
            patch("app.services.orchestrator.fetch_page_html", side_effect=fake_fetch),
        ):
            async for _ in stream_search(
                "Seattle",
                "Smart",
                "",
                max_dealerships=1,
                max_pages_per_dealer=1,
                prefer_small_dealers=prefer_small_dealers,
            ):
                pass
        assert visited
        return visited[0]

    default_first = await first_visited_url(prefer_small_dealers=False)
    biased_first = await first_visited_url(prefer_small_dealers=True)

    assert "autonationfordbellevue.com" in default_first
    assert "citysmartauto.example" in biased_first


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
async def test_stream_search_cancellation_persists_canceled_run() -> None:
    dealers = [
        DealershipFound(
            name="Slow Motors",
            place_id="p1",
            address="1 Main St",
            website="https://slow-motors.example",
        )
    ]
    store = get_account_store(settings.accounts_db_path)
    correlation_id = "test-canceled-run"
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
    fetch_started = asyncio.Event()

    async def fake_fetch(*_args, **_kwargs):
        fetch_started.set()
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async def consume() -> None:
        async for _ in stream_search(
            "Detroit",
            "Ford",
            "",
            max_dealerships=1,
            max_pages_per_dealer=1,
            correlation_id=correlation_id,
            recorder=recorder,
        ):
            pass

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
    ):
        task = asyncio.create_task(consume())
        await fetch_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run = store.get_scrape_run(correlation_id, anon_key="test-anon-key")
    assert run is not None
    assert run.status == "canceled"
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_stream_search_recovers_from_ford_family_zero_result_hyphen_url() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Chula Vista Ford",
            place_id="p1",
            address="560 Auto Park Dr",
            website="https://www.chulavistaford.com/",
        )
    ]
    hyphen_url = "https://www.chulavistaford.com/inventory/new/ford-bronco"
    slash_url = "https://www.chulavistaford.com/inventory/new/ford/bronco"
    route = ProviderRoute(
        platform_id="ford_family_inventory",
        confidence=1.0,
        extraction_mode="structured_html",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory/new", "inventory/used"),
        inventory_url_hint=hyphen_url,
    )

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if url == "https://www.chulavistaford.com/" and page_kind == "homepage":
            return "<html><body>Ford inventory</body></html>", "direct"
        if url == hyphen_url and page_kind == "inventory":
            return "<html><body><div class='vehicle_results_label'>Results: 0 Vehicles</div></body></html>", "direct"
        if url == slash_url and page_kind == "inventory":
            return "<html><body><div class='si-vehicle-box'><a href='/viewdetails/1'>View Details</a></div></body></html>", "playwright"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    def fake_extract(platform_id, **kwargs):
        page_url = kwargs["page_url"]
        if platform_id == "ford_family_inventory" and page_url == hyphen_url:
            return ExtractionResult(vehicles=[], next_page_url=None, pagination=None)
        if platform_id == "ford_family_inventory" and page_url == slash_url:
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2025,
                        make="Ford",
                        model="Bronco",
                        price=58000,
                        listing_url="https://www.chulavistaford.com/viewdetails/1",
                    )
                ],
                next_page_url=None,
                pagination=None,
            )
        return None

    with (
        patch("app.services.orchestrator.find_car_dealerships", new_callable=AsyncMock, return_value=dealers),
        patch("app.services.orchestrator.get_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.set_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.fetch_page_html", new_callable=AsyncMock, side_effect=fake_fetch),
        patch("app.services.orchestrator.detect_or_lookup_provider", return_value=route),
        patch("app.services.orchestrator.resolve_inventory_url_for_provider", return_value=hyphen_url),
        patch("app.services.orchestrator.extract_with_provider", side_effect=fake_extract),
        patch("app.services.orchestrator.remember_provider_success", return_value=None),
        patch("app.services.orchestrator.record_provider_failure", return_value=None),
    ):
        chunks: list[str] = []
        async for c in stream_search("91910", "Ford", "Bronco", max_dealerships=1, max_pages_per_dealer=1):
            chunks.append(c)

    tail = "".join(chunks)
    assert slash_url in tail
    assert '"listings_found": 1' in tail
    assert '"ford_recovery_urls": ["https://www.chulavistaford.com/inventory/new/ford/bronco"' in tail


@pytest.mark.asyncio
async def test_stream_search_recovers_from_dealer_on_scoped_empty_results() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="George Matick Chevrolet",
            place_id="p1",
            address="14001 Telegraph Rd",
            website="https://www.matickchevy.com/",
        )
    ]
    scoped_url = "https://www.matickchevy.com/searchnew.aspx?Make=Chevrolet&Model=Blazer&ModelAndTrim=Blazer"
    make_url = "https://www.matickchevy.com/searchnew.aspx?Make=Chevrolet"
    route = ProviderRoute(
        platform_id="dealer_on",
        confidence=1.0,
        extraction_mode="rendered_dom",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("searchnew.aspx", "searchused.aspx"),
        inventory_url_hint=scoped_url,
    )

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if url == "https://www.matickchevy.com/" and page_kind == "homepage":
            return "<html><body>DealerOn homepage</body></html>", "direct"
        if url == scoped_url and page_kind == "inventory":
            return "<html><body><div>Results: 0 Vehicles</div></body></html>", "direct"
        if url == make_url and page_kind == "inventory":
            return "<html><body><div class='vehicle-card'>Inventory</div></body></html>", "zenrows_rendered"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    def fake_extract(platform_id, **kwargs):
        page_url = kwargs["page_url"]
        if platform_id == "dealer_on" and page_url == scoped_url:
            return ExtractionResult(vehicles=[], next_page_url=None, pagination=None)
        if platform_id == "dealer_on" and page_url == make_url:
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2025,
                        make="Chevrolet",
                        model="Blazer",
                        price=42995,
                        listing_url="https://www.matickchevy.com/VehicleDetails/new-2025-Chevrolet-Blazer-1",
                    )
                ],
                next_page_url=None,
                pagination=None,
            )
        return None

    with (
        patch("app.services.orchestrator.find_car_dealerships", new_callable=AsyncMock, return_value=dealers),
        patch("app.services.orchestrator.get_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.set_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.fetch_page_html", new_callable=AsyncMock, side_effect=fake_fetch),
        patch("app.services.orchestrator.detect_or_lookup_provider", return_value=route),
        patch("app.services.orchestrator.resolve_inventory_url_for_provider", return_value=scoped_url),
        patch("app.services.orchestrator.extract_with_provider", side_effect=fake_extract),
        patch("app.services.orchestrator.remember_provider_success", return_value=None),
        patch("app.services.orchestrator.record_provider_failure", return_value=None),
    ):
        chunks: list[str] = []
        async for c in stream_search("48235", "Chevrolet", "Blazer", max_dealerships=1, max_pages_per_dealer=1):
            chunks.append(c)

    tail = "".join(chunks)
    assert make_url in tail
    assert '"listings_found": 1' in tail


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
async def test_stream_search_prioritizes_higher_scored_dealers_first() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Dealer A",
            place_id="p1",
            address="1 Main St",
            website="https://dealer-a.example/",
        ),
        DealershipFound(
            name="Dealer B",
            place_id="p2",
            address="2 Main St",
            website="https://dealer-b.example/",
        ),
    ]
    fetch_urls: list[str] = []

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        fetch_urls.append(url)
        if page_kind == "homepage":
            return '<html><body><a href="/inventory">Inventory</a></body></html>', "direct"
        return "<html><body><div class='vehicle-card'>Inventory</div></body></html>", "direct"

    with (
        patch("app.services.orchestrator.find_car_dealerships", new_callable=AsyncMock, return_value=dealers),
        patch("app.services.orchestrator.effective_search_concurrency", return_value=1),
        patch("app.services.orchestrator.get_scores", return_value={"dealer-a.example": 20.0, "dealer-b.example": 80.0}),
        patch("app.services.orchestrator.get_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.set_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.fetch_page_html", new_callable=AsyncMock, side_effect=fake_fetch),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            return_value=ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2024,
                        make="Toyota",
                        model="Camry",
                        price=28000,
                        listing_url="https://dealer.example/vdp/1",
                    )
                ],
                next_page_url=None,
            ),
        ),
        patch("app.services.orchestrator.extract_vehicles_from_html", new_callable=AsyncMock),
    ):
        async for _ in stream_search("Detroit", "Toyota", "", max_dealerships=2, max_pages_per_dealer=1):
            pass

    homepage_fetches = [url for url in fetch_urls if url.endswith(".example/")]
    assert homepage_fetches[:2] == ["https://dealer-b.example/", "https://dealer-a.example/"]


@pytest.mark.asyncio
async def test_stream_search_announces_full_dealer_lineup_before_scraping_starts() -> None:
    dealers = [
        DealershipFound(
            name="Dealer A",
            place_id="p1",
            address="1 Main St",
            website="https://dealer-a.example/",
        ),
        DealershipFound(
            name="Dealer B",
            place_id="p2",
            address="2 Main St",
            website="https://dealer-b.example/",
        ),
        DealershipFound(
            name="Dealer C",
            place_id="p3",
            address="3 Main St",
            website="https://dealer-c.example/",
        ),
    ]

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if page_kind == "homepage":
            return '<html><body><a href="/inventory">Inventory</a></body></html>', "direct"
        return "<html><body><div class='vehicle-card'>Inventory</div></body></html>", "direct"

    with (
        patch("app.services.orchestrator.find_car_dealerships", new_callable=AsyncMock, return_value=dealers),
        patch("app.services.orchestrator.effective_search_concurrency", return_value=1),
        patch("app.services.orchestrator.get_scores", return_value={}),
        patch("app.services.orchestrator.get_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.set_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.fetch_page_html", new_callable=AsyncMock, side_effect=fake_fetch),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            return_value=ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2024,
                        make="Toyota",
                        model="Camry",
                        price=28000,
                        listing_url="https://dealer.example/vdp/1",
                    )
                ],
                next_page_url=None,
            ),
        ),
        patch("app.services.orchestrator.extract_vehicles_from_html", new_callable=AsyncMock),
    ):
        chunks: list[str] = []
        async for c in stream_search("Detroit", "Toyota", "", max_dealerships=3, max_pages_per_dealer=1):
            chunks.append(c)

    text = "".join(chunks)
    before_first_scraping = text.split('"status": "scraping"', 1)[0]
    assert before_first_scraping.count('"status": "queued"') == 3
    assert '"name": "Dealer A"' in before_first_scraping
    assert '"name": "Dealer B"' in before_first_scraping
    assert '"name": "Dealer C"' in before_first_scraping


@pytest.mark.asyncio
async def test_stream_search_records_dealer_score_on_success() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Scored Dealer",
            place_id="p1",
            address="1 Main St",
            website="https://scored-dealer.example/",
        )
    ]

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if page_kind == "homepage":
            return '<html><body><a href="/inventory">Inventory</a></body></html>', "direct"
        return "<html><body><div class='vehicle-card'>Inventory</div></body></html>", "direct"

    with (
        patch("app.services.orchestrator.find_car_dealerships", new_callable=AsyncMock, return_value=dealers),
        patch("app.services.orchestrator.get_scores", return_value={}),
        patch("app.services.orchestrator.get_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.set_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.fetch_page_html", new_callable=AsyncMock, side_effect=fake_fetch),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            return_value=ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2024,
                        make="Toyota",
                        model="Camry",
                        price=28000,
                        vin="4T1B11HK5KU123456",
                        vehicle_identifier="4T1B11HK5KU123456",
                        listing_url="https://scored-dealer.example/vdp/1",
                    )
                ],
                next_page_url=None,
            ),
        ),
        patch("app.services.orchestrator.extract_vehicles_from_html", new_callable=AsyncMock),
        patch("app.services.orchestrator.record_scrape_outcome") as mock_record_score,
    ):
        async for _ in stream_search("Detroit", "Toyota", "", max_dealerships=1, max_pages_per_dealer=1):
            pass

    mock_record_score.assert_called_once()
    _, kwargs = mock_record_score.call_args
    assert kwargs["listings"] == 1
    assert kwargs["price_fill"] == 1.0
    assert kwargs["vin_fill"] == 1.0
    assert kwargs["failed"] is False


@pytest.mark.asyncio
async def test_stream_search_skips_homepage_when_platform_cache_has_inventory_hint() -> None:
    from datetime import UTC, datetime

    dealers = [
        DealershipFound(
            name="Hinted Dealer",
            place_id="p1",
            address="1 Main St",
            website="https://hinted-dealer.example/",
        )
    ]
    fetch_calls: list[tuple[str, str]] = []

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        fetch_calls.append((url, page_kind))
        if url.startswith("https://hinted-dealer.example/searchnew.aspx") and page_kind == "inventory":
            return "<html><body><div class='vehicle-card'>Inventory</div></body></html>", "direct"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    cached_entry = PlatformCacheEntry(
        domain="hinted-dealer.example",
        platform_id="dealer_on",
        confidence=0.95,
        extraction_mode="rendered_dom",
        requires_render=False,
        inventory_url_hint="https://hinted-dealer.example/searchnew.aspx",
        detection_source="cache",
        last_verified_at=datetime.now(UTC),
    )

    with (
        patch("app.services.orchestrator.find_car_dealerships", new_callable=AsyncMock, return_value=dealers),
        patch("app.services.orchestrator.get_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.set_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.platform_store.get", return_value=cached_entry),
        patch("app.services.orchestrator.fetch_page_html", new_callable=AsyncMock, side_effect=fake_fetch),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            return_value=ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2024,
                        make="Toyota",
                        model="Camry",
                        price=28000,
                        listing_url="https://hinted-dealer.example/vdp/1",
                    )
                ],
                next_page_url=None,
            ),
        ),
        patch("app.services.orchestrator.extract_vehicles_from_html", new_callable=AsyncMock),
    ):
        chunks: list[str] = []
        async for c in stream_search("Detroit", "Toyota", "", max_dealerships=1, max_pages_per_dealer=1):
            chunks.append(c)

    assert ("https://hinted-dealer.example/", "homepage") not in fetch_calls
    assert ("https://hinted-dealer.example/searchnew.aspx?Make=Toyota", "inventory") in fetch_calls
    assert "Using a known inventory route." in "".join(chunks)


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
async def test_stream_search_reroutes_dealer_inspire_model_hub_when_hints_include_inventory_new() -> None:
    """Stale dealer_inspire cache + /inventory/new hints must still reach the Vue SRP without a TV re-detect."""
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Hybrid Inspire Dealer",
            place_id="p1",
            address="1 Main St",
            website="https://www.hybrid-dealer.example/",
        )
    ]
    model_hub_html = "<html><body><div>Results: 10 Vehicles</div></body></html>"
    inventory_html = "<html><body><li class='v7list-results__item'>Inventory</li></body></html>"
    fetch_calls: list[tuple[str, str]] = []

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        fetch_calls.append((url, page_kind))
        if url == "https://www.hybrid-dealer.example/" and page_kind == "homepage":
            return "<html><body><a href='/new-vehicles/'>New</a></body></html>", "direct"
        if url == "https://www.hybrid-dealer.example/new-vehicles/" and page_kind == "inventory":
            return model_hub_html, "direct"
        if url == "https://www.hybrid-dealer.example/inventory/new" and page_kind == "inventory":
            return inventory_html, "direct"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    detected_route = ProviderRoute(
        platform_id="dealer_inspire",
        confidence=0.85,
        extraction_mode="structured_json",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-vehicles", "inventory/new"),
        inventory_url_hint="https://www.hybrid-dealer.example/new-vehicles/",
    )

    with (
        patch(
            "app.services.orchestrator.find_car_dealerships",
            new_callable=AsyncMock,
            return_value=dealers,
        ),
        patch(
            "app.services.orchestrator.platform_store.get",
            return_value=None,
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
            return_value="https://www.hybrid-dealer.example/new-vehicles/",
        ),
        patch(
            "app.services.orchestrator.detect_platform_profile",
            return_value=None,
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
                        listing_url="https://www.hybrid-dealer.example/viewdetails/new/VIN",
                    )
                ],
                next_page_url=None,
            ),
        ) as mock_extract,
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ),
    ):
        async for _ in stream_search(
            "Detroit, MI",
            "Acura",
            "",
            vehicle_condition="new",
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            pass

    assert ("https://www.hybrid-dealer.example/inventory/new", "inventory") in fetch_calls
    assert mock_extract.call_args is not None
    assert mock_extract.call_args.kwargs["page_url"] == "https://www.hybrid-dealer.example/inventory/new"


@pytest.mark.asyncio
async def test_stream_search_prefilters_dealer_inspire_multi_model_queries() -> None:
    dealers = [
        DealershipFound(
            name="Classic Chevrolet Sugar Land",
            place_id="p1",
            address="13115 Southwest Fwy, Sugar Land, TX 77478, USA",
            website="https://www.classicchevysugarland.com/",
        )
    ]
    blazer_url = (
        "https://www.classicchevysugarland.com/new-vehicles/"
        "?_dFR%5Btype%5D%5B0%5D=New&_dFR%5Bmake%5D%5B0%5D=Chevrolet&_dFR%5Bmodel%5D%5B0%5D=Blazer"
    )
    blazer_ev_url = (
        "https://www.classicchevysugarland.com/new-vehicles/"
        "?_dFR%5Btype%5D%5B0%5D=New&_dFR%5Bmake%5D%5B0%5D=Chevrolet&_dFR%5Bmodel%5D%5B0%5D=Blazer+EV"
    )
    fetch_calls: list[tuple[str, str]] = []
    structured_calls: list[str] = []

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        fetch_calls.append((url, page_kind))
        if url == "https://www.classicchevysugarland.com/" and page_kind == "homepage":
            return "<html><body><a href='/new-vehicles/'>New Vehicles</a></body></html>", "direct"
        if url == blazer_url and page_kind == "inventory":
            return "<html><body><div>filtered-blazer</div></body></html>", "direct"
        if url == blazer_ev_url and page_kind == "inventory":
            return "<html><body><div>filtered-blazer-ev</div></body></html>", "direct"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    def structured_result_for_url(*, page_url: str, html: str, **_kwargs):
        structured_calls.append(page_url)
        if page_url == blazer_url:
            assert "filtered-blazer" in html
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2025,
                        make="Chevrolet",
                        model="Blazer",
                        price=44995,
                        listing_url="https://www.classicchevysugarland.com/viewdetails/new/BLAZER1",
                    )
                ],
                next_page_url=None,
            )
        if page_url == blazer_ev_url:
            assert "filtered-blazer-ev" in html
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2025,
                        make="Chevrolet",
                        model="Blazer EV",
                        price=52995,
                        listing_url="https://www.classicchevysugarland.com/viewdetails/new/BLAZEREV1",
                    )
                ],
                next_page_url=None,
            )
        raise AssertionError(f"unexpected extraction {page_url}")

    detected_route = ProviderRoute(
        platform_id="dealer_inspire",
        confidence=0.95,
        extraction_mode="structured_json",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-vehicles", "used-vehicles"),
        inventory_url_hint="https://www.classicchevysugarland.com/new-vehicles/",
    )

    with (
        patch(
            "app.services.orchestrator.find_car_dealerships",
            new_callable=AsyncMock,
            return_value=dealers,
        ),
        patch("app.services.orchestrator.platform_store.get", return_value=None),
        patch("app.services.orchestrator.get_cached_inventory_listings", return_value=None),
        patch("app.services.orchestrator.set_cached_inventory_listings", return_value=None),
        patch(
            "app.services.orchestrator.fetch_page_html",
            new_callable=AsyncMock,
            side_effect=fake_fetch,
        ),
        patch("app.services.orchestrator.detect_or_lookup_provider", return_value=detected_route),
        patch("app.services.orchestrator.detect_platform_profile", return_value=None),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            side_effect=structured_result_for_url,
        ) as mock_extract,
        patch(
            "app.services.orchestrator.enrich_vehicle_listings_with_vin_data",
            new_callable=AsyncMock,
            side_effect=lambda rows: rows,
        ),
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "Sugar Land, TX",
            "Chevrolet",
            "Blazer,Blazer EV",
            vehicle_condition="new",
            max_dealerships=1,
            max_pages_per_dealer=2,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert [url for url, page_kind in fetch_calls if page_kind == "inventory"] == [blazer_url, blazer_ev_url]
    assert structured_calls == [blazer_url, blazer_ev_url]
    assert mock_extract.call_count == 2
    assert mock_llm.await_count == 0
    assert '"listings_found": 2' in tail
    assert '"pages_scraped": 2' in tail


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

    def structured_result_for_url(*, page_url: str, **_kwargs):
        if page_url.endswith("page=1"):
            return ExtractionResult(
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
            )
        if page_url.endswith("page=2"):
            return ExtractionResult(
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
            )
        if page_url.endswith("page=3"):
            return ExtractionResult(
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
            )
        if page_url.endswith("page=4"):
            return ExtractionResult(
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
            )
        return None

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
            side_effect=structured_result_for_url,
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
    assert mock_structured.call_count >= 4
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


@pytest.mark.asyncio
async def test_stream_search_retries_suspicious_dealer_dot_com_scoped_pagination_with_broad_srp() -> None:
    dealers = [
        DealershipFound(
            name="Suburban Volvo Cars",
            place_id="p1",
            address="1795 Maplelawn Rd",
            website="https://www.suburbanvolvocars.com",
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
        inventory_url_hint="https://www.suburbanvolvocars.com/new-inventory/index.htm",
    )

    async def fake_fetch(*_args, **_kwargs):
        return "<html><body>Inventory</body></html>", "direct"

    provider_results = [
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC90",
                    price=62000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc90-1",
                ),
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC60",
                    price=57000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc60-2",
                ),
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC40",
                    price=47000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc40-3",
                ),
            ],
            next_page_url=None,
            pagination=PaginationInfo(
                current_page=1,
                page_size=9,
                total_pages=1,
                total_results=1,
                source="inventory_api",
            ),
        ),
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC90",
                    price=62000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc90-1",
                ),
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC60",
                    price=57000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc60-2",
                ),
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC40",
                    price=47000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc40-3",
                ),
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="S90",
                    price=59000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/s90-4",
                ),
            ],
            next_page_url=None,
            pagination=PaginationInfo(
                current_page=1,
                page_size=18,
                total_pages=1,
                total_results=4,
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
            "app.services.orchestrator.expand_large_radius_search_locations",
            new_callable=AsyncMock,
            return_value=["48235"],
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
            "app.services.orchestrator.detect_platform_profile",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.resolve_inventory_url_for_provider",
            side_effect=[
                "https://www.suburbanvolvocars.com/new-inventory/index.htm?make=Volvo",
                "https://www.suburbanvolvocars.com/new-inventory/index.htm",
            ],
        ) as mock_resolve_inventory_url,
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
            "48235",
            "Volvo",
            "",
            vehicle_condition="new",
            radius_miles=250,
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_provider_extract.call_count == 2
    assert mock_resolve_inventory_url.call_count == 1
    assert mock_llm.await_count == 0
    assert "https://www.suburbanvolvocars.com/new-inventory/index.htm" in tail
    assert "https://www.suburbanvolvocars.com/vdp/s90-4" in tail
    assert '"listings_found": 4' in tail


@pytest.mark.asyncio
async def test_stream_search_retries_path_scoped_dealer_dot_com_pagination_with_canonical_srp() -> None:
    dealers = [
        DealershipFound(
            name="Suburban Volvo Cars",
            place_id="p1",
            address="1795 Maplelawn Rd",
            website="https://www.suburbanvolvocars.com",
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
        inventory_url_hint="https://www.suburbanvolvocars.com/new-inventory/index.htm",
    )

    async def fake_fetch(*_args, **_kwargs):
        return "<html><body>Inventory</body></html>", "direct"

    provider_results = [
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC90",
                    price=62000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc90-1",
                ),
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC60",
                    price=57000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc60-2",
                ),
            ],
            next_page_url=None,
            pagination=PaginationInfo(
                current_page=1,
                page_size=9,
                total_pages=1,
                total_results=1,
                source="inventory_api",
            ),
        ),
        ExtractionResult(
            vehicles=[
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC90",
                    price=62000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc90-1",
                ),
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="XC60",
                    price=57000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/xc60-2",
                ),
                VehicleListing(
                    year=2025,
                    make="Volvo",
                    model="S90",
                    price=59000,
                    listing_url="https://www.suburbanvolvocars.com/vdp/s90-3",
                ),
            ],
            next_page_url=None,
            pagination=PaginationInfo(
                current_page=1,
                page_size=18,
                total_pages=1,
                total_results=3,
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
            "app.services.orchestrator.expand_large_radius_search_locations",
            new_callable=AsyncMock,
            return_value=["48235"],
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
            "app.services.orchestrator.detect_platform_profile",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.resolve_inventory_url_for_provider",
            side_effect=[
                "https://www.suburbanvolvocars.com/new/volvo/",
                "https://www.suburbanvolvocars.com/new-inventory/index.htm",
            ],
        ) as mock_resolve_inventory_url,
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
            "48235",
            "Volvo",
            "",
            vehicle_condition="new",
            radius_miles=250,
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_provider_extract.call_count == 2
    assert mock_resolve_inventory_url.call_count == 2
    assert mock_llm.await_count == 0
    assert "https://www.suburbanvolvocars.com/new-inventory/index.htm" in tail
    assert "https://www.suburbanvolvocars.com/vdp/s90-3" in tail
    assert '"listings_found": 3' in tail


@pytest.mark.asyncio
async def test_stream_search_oneaudi_bypasses_raw_html_make_model_gate() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Audi Example",
            place_id="p1",
            address="100 Main St",
            website="https://www.audidealer.example/",
        )
    ]
    route = ProviderRoute(
        platform_id="oneaudi_falcon",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("en/inventory/new",),
        inventory_url_hint="https://www.audidealer.example/en/inventory/new/",
    )

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if url == "https://www.audidealer.example/" and page_kind == "homepage":
            return '<html><body><a href="/en/inventory/new/">Inventory</a></body></html>', "direct"
        if url == "https://www.audidealer.example/en/inventory/new/" and page_kind == "inventory":
            return '<html><body><div id="inventory-app"></div><script>window.__STATE__={"vehicles":[{"id":1}]}</script></body></html>', "zenrows_rendered"
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
            "app.services.orchestrator.detect_or_lookup_provider",
            return_value=route,
        ),
        patch(
            "app.services.orchestrator.resolve_inventory_url_for_provider",
            return_value="https://www.audidealer.example/en/inventory/new/",
        ),
        patch(
            "app.services.orchestrator.extract_with_provider",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
            return_value=ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2025,
                        make="Audi",
                        model="A5",
                        price=52995,
                        listing_url="https://www.audidealer.example/vdp/a5-1",
                    )
                ],
                next_page_url=None,
                pagination=None,
            ),
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "San Diego, CA",
            "Audi",
            "A5",
            vehicle_condition="new",
            max_dealerships=1,
            max_pages_per_dealer=1,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_llm.await_count == 1
    assert "https://www.audidealer.example/vdp/a5-1" in tail
    assert '"listings_found": 1' in tail


@pytest.mark.asyncio
async def test_stream_search_oneaudi_all_condition_fans_out_to_new_and_used() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Audi Example",
            place_id="p1",
            address="100 Main St",
            website="https://www.audidealer.example/",
        )
    ]
    route = ProviderRoute(
        platform_id="oneaudi_falcon",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("en/inventory/new", "en/inventory/used"),
        inventory_url_hint="https://www.audidealer.example/en/inventory/new/",
    )
    fetched_inventory_urls: list[str] = []

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if url == "https://www.audidealer.example/" and page_kind == "homepage":
            return '<html><body><a href="/en/inventory/new/">New</a><a href="/en/inventory/used/">Used</a></body></html>', "direct"
        if page_kind == "inventory":
            fetched_inventory_urls.append(url)
            return "<html><body><div>Inventory</div></body></html>", "zenrows_rendered"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    def fake_structured(*, page_url: str, **_kwargs):
        if page_url.endswith("/inventory/new/"):
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2025,
                        make="Audi",
                        model="Q5",
                        price=52995,
                        listing_url="https://www.audidealer.example/vdp/q5-new",
                    )
                ],
                next_page_url=None,
                pagination=None,
            )
        if page_url.endswith("/inventory/used/"):
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2023,
                        make="Audi",
                        model="Q7",
                        price=44995,
                        listing_url="https://www.audidealer.example/vdp/q7-used",
                    )
                ],
                next_page_url=None,
                pagination=None,
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
            return_value=route,
        ),
        patch(
            "app.services.orchestrator.resolve_inventory_url_for_provider",
            return_value="https://www.audidealer.example/en/inventory/new/",
        ),
        patch(
            "app.services.orchestrator.extract_with_provider",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            side_effect=fake_structured,
        ) as mock_structured,
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "San Diego, CA",
            "Audi",
            "Q5,Q7,Q3",
            vehicle_condition="all",
            max_dealerships=1,
            max_pages_per_dealer=10,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_structured.call_count == 2
    assert mock_llm.await_count == 0
    assert "https://www.audidealer.example/en/inventory/new/" in fetched_inventory_urls
    assert "https://www.audidealer.example/en/inventory/used/" in fetched_inventory_urls
    assert "https://www.audidealer.example/vdp/q5-new" in tail
    assert "https://www.audidealer.example/vdp/q7-used" in tail
    assert '"listings_found": 2' in tail


@pytest.mark.asyncio
async def test_stream_search_oneaudi_all_condition_keeps_localized_non_inventory_path() -> None:
    dealers = [
        DealershipFound(
            name="Audi Berlin Example",
            place_id="p1",
            address="100 Main St",
            website="https://www.audi-zentrum-berlin.example/de/",
        )
    ]
    route = ProviderRoute(
        platform_id="oneaudi_falcon",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory/new", "inventory/used"),
        inventory_url_hint="https://www.audi-zentrum-berlin.example/de/neuwagen/",
    )
    fetched_inventory_urls: list[str] = []

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if url == "https://www.audi-zentrum-berlin.example/de/" and page_kind == "homepage":
            return '<html><body><a href="/de/neuwagen/">Neuwagen</a></body></html>', "direct"
        if page_kind == "inventory":
            fetched_inventory_urls.append(url)
            return "<html><body><div>Inventory</div></body></html>", "direct"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    def fake_structured(*, page_url: str, **_kwargs):
        if page_url.endswith("/de/neuwagen/"):
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2025,
                        make="Audi",
                        model="A4",
                        price=45995,
                        listing_url="https://www.audi-zentrum-berlin.example/vdp/a4-new",
                    )
                ],
                next_page_url=None,
                pagination=None,
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
            return_value=route,
        ),
        patch(
            "app.services.orchestrator.resolve_inventory_url_for_provider",
            return_value="https://www.audi-zentrum-berlin.example/de/neuwagen/",
        ),
        patch(
            "app.services.orchestrator.extract_with_provider",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            side_effect=fake_structured,
        ),
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "Berlin, Germany",
            "Audi",
            "",
            vehicle_condition="all",
            market_region="eu",
            max_dealerships=1,
            max_pages_per_dealer=3,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_llm.await_count == 0
    assert "https://www.audi-zentrum-berlin.example/de/neuwagen/" in fetched_inventory_urls
    assert all("/inventory/" not in u for u in fetched_inventory_urls)
    assert "https://www.audi-zentrum-berlin.example/vdp/a4-new" in tail


@pytest.mark.asyncio
async def test_stream_search_oneaudi_all_condition_retries_used_when_new_fails_initially() -> None:
    from app.schemas import ExtractionResult, VehicleListing

    dealers = [
        DealershipFound(
            name="Audi Example",
            place_id="p1",
            address="100 Main St",
            website="https://www.audidealer.example/",
        )
    ]
    route = ProviderRoute(
        platform_id="oneaudi_falcon",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("en/inventory/new", "en/inventory/used"),
        inventory_url_hint="https://www.audidealer.example/en/inventory/new/",
    )
    fetched_inventory_urls: list[str] = []

    async def fake_fetch(url, page_kind, *_args, **_kwargs):
        if url == "https://www.audidealer.example/" and page_kind == "homepage":
            return '<html><body><a href="/en/inventory/new/">New</a><a href="/en/inventory/used/">Used</a></body></html>', "direct"
        if page_kind == "inventory":
            fetched_inventory_urls.append(url)
            if url.endswith("/inventory/new/"):
                raise RuntimeError("All fetch methods failed for https://www.audidealer.example/en/inventory/new/")
            return "<html><body><div>Inventory</div></body></html>", "zenrows_rendered"
        raise AssertionError(f"unexpected fetch {url} {page_kind}")

    def fake_structured(*, page_url: str, **_kwargs):
        if page_url.endswith("/inventory/used/"):
            return ExtractionResult(
                vehicles=[
                    VehicleListing(
                        year=2023,
                        make="Audi",
                        model="Q7",
                        price=44995,
                        listing_url="https://www.audidealer.example/vdp/q7-used",
                    )
                ],
                next_page_url=None,
                pagination=None,
            )
        return ExtractionResult(vehicles=[], next_page_url=None, pagination=None)

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
            return_value="https://www.audidealer.example/en/inventory/new/",
        ),
        patch(
            "app.services.orchestrator.extract_with_provider",
            return_value=None,
        ),
        patch(
            "app.services.orchestrator.try_extract_vehicles_without_llm",
            side_effect=fake_structured,
        ) as mock_structured,
        patch(
            "app.services.orchestrator.extract_vehicles_from_html",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        chunks: list[str] = []
        async for c in stream_search(
            "San Diego, CA",
            "Audi",
            "Q7,Q5,Q3",
            vehicle_condition="all",
            max_dealerships=1,
            max_pages_per_dealer=10,
        ):
            chunks.append(c)

    tail = "".join(chunks)
    assert mock_structured.call_count >= 1
    assert mock_llm.await_count == 0
    print("FETCHED:", fetched_inventory_urls); assert sorted(list(set(fetched_inventory_urls))) == [
        "https://www.audidealer.example/en/inventory/new/",
        "https://www.audidealer.example/en/inventory/used/",
    ]
    assert "https://www.audidealer.example/vdp/q7-used" in tail
    assert '"listings_found": 1' in tail
