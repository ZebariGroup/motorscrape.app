from app.services.provider_router import resolve_inventory_url_for_provider, ProviderRoute

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

