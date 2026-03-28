from urllib.parse import parse_qs, urlsplit

from app.services.provider_router import ProviderRoute, resolve_inventory_url_for_provider


def test_resolve_inventory_url_for_provider_prefers_team_velocity_all_inventory_for_unfiltered_search() -> None:
    route = ProviderRoute(
        platform_id="team_velocity",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory",),
        inventory_url_hint="https://www.examplepowersports.com/inventory/v1/",
    )
    html = """
    <html><body>
      <a href="/inventory/v1/">Inventory</a>
      <a href="/--inventory">All Inventory</a>
      <a href="/--inventory?condition=new">New Inventory</a>
      <a href="/--inventory?condition=pre-owned">Pre-Owned Inventory</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.examplepowersports.com/",
        route,
        fallback_url="https://www.examplepowersports.com/inventory/v1/",
        vehicle_condition="all",
    )
    assert url == "https://www.examplepowersports.com/--inventory"


def test_resolve_inventory_url_for_provider_prefers_dealer_spike_inventory_over_model_list() -> None:
    route = ProviderRoute(
        platform_id="dealer_spike",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=(
            "default.asp?page=xallinventory",
            "inventory/new-inventory-in-stock",
            "inventory/used-inventory",
        ),
        inventory_url_hint=None,
    )
    html = """
    <html><body>
      <a href="/Brands/Manufacturer-Models/Model-List/Triumph">Triumph Models</a>
      <a href="/Inventory/New-Inventory-In-Stock">New Inventory</a>
      <a href="/Inventory/Used-Inventory">Used Inventory</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.werkspowersports.com/",
        route,
        fallback_url="https://www.werkspowersports.com/",
        make="Triumph",
        vehicle_condition="new",
    )
    assert url == "https://www.werkspowersports.com/Inventory/New-Inventory-In-Stock"


def test_resolve_inventory_url_for_provider_drops_fragment_filters_from_dealer_spike_inventory() -> None:
    route = ProviderRoute(
        platform_id="dealer_spike",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("default.asp?page=xallinventory",),
        inventory_url_hint=None,
    )
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.indianoftoledo.com/",
        route,
        fallback_url="https://www.indianoftoledo.com/default.asp?page=xallinventory#page=xallinventory&vc=Cruiser",
        make="Indian Motorcycle",
        vehicle_condition="all",
    )
    assert url == "https://www.indianoftoledo.com/default.asp?page=xallinventory"


def test_resolve_inventory_url_for_provider_avoids_scoped_team_velocity_used_links_when_filters_empty() -> None:
    route = ProviderRoute(
        platform_id="team_velocity",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory",),
        inventory_url_hint="https://www.examplepowersports.com/inventory/v1/",
    )
    html = """
    <html><body>
      <a href="/--inventory?condition=pre-owned">Pre-Owned Inventory</a>
      <a href="/--inventory?condition=pre-owned&amp;make=harley-davidson&amp;pg=1">Harley Used Inventory</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.examplepowersports.com/",
        route,
        fallback_url="https://www.examplepowersports.com/inventory/v1/",
        vehicle_condition="used",
    )
    assert url == "https://www.examplepowersports.com/--inventory?condition=pre-owned"


def test_resolve_inventory_url_for_provider_promotes_team_velocity_inventory_v1_to_canonical_all() -> None:
    route = ProviderRoute(
        platform_id="team_velocity",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory",),
        inventory_url_hint=None,
    )
    html = """
    <html><body>
      <a href="/inventory/v1/">Inventory</a>
      <a href="/--inventory?condition=new">New Inventory</a>
      <a href="/--inventory?condition=pre-owned">Pre-Owned Inventory</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.examplepowersports.com/",
        route,
        fallback_url="https://www.examplepowersports.com/inventory/v1/",
        vehicle_condition="all",
    )
    assert url == "https://www.examplepowersports.com/--inventory"


