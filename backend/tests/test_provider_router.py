from app.services.provider_router import ProviderRoute, resolve_inventory_url_for_provider


def test_resolve_inventory_url_for_provider_fixes_express_urls():
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=(),
        inventory_url_hint="https://express.suburbanvolvocars.com/inventory/"
    )
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.suburbanvolvocars.com/",
        route,
        fallback_url="https://express.suburbanvolvocars.com/inventory/",
        vehicle_condition="new"
    )
    assert url == "https://www.suburbanvolvocars.com/new-inventory/index.htm"

    # Test used
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.suburbanvolvocars.com/",
        route,
        fallback_url="https://express.suburbanvolvocars.com/inventory/",
        vehicle_condition="used"
    )
    assert url == "https://www.suburbanvolvocars.com/used-inventory/index.htm"

    # Test all
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.suburbanvolvocars.com/",
        route,
        fallback_url="https://express.suburbanvolvocars.com/inventory/",
        vehicle_condition="all"
    )
    assert url == "https://www.suburbanvolvocars.com/inventory/index.htm"


def test_resolve_inventory_url_for_provider_promotes_ddc_homepage_to_canonical_srp():
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=(),
        inventory_url_hint="https://www.suburbanvolvocars.com/",
    )
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.suburbanvolvocars.com/",
        route,
        fallback_url="https://www.suburbanvolvocars.com/",
        vehicle_condition="new",
    )
    assert url == "https://www.suburbanvolvocars.com/new-inventory/index.htm"


def test_resolve_inventory_url_for_provider_keeps_existing_ddc_srp():
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=(),
        inventory_url_hint="https://www.hodgessubaru.com/new-inventory/index.htm",
    )
    html = """
    <html><body>
      <a href="/featured-vehicles/new.htm">Featured New</a>
      <a href="/new-inventory/index.htm">View New Inventory</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.hodgessubaru.com/new-inventory/index.htm",
        route,
        fallback_url="https://www.hodgessubaru.com/new-inventory/index.htm",
        vehicle_condition="new",
    )
    assert url == "https://www.hodgessubaru.com/new-inventory/index.htm"

