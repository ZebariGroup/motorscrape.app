"""Platform detection, provider registry, and JSON-LD helpers for dealer sites."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

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


_PLATFORM_REGISTRY: tuple[PlatformDefinition, ...] = (
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
        inventory_path_hints=("new-inventory", "used-vehicles", "inventory", "vehicles"),
        extraction_mode="structured_json",
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
        platform_id="nissan_infiniti_inventory",
        markers=(
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


def _best_platform_definition(html: str, page_url: str = "") -> PlatformDefinition | None:
    lower = html.lower()
    target = lower + " " + page_url.lower()
    best: tuple[int, PlatformDefinition] | None = None
    for definition in _PLATFORM_REGISTRY:
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
    name = item.get("name")
    identifier = item.get("identifier")
    url = item.get("url")
    image = item.get("image")
    if not any([name, identifier, url, image]):
        return None
    out = _list_item_name_to_vehicle_fields(str(name or ""))
    if identifier:
        out["vin"] = str(identifier)
    if url:
        out["vdpUrl"] = str(url)
    if image:
        out["image_url"] = str(image)
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