def test_resolve_inventory_url_for_provider_avoids_wrong_brand_generic_collection() -> None:
    html = """
    <html><body>
      <a href="/michigan-all-boat-inventory/">All Boat Inventory</a>
      <a href="/michigan-all-prestige-yachts-inventory-for-sale/">Prestige Yachts for Sale</a>
      <a href="/used-boats-for-sale/bayliner/2024-bayliner-vr6-bowrider-ob-123/">2024 Bayliner VR6 Bowrider OB</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.examplemarine.com/",
        None,
        fallback_url="https://www.examplemarine.com/michigan-all-boat-inventory/",
        make="Bayliner",
        vehicle_condition="all",
    )
    assert url == "https://www.examplemarine.com/michigan-all-boat-inventory/"


def test_resolve_inventory_url_for_provider_prefers_requested_brand_collection() -> None:
    html = """
    <html><body>
      <a href="/michigan-all-boat-inventory/">All Boat Inventory</a>
      <a href="/michigan-all-bayliner-boat-inventory/">Bayliner Boats for Sale</a>
      <a href="/michigan-all-prestige-yachts-inventory-for-sale/">Prestige Yachts for Sale</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.examplemarine.com/",
        None,
        fallback_url="https://www.examplemarine.com/michigan-all-boat-inventory/",
        make="Bayliner",
        vehicle_condition="all",
    )
    assert url == "https://www.examplemarine.com/michigan-all-bayliner-boat-inventory/"


def test_resolve_inventory_url_for_provider_generic_make_search_keeps_fallback_when_best_url_has_other_brand() -> None:
    html = """
    <html><body>
      <a href="/michigan-all-boat-inventory/">All Boat Inventory</a>
      <a href="/michigan-new-crest-pontoon-boats-for-sale/">Crest Pontoon Boats for Sale</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.examplemarine.com/",
        None,
        fallback_url="https://www.examplemarine.com/michigan-all-boat-inventory/",
        make="Bayliner",
        vehicle_condition="all",
    )
    assert url == "https://www.examplemarine.com/michigan-all-boat-inventory/"


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
    assert url == "https://www.suburbanvolvocars.com/all-inventory/index.htm"


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


def test_resolve_inventory_url_for_provider_promotes_ddc_all_condition_to_all_inventory() -> None:
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=(),
        inventory_url_hint="https://www.hodgessubaru.com/",
    )
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.hodgessubaru.com/",
        route,
        fallback_url="https://www.hodgessubaru.com/",
        vehicle_condition="all",
    )
    assert url == "https://www.hodgessubaru.com/all-inventory/index.htm"


def test_resolve_inventory_url_for_provider_prefers_make_specific_ddc_srp_when_model_empty():
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-inventory",),
        inventory_url_hint="https://www.suburbanbuickgmcoftroy.com/new-inventory/index.htm",
    )
    html = """
    <html><body>
      <a href="/new-inventory/index.htm">New Inventory</a>
      <a href="/new-gmc/vehicles-troy-mi.htm">Search New GMC</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.suburbanbuickgmcoftroy.com/new-inventory/index.htm?search=&model=Acadia&gvBodyStyle=SUV",
        route,
        fallback_url="https://www.suburbanbuickgmcoftroy.com/new-inventory/index.htm",
        make="GMC",
        model="",
        vehicle_condition="new",
    )
    assert url == "https://www.suburbanbuickgmcoftroy.com/new-gmc/vehicles-troy-mi.htm"


