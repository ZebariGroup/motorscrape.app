import json

from app.services.dealer_platforms import (
    detect_platform_profile,
    inventory_hints_for_platform,
    inventory_render_plan_for_url,
    playwright_inventory_instructions_for_url,
    zenrows_inventory_js_instructions_for_url,
)

_ZENROWS_JS_INSTRUCTIONS_WAIT_LIMIT_MS = 30_000


def test_oneaudi_js_instructions_match_audi_birmingham_inventory_url() -> None:
    instructions = zenrows_inventory_js_instructions_for_url(
        "https://www.audibirminghammi.com/en/inventory/new/"
    )
    assert instructions is not None
    steps = json.loads(instructions)

    total_wait_ms = sum(step.get("wait", 0) for step in steps if isinstance(step.get("wait"), int))
    assert total_wait_ms < _ZENROWS_JS_INSTRUCTIONS_WAIT_LIMIT_MS, (
        f"Total js_instructions wait {total_wait_ms}ms exceeds ZenRows 30s cap (REQS004)"
    )

    assert len(steps) >= 30
    assert len(instructions) < 2500
    assert steps[0]["evaluate"].startswith("window.__zrClickMore=()=>")
    assert sum(1 for step in steps if step.get("evaluate") == "window.__zrClickMore&&window.__zrClickMore()") >= 6


def test_oneaudi_js_instructions_do_not_match_non_audi_inventory_url() -> None:
    instructions = zenrows_inventory_js_instructions_for_url(
        "https://www.example-subaru.com/inventory/new/"
    )
    assert instructions is None


def test_inventory_render_plan_keeps_oneaudi_instructions_for_both_playwright_and_zenrows() -> None:
    plan = inventory_render_plan_for_url(
        "https://www.audibirminghammi.com/en/inventory/new/",
        platform_id="oneaudi_falcon",
    )
    assert plan.zenrows_js_instructions is not None
    assert plan.playwright_instructions is not None
    assert "window.__zrClickMore=()=>".replace(" ", "") in plan.playwright_instructions.replace(" ", "")
    assert "wait_for_selector" in plan.playwright_instructions


def test_detect_platform_profile_does_not_treat_generic_audi_de_links_as_oneaudi() -> None:
    html = """
    <html><body>
      <a href="https://www.audi.de/de/neuwagenboerse/">Neuwagensuche</a>
      <a href="https://www.audi.de/de/gebrauchtwagenboerse/">Gebrauchtwagensuche</a>
    </body></html>
    """
    profile = detect_platform_profile(
        html,
        page_url="https://www.audi-zentrum-berlin-charlottenburg.audi/de/",
    )
    assert profile is None


def test_playwright_inventory_instructions_cover_render_required_platforms() -> None:
    instructions = playwright_inventory_instructions_for_url(
        "https://dealer.example/searchnew.aspx",
        platform_id="dealer_on",
    )
    assert instructions is not None
    steps = json.loads(instructions)
    assert any(step.get("wait_for_selector") for step in steps)
    assert any(step.get("scroll") == "bottom" for step in steps)


def test_playwright_inventory_instructions_include_dealer_on_network_wait() -> None:
    instructions = playwright_inventory_instructions_for_url(
        "https://dealer.example/searchnew.aspx",
        platform_id="dealer_on",
    )
    assert instructions is not None
    steps = json.loads(instructions)
    assert any(step.get("wait_for_response_url") == "/api/vhcliaa/" for step in steps)
    assert any(step.get("wait_for_selector") == ".vehicle-card--mod,.vehicle-card" for step in steps)


