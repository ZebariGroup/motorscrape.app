"""Platform detection, provider registry, and JSON-LD helpers for dealer sites."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_TEAM_VELOCITY_STRONG_MARKERS: tuple[str, ...] = (
    "teamvelocitymarketing.com",
    "teamvelocity",
    "team velocity",
)
_DEALER_INSPIRE_STRONG_MARKERS: tuple[str, ...] = (
    "dealerinspire.com",
    "dealer-inspire",
    "dealerinspire",
    "wp-content/themes/dealerinspire",
)
_DEALER_SPIKE_STRONG_MARKERS: tuple[str, ...] = (
    "dealer spike",
    "dealerspike",
    "endeavorsuite",
    "/search/inventory",
    "--xallinventory",
)
_FORD_FAMILY_STRONG_MARKERS: tuple[str, ...] = (
    "ford",
    "lincoln",
    "vehicle_results_label",
    "si-vehicle-box",
    "unlockctadiscountdata",
    "/viewdetails/",
    "inventory_listing",
)
# Sonic / SecureOfferSites-style stack shared by Ford, Nissan, INFINITI, etc. — do not use "ford" substring
# in HTML alone (e.g. "affordable") to enable the Ford OEM profile.
_NISSAN_INFINITI_SONIC_MARKERS: tuple[str, ...] = (
    "si-vehicle-box",
    "unlockctadiscountdata",
    "/viewdetails/",
    "inventory_listing",
)
# Embedded Dealer.com widget bootstrap — definitive fingerprint for DDC inventory URLs
# (/new-inventory/index.htm, etc.), even when GM/Ford/Honda brand tokens outscore raw marker counts.
_DDC_DOMINANT_MARKERS: frozenset[str] = frozenset({"ddc.widgetdata", "inventoryapiurl"})
# OEM "family" stacks that build /inventory/new/{make}/{model} paths; those 404 on pure DDC sites.
_PLATFORMS_SUBSUMED_BY_DDC_WHEN_DOMINANT: frozenset[str] = frozenset(
    {
        "ford_family_inventory",
        "gm_family_inventory",
        "honda_acura_inventory",
        "nissan_infiniti_inventory",
        "kia_inventory",
    }
)

_FORD_LINCOLN_BODY_RE = re.compile(r"(?<![a-z0-9])ford(?![a-z0-9])", re.I)
_LINCOLN_BODY_RE = re.compile(r"(?<![a-z0-9])lincoln(?![a-z0-9])", re.I)


@dataclass(frozen=True, slots=True)
class PlatformProfile:
    platform_id: str
    confidence: float
    extraction_mode: str
    requires_render: bool
    inventory_path_hints: tuple[str, ...]
    detection_source: str


@dataclass(frozen=True, slots=True)
class PlatformDefinition:
    platform_id: str
    markers: tuple[str, ...]
    inventory_path_hints: tuple[str, ...]
    extraction_mode: str
    requires_render: bool = False


@dataclass(frozen=True, slots=True)
class InventoryRenderPlan:
    playwright_instructions: str | None = None
    zenrows_js_instructions: str | None = None


_ONEAUDI_FALCON_DEFINE_LOAD_MORE_HELPER_JS = (
    "window.__zrClickMore=()=>{"
    "for(const e of document.querySelectorAll('button,a,[role=\"button\"]')){"
    "if(e.disabled||e.hasAttribute('disabled'))continue;"
    "const t=(e.innerText||e.textContent||e.getAttribute('aria-label')||'').toLowerCase();"
    "if(/(load|show|view|see) more/.test(t)){e.click();break}"
    "}"
    "}"
)
_ONEAUDI_FALCON_SCROLL_BOTTOM_JS = "window.scrollTo(0,document.body.scrollHeight)"
_ONEAUDI_FALCON_CLICK_LOAD_MORE_JS = "window.__zrClickMore&&window.__zrClickMore()"
_PLAYWRIGHT_INVENTORY_READY_SELECTOR = ",".join(
    (
        "[data-vehicle]",
        ".result-wrap.new-vehicle",
        ".carbox",
        ".vehicle-card",
        ".vehicle-card--mod",
        ".inventory-card",
        ".cc-vehicle",
        ".sbiGrid .item",
        ".si-vehicle-box",
        ".v7list-results__item",
        ".v7list-vehicle",
        ".vehicle-heading__link",
        "[data-test-section='vehicleCard']",
        ".mmx-boat-card[href]",
        ".mmx-boat-card .title",
        "a[href*='/boats-for-sale/details/']",
        "[class*='boat-card'] a[href]",
        "li[data-component='result-tile']",
        "[data-component='result-tile']",
    )
)


def _compact_instruction_payload(steps: list[dict[str, Any]]) -> str:
    return json.dumps(steps, separators=(",", ":"))


def _oneaudi_falcon_inventory_js_instructions(rounds: int = 8) -> str:
    # Define the helper once so the ZenRows query string stays comfortably below common URL limits.
    # rounds=8 keeps total js_instructions wait time at 26s, safely under ZenRows' 30s hard cap (REQS004).
    steps: list[dict[str, int | str]] = [
        {"evaluate": _ONEAUDI_FALCON_DEFINE_LOAD_MORE_HELPER_JS},
        {"wait": 2000},
    ]
    for _ in range(max(1, rounds)):
        steps.extend(
            [
                {"evaluate": _ONEAUDI_FALCON_SCROLL_BOTTOM_JS},
                {"wait": 1200},
                {"evaluate": _ONEAUDI_FALCON_CLICK_LOAD_MORE_JS},
                {"wait": 1800},
            ]
        )
    return _compact_instruction_payload(steps)


def _inventory_ready_playwright_instructions(scroll_rounds: int = 2) -> str:
    steps: list[dict[str, Any]] = [
        {"wait_for_selector": _PLAYWRIGHT_INVENTORY_READY_SELECTOR, "timeout_ms": 4500},
    ]
    for _ in range(max(1, scroll_rounds)):
        steps.extend(
            [
                {"scroll": "bottom"},
                {"wait": 900},
                {"wait_for_selector": _PLAYWRIGHT_INVENTORY_READY_SELECTOR, "timeout_ms": 2500},
            ]
        )
    return _compact_instruction_payload(steps)


def _dealer_on_playwright_instructions(scroll_rounds: int = 2) -> str:
    steps: list[dict[str, Any]] = [
        {"wait_for_response_url": "/api/vhcliaa/", "timeout_ms": 2500},
        {"wait_for_selector": ".vehicle-card--mod,.vehicle-card", "timeout_ms": 5000},
    ]
    for _ in range(max(1, scroll_rounds)):
        steps.extend(
            [
                {"scroll": "bottom"},
                {"wait": 900},
                {"wait_for_selector": ".vehicle-card--mod,.vehicle-card", "timeout_ms": 2500},
            ]
        )
    return _compact_instruction_payload(steps)


def _dealer_inspire_playwright_instructions(scroll_rounds: int = 3) -> str:
    steps: list[dict[str, Any]] = [
        {"wait_for_response_url": "/api/v1/facets/", "timeout_ms": 3000},
        {"wait_for_selector": "[data-vehicle],.result-wrap.new-vehicle", "timeout_ms": 5000},
    ]
    for _ in range(max(1, scroll_rounds)):
        steps.extend(
            [
                {"scroll": "bottom"},
                {"wait": 900},
                {"wait_for_selector": "[data-vehicle],.result-wrap.new-vehicle", "timeout_ms": 2500},
            ]
        )
    return _compact_instruction_payload(steps)


def _ford_family_playwright_instructions(scroll_rounds: int = 4) -> str:
    ford_selector = ".vehicle_results_label,.si-vehicle-box,.inventory_listing,[href*='/viewdetails/']"
    steps: list[dict[str, Any]] = [
        {"wait_for_selector": ford_selector, "timeout_ms": 6000},
    ]
    for _ in range(max(1, scroll_rounds)):
        steps.extend(
            [
                {"scroll": "bottom"},
                {"wait": 1200},
                {"wait_for_selector": ford_selector, "timeout_ms": 3000},
            ]
        )
    return _compact_instruction_payload(steps)


def _team_velocity_playwright_instructions(scroll_rounds: int = 3) -> str:
    tv_selector = ".v7list-results__item,.v7list-vehicle,.vehicle-heading__link,.vehicle-price--current"
    steps: list[dict[str, Any]] = [
        {"wait_for_selector": tv_selector, "timeout_ms": 7000},
    ]
    for _ in range(max(1, scroll_rounds)):
        steps.extend(
            [
                {"scroll": "bottom"},
                {"wait": 1000},
                {"wait_for_selector": tv_selector, "timeout_ms": 3000},
            ]
        )
    return _compact_instruction_payload(steps)


def _oneaudi_falcon_playwright_instructions(rounds: int = 8) -> str:
    steps = json.loads(_oneaudi_falcon_inventory_js_instructions(rounds=rounds))
    if not isinstance(steps, list):
        steps = []
    steps.append({"wait_for_selector": _PLAYWRIGHT_INVENTORY_READY_SELECTOR, "timeout_ms": 4000})
    return _compact_instruction_payload(steps)


# ZenRows `js_instructions` for infinite-scroll SRPs (e.g. OneAudi Falcon) — host-based, not hard-coded in scraper.
_ONEAUDI_FALCON_INVENTORY_JS_INSTRUCTIONS = _oneaudi_falcon_inventory_js_instructions()
_ONEAUDI_FALCON_PLAYWRIGHT_INSTRUCTIONS = _oneaudi_falcon_playwright_instructions()
_DEALER_ON_PLAYWRIGHT_INSTRUCTIONS = _dealer_on_playwright_instructions()
_DEALER_INSPIRE_PLAYWRIGHT_INSTRUCTIONS = _dealer_inspire_playwright_instructions()
_FORD_FAMILY_PLAYWRIGHT_INSTRUCTIONS = _ford_family_playwright_instructions()
_TEAM_VELOCITY_PLAYWRIGHT_INSTRUCTIONS = _team_velocity_playwright_instructions()
_RENDER_REQUIRED_PLAYWRIGHT_INSTRUCTIONS = _inventory_ready_playwright_instructions()

_ONEAUDI_FALCON_INVENTORY_HOST_FRAGMENTS: frozenset[str] = frozenset(
    {
        "audi.com",
        "audinovi.com",
        "audibirminghammi.com",
        "audirochesterhills.com",
        "audiannarbor.com",
        "audilansing.com",
        "audiwindsor.com",
    }
)


def _looks_like_oneaudi_falcon_inventory_url(url: str) -> bool:
    if not url:
        return False
    try:
        parts = urlsplit(url)
    except Exception:
        return False
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    path = parts.path.lower().rstrip("/")
    if any(fragment in host for fragment in _ONEAUDI_FALCON_INVENTORY_HOST_FRAGMENTS):
        return True
    if "audi" not in host:
        return False
    return path.endswith("/inventory/new") or path.endswith("/inventory/used") or path.endswith("/en/inventory/new") or path.endswith("/en/inventory/used")


_MARINEMAX_BOATS_SRP_ZENROWS_JS = _compact_instruction_payload(
    [
        # MarineMax / SkipperBuds Vue+Algolia SRPs: wait for app boot, then scroll so hits load.
        {"wait": 4000},
        {"evaluate": "window.scrollTo(0, Math.min(document.body.scrollHeight, 9000));"},
        {"wait": 4500},
        {"evaluate": "window.scrollTo(0, document.body.scrollHeight);"},
        {"wait": 5500},
    ]
)


_FORD_FAMILY_INVENTORY_ZENROWS_JS = _compact_instruction_payload(
    [
        {"wait": 2500},
        {"evaluate": "window.scrollTo(0, Math.min(document.body.scrollHeight, 5000));"},
        {"wait": 1800},
        {"evaluate": "window.scrollTo(0, Math.min(document.body.scrollHeight, 9000));"},
        {"wait": 1800},
        {"evaluate": "window.scrollTo(0, document.body.scrollHeight);"},
        {"wait": 2200},
    ]
)


def zenrows_inventory_js_instructions_for_url(url: str, platform_id: str | None = None) -> str | None:
    """Return platform-specific ZenRows JS instructions for inventory URLs, if any."""
    if platform_id == "oneaudi_falcon":
        return _ONEAUDI_FALCON_INVENTORY_JS_INSTRUCTIONS.strip()
    if not url:
        return None
    if _looks_like_oneaudi_falcon_inventory_url(url):
        return _ONEAUDI_FALCON_INVENTORY_JS_INSTRUCTIONS.strip()
    if platform_id == "marinemax" and "boats-for-sale" in url.lower():
        return _MARINEMAX_BOATS_SRP_ZENROWS_JS.strip()
    if platform_id in {
        "ford_family_inventory",
        "gm_family_inventory",
        "honda_acura_inventory",
        "nissan_infiniti_inventory",
        "kia_inventory",
    }:
        return _FORD_FAMILY_INVENTORY_ZENROWS_JS.strip()
    return None


def _platform_definition_for_id(platform_id: str | None) -> PlatformDefinition | None:
    if not platform_id:
        return None
    for definition in _PLATFORM_REGISTRY:
        if definition.platform_id == platform_id:
            return definition
    return None


def playwright_inventory_instructions_for_url(url: str, platform_id: str | None = None) -> str | None:
    """Return Playwright-specific interaction steps for inventory URLs, if any."""
    if platform_id == "oneaudi_falcon":
        return _ONEAUDI_FALCON_PLAYWRIGHT_INSTRUCTIONS.strip()
    if platform_id in {
        "ford_family_inventory",
        "nissan_infiniti_inventory",
        "kia_inventory",
    }:
        return _FORD_FAMILY_PLAYWRIGHT_INSTRUCTIONS.strip()
    if platform_id == "dealer_on":
        return _DEALER_ON_PLAYWRIGHT_INSTRUCTIONS.strip()
    if platform_id == "dealer_inspire":
        return _DEALER_INSPIRE_PLAYWRIGHT_INSTRUCTIONS.strip()
    if platform_id == "team_velocity":
        return _TEAM_VELOCITY_PLAYWRIGHT_INSTRUCTIONS.strip()
    if url and _looks_like_oneaudi_falcon_inventory_url(url):
        return _ONEAUDI_FALCON_PLAYWRIGHT_INSTRUCTIONS.strip()
    definition = _platform_definition_for_id(platform_id)
    if definition and definition.requires_render:
        return _RENDER_REQUIRED_PLAYWRIGHT_INSTRUCTIONS.strip()
    return None


def inventory_render_plan_for_url(url: str, platform_id: str | None = None) -> InventoryRenderPlan:
    """Return the local-browser and managed-render instruction plan for an inventory URL."""
    return InventoryRenderPlan(
        playwright_instructions=playwright_inventory_instructions_for_url(url, platform_id=platform_id),
        zenrows_js_instructions=zenrows_inventory_js_instructions_for_url(url, platform_id=platform_id),
    )


_PLATFORM_REGISTRY: tuple[PlatformDefinition, ...] = (
    PlatformDefinition(
        platform_id="marinemax",
        markers=(
            "marinemax.com",
            "skipperbuds.com",
            "find-a-boat-v2",
            "boat-card-template",
            "algoliaapplicationid",
            "algoliaapikey",
        ),
        inventory_path_hints=("boats-for-sale", "boats-for-sale/stores"),
        extraction_mode="rendered_dom",
        requires_render=True,
    ),
    PlatformDefinition(
        platform_id="oneaudi_falcon",
        markers=("oneaudi-falcon", "vtpimages.audi.com"),
        inventory_path_hints=(
            "new-inventory",
            "used-inventory",
            "inventory",
            "new",
            "inventory/new",
            "inventory/used",
            "en/inventory/new",
            "en/inventory/used",
        ),
        extraction_mode="hybrid",
        requires_render=True,
    ),
    PlatformDefinition(
        platform_id="dealer_dot_com",
        markers=(
            "dealer.com",
            "coxautoinc",
            "dealerdotcom",
            "inventoryapiurl",
            "/api/widget/ws-inv-data/getinventory",
            "ddc.widgetdata",
        ),
        inventory_path_hints=("new-inventory", "used-inventory", "searchnew", "searchused", "inventory/index.htm"),
        extraction_mode="structured_api",
    ),
    PlatformDefinition(
        platform_id="dealer_on",
        markers=(
            "dealeron.com",
            "cdn.dealeron",
            "dealeron.js",
            "vhcliaa",
            "searchresultspagewasabibundle",
            "vehicle-card--mod",
        ),
        inventory_path_hints=("searchnew.aspx", "searchused.aspx", "searchnewinventory", "searchusedinventory"),
        extraction_mode="rendered_dom",
    ),
    PlatformDefinition(
        platform_id="dealer_inspire",
        markers=(
            "dealerinspire.com",
            "dealer-inspire",
            "dealerinspire",
            "__next_data__",
            "wp-content/themes/dealerinspire",
        ),
        inventory_path_hints=("new-vehicles", "new-inventory", "used-vehicles", "inventory", "vehicles"),
        extraction_mode="structured_json",
        requires_render=True,
    ),
    PlatformDefinition(
        platform_id="autohausen_ahp6",
        markers=(
            "vgrdapps.autohausen.ag/ahp6/snippet/main.js",
            "ahp6.rendersearch",
            "apps.autohausen.de/ahp6/api",
        ),
        inventory_path_hints=("gebrauchtwagen/fahrzeugsuche", "fahrzeugsuche"),
        extraction_mode="provider",
    ),
    PlatformDefinition(
        platform_id="carzilla_search",
        markers=(
            "carzillasearchinstance",
            "querystringdetailsearch",
            "/?type=17911",
            "cc-link-vehicle-detail",
            "cc-vehicle",
        ),
        inventory_path_hints=("fahrzeuge/fahrzeugsuche", "fahrzeuge/fahrzeugsuche/trefferliste"),
        extraction_mode="provider",
    ),
    PlatformDefinition(
        platform_id="cdk_dealerfire",
        markers=("dealerfire", "fortellis", "cdk", "dealerfire.com"),
        inventory_path_hints=("new-inventory", "used-inventory", "inventory", "new-vehicles"),
        extraction_mode="hybrid",
    ),
    PlatformDefinition(
        platform_id="team_velocity",
        markers=("teamvelocity", "tvs", "team velocity"),
        inventory_path_hints=(
            "inventory/new",
            "inventory/used",
            "new-inventory",
            "used-inventory",
            "inventory",
            "new",
            "certified",
            "pre-owned",
        ),
        extraction_mode="hybrid",
        requires_render=True,
    ),
    PlatformDefinition(
        platform_id="revver_digital_marine",
        markers=(
            "powered by revver digital",
            "name=\"boat_details\"",
            "name='boat_details'",
            "class=\"sbnext\"",
            "onewaterinventory.com/search",
        ),
        inventory_path_hints=("search", "details", "boats-for-sale"),
        extraction_mode="structured_html",
    ),
    PlatformDefinition(
        platform_id="dealer_spike",
        markers=(
            "dealer spike",
            "dealerspike",
            "endeavorsuite",
            "dsp.dealerid",
            "default.asp?page=xallinventory",
            "default.asp?page=xnewinventory",
            "default.asp?page=xpreownedinventory",
            "/inventory/all-inventory-in-stock",
            "/inventory/new-inventory-in-stock",
            "/inventory/used-inventory",
            "/search/inventory",
            "--xallinventory",
            "--xnewinventory",
            "--xpreownedinventory",
        ),
        inventory_path_hints=(
            "default.asp?page=xallinventory",
            "default.asp?page=xnewinventory",
            "inventory/all-inventory-in-stock",
            "inventory/new-inventory-in-stock",
            "all-inventory-in-stock",
            "new-inventory-in-stock",
            "default.asp?page=xpreownedinventory",
            "inventory/used-inventory",
            "inventory/used-inventory-in-stock",
            "used-inventory-in-stock",
        ),
        extraction_mode="hybrid",
    ),
    PlatformDefinition(
        platform_id="basspro_boating_center",
        markers=(
            "bassproboatingcenters.com",
            "data-modelpage=\"/boats-for-sale/boatmodel/\"",
            "class=\"cell inventory-card\"",
            "class=\"mname\"",
        ),
        inventory_path_hints=("boats-for-sale.html", "boats-for-sale/boatmodel", "brands"),
        extraction_mode="structured_html",
    ),
    PlatformDefinition(
        platform_id="d2c_media",
        markers=(
            "d2c media",
            "autoaubaine",
            "##linkrules##",
            "{$name}",
            "member of the autoaubaine network",
        ),
        inventory_path_hints=("new/inventory/search.html", "used/search.html", "new/inventory", "used"),
        extraction_mode="structured_html",
    ),
    PlatformDefinition(
        platform_id="fusionzone",
        markers=("fusionzone", "fusion-zone", "fzautomotive"),
        inventory_path_hints=("inventory", "new-inventory", "used-inventory"),
        extraction_mode="hybrid",
    ),
    PlatformDefinition(
        platform_id="shift_digital",
        markers=("shiftdigital", "shift digital"),
        inventory_path_hints=("inventory", "new-inventory", "used-inventory"),
        extraction_mode="hybrid",
    ),
    PlatformDefinition(
        platform_id="kia_inventory",
        markers=(
            "kia",
            "si-vehicle-box",
            "unlockctadiscountdata",
            "/viewdetails/",
            "inventory_listing",
        ),
        inventory_path_hints=("inventory/new", "inventory/used", "new-", "used-", "certified", "pre-owned"),
        extraction_mode="structured_html",
    ),
    PlatformDefinition(
        platform_id="nissan_infiniti_inventory",
        markers=(
            "infiniti",
            "nissan",
            "si-vehicle-box",
            "unlockctadiscountdata",
            "inventorysettings.data.buttonlabel",
            "/viewdetails/new/",
            "inventory_listing",
        ),
        inventory_path_hints=("inventory/new", "inventory/used", "new-", "used-", "pre-owned"),
        extraction_mode="structured_html",
    ),
    PlatformDefinition(
        platform_id="harley_digital_showroom",
        markers=(
            # Harley-Davidson corporate / dealer "digital showroom" motorcycle SRP (shared group inventory)
            "page_infofilters",
            "harley-davidson",
        ),
        inventory_path_hints=("new-inventory", "used-inventory", "inventory"),
        extraction_mode="structured_html",
        requires_render=True,
    ),
    PlatformDefinition(
        platform_id="honda_acura_inventory",
        markers=(
            "honda",
            "acura",
            "si-vehicle-box",
            "unlockctadiscountdata",
            "/viewdetails/",
            "inventory_listing",
        ),
        inventory_path_hints=("inventory/new", "inventory/used", "new-", "used-", "certified", "pre-owned"),
        extraction_mode="structured_html",
        requires_render=True,
    ),
    PlatformDefinition(
        platform_id="ford_family_inventory",
        markers=(
            "ford",
            "lincoln",
            "si-vehicle-box",
            "unlockctadiscountdata",
            "/viewdetails/",
            "inventory_listing",
        ),
        inventory_path_hints=("inventory/new", "inventory/used", "new-", "used-", "certified", "pre-owned"),
        extraction_mode="structured_html",
        requires_render=True,
    ),
    PlatformDefinition(
        platform_id="gm_family_inventory",
        markers=(
            "chevrolet",
            "chevy",
            "gmc",
            "buick",
            "cadillac",
            "si-vehicle-box",
            "unlockctadiscountdata",
            "/viewdetails/",
            "inventory_listing",
        ),
        inventory_path_hints=("inventory/new", "inventory/used", "new-", "used-", "certified", "pre-owned"),
        extraction_mode="structured_html",
        requires_render=True,
    ),
    PlatformDefinition(
        platform_id="toyota_lexus_oem_inventory",
        markers=(
            "toyota",
            "lexus",
            "si-vehicle-box",
            "unlockctadiscountdata",
            "/viewdetails/",
            "inventory_listing",
            "ws-inv-data",
            "ddc.widgetdata",
        ),
        inventory_path_hints=("new-inventory", "used-inventory", "inventory/new", "inventory/used", "inventory/index.htm"),
        extraction_mode="structured_api",
    ),
    PlatformDefinition(
        platform_id="hyundai_inventory_search",
        markers=(
            "hyundai",
            "/search/new/",
            "/detail/new/",
            "new hyundai",
        ),
        inventory_path_hints=("search/new", "search/used", "detail/new", "detail/used"),
        extraction_mode="structured_html",
    ),
    PlatformDefinition(
        platform_id="purecars",
        markers=("purecars",),
        inventory_path_hints=("inventory", "new-inventory", "used-inventory"),
        extraction_mode="hybrid",
    ),
    PlatformDefinition(
        platform_id="jazel",
        markers=("jazel", "jazelauto", "jazelcauto"),
        inventory_path_hints=("inventory", "new-inventory", "used-inventory"),
        extraction_mode="hybrid",
    ),
)


def _ford_lincoln_allowed(html_lower: str, page_url: str) -> bool:
    """Ford/Lincoln OEM stack: host may contain ford/lincoln; body/URL must not match via substrings like 'affordable'."""
    parsed = urlsplit(page_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "ford" in host or "lincoln" in host:
        return True
    if "ford" in path or "lincoln" in path:
        return True
    blob = f"{html_lower} {page_url.lower()}"
    return bool(
        (_FORD_LINCOLN_BODY_RE.search(blob) or _LINCOLN_BODY_RE.search(blob))
        and not any(token in path for token in ("volkswagen", "vw", "audi", "skoda", "seat", "cupra", "bmw", "mini"))
    )


def _family_stack_allowed_for_target(platform_id: str, html_lower: str, page_url: str) -> bool:
    parsed = urlsplit(page_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    target = html_lower + " " + page_url.lower()
    infiniti_or_nissan_host = "infiniti" in host or "nissan" in host
    if platform_id == "nissan_infiniti_inventory":
        return any(token in host or token in path for token in ("nissan", "infiniti"))
    if platform_id == "honda_acura_inventory":
        # Shared Sonic markers (si-vehicle-box, etc.) must not classify INFINITI/Nissan dealers as Honda/Acura.
        if infiniti_or_nissan_host:
            return False
        return any(token in host or token in path for token in ("honda", "acura"))
    if platform_id == "ford_family_inventory":
        if infiniti_or_nissan_host and "ford" not in host and "lincoln" not in host:
            return False
        # Sonic-style markers appear on many non-Ford EU/UK OEM sites; require Ford/Lincoln in the host
        # before treating the page as the Ford family stack (avoids BMW UK sites misclassified as Ford).
        if "ford" not in host and "lincoln" not in host:
            non_ford_oem = (
                "bmw",
                "mini",
                "mercedes",
                "audi",
                "volkswagen",
                "vw",
                "porsche",
                "jaguar",
                "landrover",
                "land-rover",
                "volvo",
                "cupra",
                "seat",
                "skoda",
                "škoda",
                "peugeot",
                "citroen",
                "citroën",
                "dsautomobiles",
                "renault",
                "fiat",
                "alfaromeo",
                "alfa-romeo",
                "maserati",
                "bentley",
                "rollsroyce",
                "rolls-royce",
                "astonmartin",
                "aston-martin",
                "mclaren",
                "polestar",
                "lynkco",
                "opel",
                "vauxhall",
                "hyundai",
                "kia",
                "toyota",
                "lexus",
                "nissan",
                "honda",
                "mazda",
                "subaru",
                "suzuki",
                "mitsubishi",
                "tesla",
                "byd",
            )
            if any(token in host or token in path for token in non_ford_oem):
                return False
        return _ford_lincoln_allowed(html_lower, page_url)
    if platform_id == "gm_family_inventory":
        if infiniti_or_nissan_host:
            return False
        return any(
            token in host or token in path
            for token in ("chevrolet", "chevy", "gmc", "buick", "cadillac")
        )
    if platform_id == "toyota_lexus_oem_inventory":
        if infiniti_or_nissan_host and "toyota" not in host and "lexus" not in host:
            return False
        # Hostname only: other OEM sites (e.g. Alfa Romeo DDC) mention Toyota/Lexus in
        # footers or comparison copy; body-text matching misroutes to /inventory/new/... SRPs.
        return "toyota" in host or "lexus" in host
    if platform_id == "hyundai_inventory_search":
        return "hyundai" in host or "hyundai" in path
    if platform_id == "kia_inventory":
        return "kia" in host or "kia" in path
    if platform_id == "harley_digital_showroom":
        # National H-D template: /new-inventory and /used-inventory on harley* dealer domains.
        return "harley" in host and (
            "new-inventory" in target or "used-inventory" in target or "/inventory" in target
        )
    return True


def _platform_tie_break_priority(
    definition: PlatformDefinition, target: str, *, page_url: str = ""
) -> int:
    host = urlsplit(page_url).netloc.lower()
    if definition.platform_id == "team_velocity":
        return 30 if any(marker in target for marker in _TEAM_VELOCITY_STRONG_MARKERS) else 0
    if definition.platform_id == "dealer_inspire":
        if any(marker in target for marker in _DEALER_INSPIRE_STRONG_MARKERS):
            return 20
        return 5 if "__next_data__" in target else 0
    if definition.platform_id == "dealer_spike":
        return 35 if any(marker in target for marker in _DEALER_SPIKE_STRONG_MARKERS) else 0
    if definition.platform_id == "nissan_infiniti_inventory":
        if "nissan" in host or "infiniti" in host:
            sonic = sum(1 for marker in _NISSAN_INFINITI_SONIC_MARKERS if marker in target)
            if sonic >= 3:
                return 26
        return 0
    if definition.platform_id == "ford_family_inventory":
        return 25 if all(marker in target for marker in ("ford", "vehicle_results_label")) else (
            18 if sum(1 for marker in _FORD_FAMILY_STRONG_MARKERS if marker in target) >= 4 else 0
        )
    if definition.platform_id == "dealer_dot_com":
        return 15 if "inventoryapiurl" in target or "ddc.widgetdata" in target else 0
    return 0


def _dealer_dot_com_definition() -> PlatformDefinition:
    for definition in _PLATFORM_REGISTRY:
        if definition.platform_id == "dealer_dot_com":
            return definition
    raise RuntimeError("dealer_dot_com platform definition missing from registry")


def _dealer_dot_com_score_for_target(target: str, page_url: str) -> tuple[int, int]:
    ddc_def = _dealer_dot_com_definition()
    score = sum(1 for marker in ddc_def.markers if marker in target)
    priority = _platform_tie_break_priority(ddc_def, target, page_url=page_url)
    return score, priority


def _ddc_fingerprint_dominates_family_stack(target: str, ddc_score: int) -> bool:
    if ddc_score <= 0:
        return False
    if "inventoryapiurl" in target:
        return True
    return "ddc.widgetdata" in target and ddc_score >= 2


def _best_platform_definition(html: str, page_url: str = "") -> PlatformDefinition | None:
    lower = html.lower()
    target = lower + " " + page_url.lower()
    best: tuple[int, int, PlatformDefinition] | None = None
    for definition in _PLATFORM_REGISTRY:
        if not _family_stack_allowed_for_target(definition.platform_id, lower, page_url):
            continue
        score = sum(1 for marker in definition.markers if marker in target)
        if score <= 0:
            continue
        priority = _platform_tie_break_priority(definition, target, page_url=page_url)
        if not best or score > best[0] or (score == best[0] and priority > best[1]):
            best = (score, priority, definition)
    if not best:
        return None
    chosen = best[2]
    if (
        chosen.platform_id in _PLATFORMS_SUBSUMED_BY_DDC_WHEN_DOMINANT
        and any(m in target for m in _DDC_DOMINANT_MARKERS)
    ):
        ddc_def = _dealer_dot_com_definition()
        if _family_stack_allowed_for_target(ddc_def.platform_id, lower, page_url):
            ddc_score, ddc_priority = _dealer_dot_com_score_for_target(target, page_url)
            if _ddc_fingerprint_dominates_family_stack(target, ddc_score):
                return ddc_def
    return chosen


def detect_platform_profile(html: str, page_url: str = "") -> PlatformProfile | None:
    definition = _best_platform_definition(html, page_url=page_url)
    if not definition:
        return None
    score = sum(1 for marker in definition.markers if marker in (html.lower() + " " + page_url.lower()))
    confidence = min(0.55 + 0.1 * score, 0.98)
    return PlatformProfile(
        platform_id=definition.platform_id,
        confidence=confidence,
        extraction_mode=definition.extraction_mode,
        requires_render=definition.requires_render,
        inventory_path_hints=definition.inventory_path_hints,
        detection_source="html_fingerprint",
    )


def detect_platform(html: str, page_url: str = "") -> str | None:
    profile = detect_platform_profile(html, page_url=page_url)
    return profile.platform_id if profile else None


def inventory_hints_for_platform(platform_id: str | None) -> tuple[str, ...]:
    if not platform_id:
        return ()
    for definition in _PLATFORM_REGISTRY:
        if definition.platform_id == platform_id:
            return definition.inventory_path_hints
    return ()


def all_known_platform_ids() -> tuple[str, ...]:
    return tuple(d.platform_id for d in _PLATFORM_REGISTRY)


def _walk_ld_json_vehicle_objects(obj: Any, out: list[dict], depth: int = 0) -> None:
    if depth > 14:
        return
    if isinstance(obj, dict):
        types = obj.get("@type")
        type_list: list[str] = []
        if isinstance(types, str):
            type_list = [types.lower()]
        elif isinstance(types, list):
            type_list = [str(t).lower() for t in types if t]
        if any(t in ("vehicle", "car", "product") for t in type_list):
            if obj.get("vehicleIdentificationNumber") or obj.get("model") or obj.get("name"):
                out.append(obj)
        for v in obj.values():
            _walk_ld_json_vehicle_objects(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_ld_json_vehicle_objects(item, out, depth + 1)


def _list_item_name_to_vehicle_fields(name: str) -> dict[str, Any]:
    text = (name or "").strip()
    if not text:
        return {}
    parts = text.split()
    if len(parts) < 3:
        return {"raw_title": text}
    year = parts[0] if re.fullmatch(r"\d{4}", parts[0]) else None
    make = parts[1] if year else None
    suffix = parts[2:] if year else parts
    model = " ".join(suffix) if suffix else None
    out: dict[str, Any] = {"raw_title": text}
    if year:
        out["year"] = year
    if make:
        out["make"] = make
    if model:
        out["model"] = model
    return out


def _schema_list_item_to_vehicle_dict(item: dict[str, Any]) -> dict[str, Any] | None:
    nested = item.get("item") if isinstance(item.get("item"), dict) else {}
    name = item.get("name") or nested.get("name")
    identifier = (
        item.get("identifier")
        or nested.get("identifier")
        or nested.get("sku")
        or nested.get("vehicleIdentificationNumber")
    )
    url = item.get("url") or nested.get("url")
    image = item.get("image") or nested.get("image")
    offers = nested.get("offers") if isinstance(nested.get("offers"), dict) else {}
    if not any([name, identifier, url, image]):
        return None
    out = _list_item_name_to_vehicle_fields(str(name or ""))
    if identifier:
        out["vin"] = str(identifier)
    if url:
        out["vdpUrl"] = str(url)
    elif offers.get("url"):
        out["vdpUrl"] = str(offers["url"])
    if image:
        out["image_url"] = str(image)
    if offers.get("price") not in (None, ""):
        out["price"] = offers.get("price")
    if nested.get("brand"):
        out["make"] = nested.get("brand")
    if nested.get("vehicleModelDate"):
        out["year"] = nested.get("vehicleModelDate")
    if nested.get("model") and "model" not in out:
        out["model"] = nested.get("model")
    if nested.get("vehicleConfiguration"):
        out["trim"] = nested.get("vehicleConfiguration")
    return out if out else None


def _collect_item_list_vehicle_objects(obj: Any, out: list[dict], depth: int = 0) -> None:
    if depth > 14:
        return
    if isinstance(obj, dict):
        obj_type = obj.get("@type")
        types = [str(obj_type).lower()] if isinstance(obj_type, str) else [str(x).lower() for x in obj_type] if isinstance(obj_type, list) else []
        if "itemlist" in types and isinstance(obj.get("itemListElement"), list):
            for item in obj["itemListElement"]:
                if isinstance(item, dict):
                    converted = _schema_list_item_to_vehicle_dict(item)
                    if converted:
                        out.append(converted)
        for v in obj.values():
            _collect_item_list_vehicle_objects(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _collect_item_list_vehicle_objects(item, out, depth + 1)


def extract_json_ld_vehicle_dicts(html: str) -> list[dict]:
    """Collect schema.org-style vehicle/product objects from application/ld+json scripts."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for script in soup.find_all("script"):
        st = (script.get("type") or "").lower()
        if "ld+json" not in st:
            continue
        raw = script.string or ""
        if len(raw) < 50:
            continue
        try:
            blob = json.loads(raw, strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        _walk_ld_json_vehicle_objects(blob, out)
        _collect_item_list_vehicle_objects(blob, out)
    return out


def provider_enriched_vehicle_dicts(html: str, page_url: str) -> list[dict] | None:
    """
    If a known platform is detected, return extra vehicle-shaped dicts from JSON-LD.
    Returns None if no known platform (caller uses generic extraction).
    """
    profile = detect_platform_profile(html, page_url=page_url)
    if not profile:
        return None
    records = extract_json_ld_vehicle_dicts(html)
    if not records:
        logger.debug("Platform %s detected for %s but no JSON-LD vehicles found", profile.platform_id, page_url)
        return []
    logger.info("Platform %s: %d JSON-LD vehicle record(s) for %s", profile.platform_id, len(records), page_url)
    return records