def test_resolve_inventory_url_for_provider_avoids_model_landing_for_make_only_ddc_search():
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-inventory",),
        inventory_url_hint="https://www.foxbuickgmc.com/new-inventory/index.htm",
    )
    html = """
    <html><body>
      <a href="/new-inventory/gmc-yukon.htm">GMC Yukon</a>
      <a href="/new-inventory/index.htm">New Inventory</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.foxbuickgmc.com/",
        route,
        fallback_url="https://www.foxbuickgmc.com/new-inventory/index.htm",
        make="GMC",
        model="",
        vehicle_condition="new",
    )
    assert url == "https://www.foxbuickgmc.com/new-inventory/index.htm?make=GMC"


def test_resolve_inventory_url_for_provider_keeps_generic_ddc_srp_when_anchor_text_is_make_scoped():
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-inventory",),
        inventory_url_hint="https://www.alfaromeoofbirmingham.com/new-inventory/index.htm",
    )
    html = """
    <html><body>
      <a href="/new-inventory/index.htm">New Alfa Romeo Inventory</a>
      <a href="/new-fiat/index.htm">New FIAT Inventory</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.alfaromeoofbirmingham.com/",
        route,
        fallback_url="https://www.alfaromeoofbirmingham.com/new-inventory/index.htm",
        make="Alfa Romeo",
        model="",
        vehicle_condition="new",
    )
    assert url == "https://www.alfaromeoofbirmingham.com/new-inventory/index.htm"


def test_resolve_inventory_url_for_provider_keeps_generic_ddc_srp_for_single_brand_bmw_host() -> None:
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-inventory",),
        inventory_url_hint="https://www.bmwofannarbor.com/new-inventory/index.htm",
    )
    html = """
    <html><body>
      <a href="/new-inventory/index.htm">New Inventory</a>
      <a href="/featured-vehicles/new.htm">Featured New</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.bmwofannarbor.com/",
        route,
        fallback_url="https://www.bmwofannarbor.com/new-inventory/index.htm",
        make="BMW",
        model="",
        vehicle_condition="new",
    )
    assert url == "https://www.bmwofannarbor.com/new-inventory/index.htm"


def test_resolve_inventory_url_for_provider_avoids_single_brand_bmw_marketing_landings() -> None:
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-inventory",),
        inventory_url_hint="https://www.bmwofrochesterhills.com/new-inventory/index.htm",
    )
    html = """
    <html><body>
      <a href="/bmw-electric-vehicles.htm">BMW Electric Vehicles</a>
      <a href="/bmw-plug-in-hybrid-vehicles.htm">BMW Plug-In Hybrid Vehicles</a>
      <a href="/new-inventory/index.htm">New Inventory</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.bmwofrochesterhills.com/",
        route,
        fallback_url="https://www.bmwofrochesterhills.com/new-inventory/index.htm",
        make="BMW",
        model="",
        vehicle_condition="new",
    )
    assert url == "https://www.bmwofrochesterhills.com/new-inventory/index.htm"


def test_resolve_inventory_url_for_provider_keeps_gm_family_all_inventory_index() -> None:
    route = ProviderRoute(
        platform_id="gm_family_inventory",
        confidence=1.0,
        extraction_mode="structured_html",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory/new", "inventory/used", "new-", "used-", "certified", "pre-owned"),
        inventory_url_hint=None,
    )
    html = """
    <html><body>
      <a href="/all-inventory/index.htm">All Inventory</a>
      <a href="/new-inventory/index.htm">New Inventory</a>
      <a href="/certified-inventory/index.htm">Certified</a>
      <a href="/new-inventory/cadillac-escalade-novi-mi.htm">Escalade</a>
    </body></html>
    """
    url = resolve_inventory_url_for_provider(
        html,
        "https://www.cadillacofnovi.com/",
        route,
        fallback_url="https://www.cadillacofnovi.com/certified-inventory/index.htm",
        make="Cadillac",
        model="",
        vehicle_condition="all",
    )
    assert url == "https://www.cadillacofnovi.com/all-inventory/index.htm"


def test_resolve_inventory_url_for_provider_canonicalizes_stale_dealer_on_inventory_hint() -> None:
    route = ProviderRoute(
        platform_id="dealer_on",
        confidence=1.0,
        extraction_mode="rendered_dom",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("searchnew.aspx", "searchused.aspx"),
        inventory_url_hint="https://express.bmwgrandblanc.com/inventory",
    )
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.bmwgrandblanc.com/",
        route,
        fallback_url="https://express.bmwgrandblanc.com/inventory",
        make="BMW",
        model="",
        vehicle_condition="new",
    )
    assert url == "https://www.bmwgrandblanc.com/searchnew.aspx?Make=BMW"


