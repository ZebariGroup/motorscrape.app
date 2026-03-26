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
    return json.dumps(steps, separators=(",", ":"))


# ZenRows `js_instructions` for infinite-scroll SRPs (e.g. OneAudi Falcon) — host-based, not hard-coded in scraper.
_ONEAUDI_FALCON_INVENTORY_JS_INSTRUCTIONS = _oneaudi_falcon_inventory_js_instructions()

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


def zenrows_inventory_js_instructions_for_url(url: str, platform_id: str | None = None) -> str | None:
    """Return platform-specific ZenRows JS instructions for inventory URLs, if any."""
    if platform_id == "oneaudi_falcon":
        return _ONEAUDI_FALCON_INVENTORY_JS_INSTRUCTIONS.strip()
    if not url:
        return None
    if _looks_like_oneaudi_falcon_inventory_url(url):
        return _ONEAUDI_FALCON_INVENTORY_JS_INSTRUCTIONS.strip()
    return None


_PLATFORM_REGISTRY: tuple[PlatformDefinition, ...] = (
    PlatformDefinition(
        platform_id="oneaudi_falcon",
        markers=("oneaudi-falcon", "audi.com", "vtpimages.audi.com"),
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
        requires_render=True,
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
        platform_id="cdk_dealerfire",
        markers=("dealerfire", "fortellis", "cdk", "dealerfire.com"),
        inventory_path_hints=("new-inventory", "used-inventory", "inventory", "new-vehicles"),
        extraction_mode="hybrid",
    ),
    PlatformDefinition(
        platform_id="team_velocity",
        markers=("teamvelocity", "tvs", "team velocity"),
        inventory_path_hints=("new-inventory", "used-inventory", "inventory", "new"),
        extraction_mode="hybrid",
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


def _family_stack_allowed_for_url(platform_id: str, page_url: str) -> bool:
    target = page_url.lower()
    host = urlsplit(page_url).netloc.lower()
    if platform_id == "nissan_infiniti_inventory":
        return any(token in host or token in target for token in ("nissan", "infiniti"))
    if platform_id == "honda_acura_inventory":
        return any(token in host or token in target for token in ("honda", "acura"))
    if platform_id == "ford_family_inventory":
        return any(token in host or token in target for token in ("ford", "lincoln"))
    if platform_id == "gm_family_inventory":
        return any(
            token in host or token in target
            for token in ("chevrolet", "chevy", "gmc", "buick", "cadillac")
        )
    if platform_id == "toyota_lexus_oem_inventory":
        return any(token in host or token in target for token in ("toyota", "lexus"))
    if platform_id == "hyundai_inventory_search":
        return "hyundai" in host or "hyundai" in target
    if platform_id == "kia_inventory":
        return "kia" in host or "kia" in target
    return True


def _best_platform_definition(html: str, page_url: str = "") -> PlatformDefinition | None:
    lower = html.lower()
    target = lower + " " + page_url.lower()
    best: tuple[int, PlatformDefinition] | None = None
    for definition in _PLATFORM_REGISTRY:
        if not _family_stack_allowed_for_url(definition.platform_id, page_url):
            continue
        score = sum(1 for marker in definition.markers if marker in target)
        if score <= 0:
            continue
        if not best or score > best[0]:
            best = (score, definition)
    return best[1] if best else None


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