def test_detect_platform_profile_matches_dealer_on_without_requiring_render() -> None:
    html = """
    <html><body>
      <script src="https://cdn.dealeron.com/js/dealeron.js"></script>
      <div class="vehicle-card--mod">Inventory</div>
      <div>vhcliaa</div>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://dealer.example/searchnew.aspx")
    assert profile is not None
    assert profile.platform_id == "dealer_on"
    assert profile.requires_render is False


def test_playwright_inventory_instructions_include_dealer_inspire_network_wait() -> None:
    instructions = playwright_inventory_instructions_for_url(
        "https://dealer.example/new-vehicles/",
        platform_id="dealer_inspire",
    )
    assert instructions is not None
    steps = json.loads(instructions)
    assert any(step.get("wait_for_response_url") == "/api/v1/facets/" for step in steps)
    assert any(step.get("wait_for_selector") == "[data-vehicle],.result-wrap.new-vehicle" for step in steps)


def test_playwright_inventory_instructions_include_team_velocity_selectors() -> None:
    instructions = playwright_inventory_instructions_for_url(
        "https://dealer.example/inventory/new",
        platform_id="team_velocity",
    )
    assert instructions is not None
    steps = json.loads(instructions)
    assert any(
        step.get("wait_for_selector")
        == ".v7list-results__item,.v7list-vehicle,.vehicle-heading__link,.vehicle-price--current"
        for step in steps
    )
    assert any(step.get("scroll") == "bottom" for step in steps)


def test_playwright_inventory_instructions_include_ford_family_selectors() -> None:
    instructions = playwright_inventory_instructions_for_url(
        "https://www.chulavistaford.com/inventory/new/ford/bronco",
        platform_id="ford_family_inventory",
    )
    assert instructions is not None
    steps = json.loads(instructions)
    assert any(step.get("wait_for_selector") == ".vehicle_results_label,.si-vehicle-box,.inventory_listing,[href*='/viewdetails/']" for step in steps)
    assert any(step.get("scroll") == "bottom" for step in steps)


def test_detect_platform_profile_matches_ford_family_on_group_host() -> None:
    html = """
    <html><body>
      <h1>New Ford Bronco for Sale</h1>
      <div class="vehicle_results_label">Results: 24 Vehicles</div>
      <div class="si-vehicle-box"></div>
      <a href="/inventory/new/ford/bronco/viewdetails/1">View Details</a>
      <script>var unlockCTADiscountData = {};</script>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.mossyauto.com/san-diego/bronco-search")
    assert profile is not None
    assert profile.platform_id == "ford_family_inventory"
    assert profile.requires_render is True


def test_detect_platform_profile_infiniti_host_not_honda_acura_when_shared_sonic_markers() -> None:
    """INFINITI retailers use the same Sonic DOM markers as Honda OEM; hostname must disambiguate."""
    html = """
    <html><body>
      <p>Welcome to LaFontaine INFINITI</p>
      <div class="si-vehicle-box"></div>
      <div class="inventory_listing"></div>
      <a href="/viewdetails/new/abc/2025-infiniti-q50">Details</a>
      <script>var unlockCTADiscountData = {};</script>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.lafontaineinfinititroy.com/")
    assert profile is not None
    assert profile.platform_id == "nissan_infiniti_inventory"


def test_detect_platform_profile_infiniti_host_not_gm_family_when_footer_mentions_chevy() -> None:
    html = """
    <html><body>
      <title>Infiniti of Windsor</title>
      <div class="si-vehicle-box"></div>
      <footer>Also shop Chevrolet and GMC trucks at our group site</footer>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.infinitiofwindsor.com/")
    assert profile is not None
    assert profile.platform_id == "nissan_infiniti_inventory"


def test_detect_platform_profile_nissan_host_not_ford_family_when_ford_is_substring() -> None:
    """Marketing copy like 'affordable' must not enable Ford OEM detection on Nissan dealers."""
    html = """
    <html><body>
      <p>Shop affordable financing on every new Nissan Altima.</p>
      <div class="si-vehicle-box"></div>
      <div class="inventory_listing">Inventory</div>
      <a href="/inventory/new/viewdetails/new/abc123/2025-nissan-altima">View Details</a>
      <script>var unlockCTADiscountData = {};</script>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.jeffreynissan.com/")
    assert profile is not None
    assert profile.platform_id == "nissan_infiniti_inventory"


def test_detect_platform_profile_alfa_host_not_toyota_lexus_when_footer_mentions_toyota_lexus() -> None:
    """DDC Alfa hosts mention Toyota/Lexus in copy; Toyota OEM routing must not apply."""
    html = """
    <html><body>
      <link href="https://pictures.dealer.com/x" />
      <script>window.DDC.WidgetData["x"]={}; ddc.widgetdata</script>
      <div class="si-vehicle-box"></div>
      <div class="inventory_listing"></div>
      <a href="/viewdetails/new/abc/2025-alfa-romeo-giulia">Details</a>
      <script>var unlockCTADiscountData = {};</script>
      <footer>Compare Toyota and Lexus — we have Alfa Romeo inventory.</footer>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.alfaromeoofbirmingham.com/")
    assert profile is not None
    assert profile.platform_id == "dealer_dot_com"


def test_inventory_render_plan_uses_sonic_scroll_for_nissan_infiniti_inventory() -> None:
    plan = inventory_render_plan_for_url(
        "https://www.jeffreynissan.com/inventory/new",
        platform_id="nissan_infiniti_inventory",
    )
    assert plan.zenrows_js_instructions is not None
    assert plan.playwright_instructions is not None