def test_resolve_inventory_url_for_provider_canonicalizes_dealer_inspire_filtered_new_hint() -> None:
    route = ProviderRoute(
        platform_id="dealer_inspire",
        confidence=1.0,
        extraction_mode="structured_json",
        requires_render=True,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new-vehicles", "used-vehicles"),
        inventory_url_hint=(
            "https://www.northlandchryslerjeepdodge.com/new-vehicles/"
            "?_dFR%5Btype%5D%5B0%5D=New&_dFR%5Bmake%5D%5B0%5D=Jeep"
        ),
    )
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.northlandchryslerjeepdodge.com/",
        route,
        fallback_url=route.inventory_url_hint,
        make="Jeep",
        model="",
        vehicle_condition="new",
    )
    assert url == "https://www.northlandchryslerjeepdodge.com/new-vehicles/"


def test_resolve_inventory_url_for_provider_handles_multi_model_filter_as_make_only_for_ddc() -> None:
    route = ProviderRoute(
        platform_id="dealer_dot_com",
        confidence=1.0,
        extraction_mode="hybrid",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("inventory",),
        inventory_url_hint="https://www.patmillikenford.com/inventory/",
    )
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.patmillikenford.com/inventory/",
        route,
        fallback_url="https://www.patmillikenford.com/inventory/",
        make="Ford",
        model="F-150,F-150 Lightning",
        vehicle_condition="all",
    )
    parsed = urlsplit(url)
    assert parsed.path.endswith("/all-inventory/index.htm")
    query = parse_qs(parsed.query)
    assert query.get("make") == ["Ford"]
    assert "model" not in query


def test_resolve_inventory_url_for_provider_handles_multi_model_filter_as_make_only_for_dealer_on() -> None:
    route = ProviderRoute(
        platform_id="dealer_on",
        confidence=1.0,
        extraction_mode="rendered_dom",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("searchnew.aspx", "searchused.aspx"),
        inventory_url_hint="https://www.patmillikenford.com/inventory/",
    )
    url = resolve_inventory_url_for_provider(
        "<html></html>",
        "https://www.patmillikenford.com/inventory/",
        route,
        fallback_url="https://www.patmillikenford.com/inventory/",
        make="Ford",
        model="F-150,F-150 Lightning",
        vehicle_condition="all",
    )
    parsed = urlsplit(url)
    assert parsed.path.endswith("/searchall.aspx")
    query = parse_qs(parsed.query)
    assert query.get("Make") == ["Ford"]
    assert "Model" not in query
    assert "ModelAndTrim" not in query


def test_resolve_inventory_url_for_provider_prefers_d2c_search_pages() -> None:
    route = ProviderRoute(
        platform_id="d2c_media",
        confidence=1.0,
        extraction_mode="structured_html",
        requires_render=False,
        detection_source="test",
        cache_status="detected",
        inventory_path_hints=("new/inventory/search.html", "used/search.html"),
        inventory_url_hint="https://www.erinmillsacura.ca/new/inventory/search.html",
    )
    html = """
    <html><body>
      <a href="/new/new.html">New Vehicles</a>
      <a href="/new/inventory/search.html">New Inventory (149)</a>
      <a href="/new/2026-Acura-MDX.html">2026 Acura MDX</a>
      <a href="/used/search.html">Pre-Owned Inventory (33)</a>
      <a href="/used/2024-Acura-RDX.html">2024 Acura RDX</a>
    </body></html>
    """

    new_url = resolve_inventory_url_for_provider(
        html,
        "https://www.erinmillsacura.ca/",
        route,
        fallback_url="https://www.erinmillsacura.ca/",
        vehicle_condition="new",
    )
    used_url = resolve_inventory_url_for_provider(
        html,
        "https://www.erinmillsacura.ca/",
        route,
        fallback_url="https://www.erinmillsacura.ca/",
        vehicle_condition="used",
    )

    assert new_url == "https://www.erinmillsacura.ca/new/inventory/search.html"
    assert used_url == "https://www.erinmillsacura.ca/used/search.html"