def test_detect_platform_profile_matches_d2c_media_homepage_markers() -> None:
    html = """
    <html><body>
      <a href="/new/inventory/search.html">New Inventory (149)</a>
      <a href="/used/search.html">Pre-Owned Inventory (33)</a>
      <div>##LINKRULES##</div>
      <footer>Member of the AutoAubaine network - D2C Media</footer>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.erinmillsacura.ca/")
    assert profile is not None
    assert profile.platform_id == "d2c_media"
    assert profile.extraction_mode == "structured_html"


def test_detect_platform_profile_breaks_dealer_inspire_ties_toward_team_velocity() -> None:
    html = """
    <html><body>
      <script src="https://cdn.example.com/dealerinspire/runtime.js"></script>
      <script id="__NEXT_DATA__" type="application/json">{}</script>
      <footer>Website by Team Velocity - https://www.teamvelocitymarketing.com/</footer>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.jeffreyacura.com/")
    assert profile is not None
    assert profile.platform_id == "team_velocity"
    assert profile.requires_render is True


def test_team_velocity_inventory_hints_cover_inventory_new_paths() -> None:
    hints = inventory_hints_for_platform("team_velocity")
    assert "inventory/new" in hints
    assert "inventory/used" in hints


def test_detect_platform_profile_matches_dealer_spike_homepage_markers() -> None:
    html = """
    <html><body>
      <a href="/default.asp?page=xAllInventory">Shop Inventory</a>
      <footer>Dealer Spike Powersports</footer>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.indianoftoledo.com/")
    assert profile is not None
    assert profile.platform_id == "dealer_spike"
    assert "default.asp?page=xallinventory" in inventory_hints_for_platform("dealer_spike")


def test_detect_platform_profile_prefers_dealer_spike_over_generic_dealer_dot_com_marker() -> None:
    html = """
    <html><body>
      <script>var vendor = "dealer.com";</script>
      <footer>Dealer Spike Powersports</footer>
      <a href="/search/inventory">Search Inventory</a>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.southgatehondapowersports.com/")
    assert profile is not None
    assert profile.platform_id == "dealer_spike"


def test_detect_platform_profile_prefers_dealer_dot_com_over_gm_family_when_ddc_widget_present() -> None:
    """GM/Buick dealers on Dealer.com embed brand tokens + inventory_listing but use DDC SRPs, not /inventory/new/..."""
    html = """
    <html><body>
      <script>window.DDC=window.DDC||{};window.DDC.WidgetData=window.DDC.WidgetData||{};</script>
      <script>DealerDotCom.config = true;</script>
      <span>gmc</span><span>buick</span><span>cadillac</span>
      <div class="inventory_listing"></div>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.foxbuickgmc.com/")
    assert profile is not None
    assert profile.platform_id == "dealer_dot_com"


def test_detect_platform_profile_matches_marinemax_markers() -> None:
    html = """
    <html><body>
      <div id="find-a-boat-v2"></div>
      <script id="boat-card-template" type="text/x-template"></script>
      <script>window.algoliaApplicationID = 'MES124X9KA'; window.algoliaAPIKey = 'abc';</script>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.marinemax.com/boats-for-sale")
    assert profile is not None
    assert profile.platform_id == "marinemax"
    assert profile.requires_render is True


def test_detect_platform_profile_matches_revver_digital_marine_markers() -> None:
    html = """
    <html><body>
      <input type="hidden" name="boat_details" value="{}" />
      <a class="sbNext" href="?sbpage=2">Next Page</a>
      <footer>Powered by Revver Digital</footer>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.onewaterinventory.com/search/")
    assert profile is not None
    assert profile.platform_id == "revver_digital_marine"
    assert "search" in inventory_hints_for_platform("revver_digital_marine")


def test_detect_platform_profile_matches_basspro_markers() -> None:
    html = """
    <html><body>
      <div class="grid-x" data-modelPage="/boats-for-sale/boatmodel/">
        <div class="cell inventory-card">
          <p class="mname">2026 Nitro ZV19 Sport Pro</p>
        </div>
      </div>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.bassproboatingcenters.com/boats-for-sale.html")
    assert profile is not None
    assert profile.platform_id == "basspro_boating_center"
    assert "boats-for-sale.html" in inventory_hints_for_platform("basspro_boating_center")


def test_detect_platform_profile_matches_harley_digital_showroom() -> None:
    html = """
    <html><body>
      <div class="page_infoFilters"></div>
      <p>Harley-Davidson® motorcycles</p>
    </body></html>
    """
    profile = detect_platform_profile(html, page_url="https://www.motownharley.com/new-inventory")
    assert profile is not None
    assert profile.platform_id == "harley_digital_showroom"
    assert profile.requires_render is True
    assert "new-inventory" in inventory_hints_for_platform("harley_digital_showroom")
