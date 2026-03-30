"""LLM-assisted extraction of vehicle listings from arbitrary HTML."""

from __future__ import annotations

import asyncio
import base64
import html as stdlib_html
import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from app.config import settings
from app.schemas import ExtractionResult, PaginationInfo, VehicleListing
from app.services.dealer_platforms import provider_enriched_vehicle_dicts
from app.services.inventory_filters import (
    apply_page_make_scope,
    listing_matches_filters,
    normalize_vehicle_condition,
)

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None
_openai_sem: asyncio.Semaphore | None = None
_openai_init_lock = asyncio.Lock()
_openai_disabled_reason: str | None = None


async def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        async with _openai_init_lock:
            if _openai_client is None:
                _openai_client = AsyncOpenAI(
                    api_key=settings.openai_api_key,
                    max_retries=2,
                    timeout=settings.openai_timeout,
                )
    return _openai_client


async def _get_openai_semaphore() -> asyncio.Semaphore:
    global _openai_sem
    if _openai_sem is None:
        async with _openai_init_lock:
            if _openai_sem is None:
                _openai_sem = asyncio.Semaphore(max(1, settings.openai_max_concurrency))
    return _openai_sem


async def close_openai_client() -> None:
    """Close shared AsyncOpenAI client (app shutdown)."""
    global _openai_client, _openai_disabled_reason, _openai_sem
    async with _openai_init_lock:
        if _openai_client is not None:
            await _openai_client.close()
            _openai_client = None
        _openai_sem = None
        _openai_disabled_reason = None


def _openai_error_status_code(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _openai_error_text(error: Exception) -> str:
    body = getattr(error, "body", None)
    parts: list[str] = []
    if body is not None:
        parts.append(str(body))
    message = str(error).strip()
    if message:
        parts.append(message)
    return " | ".join(parts).lower()


def _is_openai_quota_or_billing_error(error: Exception) -> bool:
    detail = _openai_error_text(error)
    if not detail:
        return False
    if "insufficient_quota" in detail:
        return True
    if "exceeded your current quota" in detail:
        return True
    status_code = _openai_error_status_code(error)
    if status_code == 429 and "billing" in detail:
        return True
    return False


def _build_no_llm_fallback_result(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
    vehicle_category: str,
) -> ExtractionResult:
    structured = try_extract_vehicles_without_llm(
        page_url=page_url,
        html=html,
        make_filter=make_filter,
        model_filter=model_filter,
        vehicle_category=vehicle_category,
    )
    if structured is not None:
        return structured
    fallback_page_size = max(
        len(
            extract_dom_vehicle_cards(
                html,
                page_url,
                vehicle_category=vehicle_category,
                model_filter=model_filter,
            )
        ),
        len(_extract_search_result_card_vehicles(html, page_url, vehicle_category=vehicle_category)),
    )
    pagination = infer_inventory_pagination(
        html,
        page_url,
        fallback_page_size=fallback_page_size or None,
    )
    next_u = (
        find_next_page_url(html, page_url)
        or _next_page_url_from_pagination(
            page_url,
            pagination,
            fallback_page_size=fallback_page_size or None,
        )
    )
    return ExtractionResult(vehicles=[], next_page_url=next_u, pagination=pagination)


SYSTEM_PROMPT = """You extract motor vehicle inventory from dealership webpage HTML or JSON data.

Filtering (highest priority):
- The user message includes optional make and model filters.
- If a model filter is non-empty: return ONLY vehicles of that model. Match common variants
  (e.g. F-150, F150, F 150 are the same model). Do NOT return other models from the same make.
- If a make filter is non-empty but model is empty: return vehicles of that make only.
- If both filters are empty: extract all real vehicles for sale on the page.

Extraction rules:
- Only real motor vehicles for sale (cars, trucks, SUVs, motorcycles, boats, and similar powered vehicles). Skip service specials, parts, disclaimers, nav.
- Prefer listing-specific URLs and images when present.
- Do not invent VINs, prices, or stock numbers; use null if not clearly present.
- Keep the listing's category aligned with the requested vehicle category when the page supports it.
- Set `vehicle_condition` to `new` or `used` when clearly stated; otherwise use null.
- When MSRP and a lower sale price are both shown, set `msrp` and `price` (sale), and set
  `dealer_discount` to the gap (msrp - sale) if not stated explicitly elsewhere.
- Capture visible incentives/rebates as short strings in `incentive_labels` (e.g. "Lease Credit: $1500").
- When packages, option groups, or notable equipment lists appear, add concise lines to `feature_highlights` (max ~6 strings).
- If a stock/arrival date or "days on lot" is shown, set `stock_date` as YYYY-MM-DD when parseable, and/or `days_on_lot` as an integer.
- If there is a clear next-page link for inventory, set `next_page_url` to its absolute URL.
- Data may be provided as structured JSON extracted from the page. Parse it the same way.

European pages (EN/FR/DE and similar):
- Always populate `make` with the brand when the listing is for a single-brand dealer, even if the visible title only shows model lines (e.g. "320d M Sport" → make BMW).
- Map condition words: e.g. French *occasion/neuf*, German *Gebrauchtwagen/Neuwagen* to `used`/`new`.
"""

_INVENTORY_KEYS = {
    "make",
    "manuf",  # Dealer Spike Marine uses "manuf" for manufacturer/make
    "itemmake",  # Dealer Spike / Endeavor inventory payloads
    "model",
    "itemmodel",  # Dealer Spike / Endeavor inventory payloads
    "vin",
    "hin",
    "stock",
    "stockno",
    "stock_no",
    "stocknumber",
    "itemurl",  # Dealer Spike / Endeavor inventory payloads
    "itemprice",  # Dealer Spike / Endeavor inventory payloads
    "itemyear",  # Dealer Spike / Endeavor inventory payloads
    "bodystyle",
    "bodytype",
    "enginehours",
    "engine_hours",
    # Help nested inventory records match even when mileage uses OEM-specific keys
    "miles",
    "mileage",
    "odometer",
    "odometermiles",
    "odometerreading",
    "mileagevalue",
    # Dealer Inspire / Next.js SRP payloads (camelCase keys lowercased in _collect_vehicle_arrays)
    "vehiclemake",
    "vehiclemodel",
    "vehicleyear",
    "makename",
    "modelname",
    "detailurl",
    "vehicleurl",
    "vdppath",
}

_VEHICLE_KEEP_KEYS = {
    "make", "model", "trim", "year", "miles", "mileage", "odometer", "odometermiles", "price",
    "priceinet", "price_inet", "pricesticker", "vin", "stockno",
    "stock_no", "bodytype", "bodystyle", "colorexterior", "colorinterior",
    "transmission", "engine", "drivetrain", "vdpurl", "vdp_url",
    "imagespath", "images_path", "imageurl", "image_url",
    "cylinders", "doors", "fueltype", "status", "condition",
    "vehiclecondition", "newused", "inventorytype", "itemcondition",
    "hin", "hullidentificationnumber", "enginehours", "engine_hours",
}

_VEHICLE_FULL_REGEX = re.compile(
    r'\\"id\\":(?P<id>\d+)(?:.*?\\"bodyType\\":\\"(?P<bodyType>[^\\]*)\\")?'
    r'(?:.*?\\"colorExterior\\":\\"(?P<colorExterior>[^\\]*)\\")?'
    r'(?:.*?\\"make\\":\\"(?P<make>[^\\]+)\\")'
    r'(?:.*?\\"miles\\":(?:null|\\"?(?P<miles>[^\\,"]+)\\"?))?'
    r'(?:.*?\\"model\\":\\"(?P<model>[^\\]+)\\")'
    r'(?:.*?\\"priceInet\\":\\"(?P<price>[^\\]*)\\")?'
    r'(?:.*?\\"trim\\":\\"(?P<trim>[^\\]*)\\")?'
    r'(?:.*?\\"vin\\":\\"(?P<vin>[^\\]*)\\")?'
    r'(?:.*?\\"vdpUrl\\":\\"(?P<vdpUrl>[^\\]*)\\")?',
)
_TEXT_PRICE_RE = re.compile(r"\$([0-9][0-9,]{2,})(?:\.\d{2})?")
_TEXT_MILEAGE_LABELED_RE = re.compile(r"\bmileage\s*:\s*([0-9][0-9,]{0,6})\b", re.I)
_TEXT_MILEAGE_UNITS_RE = re.compile(r"\b([0-9][0-9,]{0,6})\s*(?:mi|miles?)\b", re.I)
_TEXT_ODOMETER_LABELED_RE = re.compile(
    r"\b(?:odometer|odo)\s*:\s*([0-9][0-9,]{0,6})\b",
    re.I,
)
_TEXT_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_TEXT_HIN_RE = re.compile(r"\b([A-Z]{3}[A-Z0-9]{5}[A-Z0-9]{4})\b")
_TEXT_ENGINE_HOURS_RE = re.compile(r"\b([0-9][0-9,]{0,6})\s*(?:hrs?|hours?)\b", re.I)
_TEXT_STOCK_RE = re.compile(
    r"\b(?:stock(?:\s*(?:#|number|no\.?))?)\s*[:#-]?\s*([A-Z0-9-]{4,})\b",
    re.I,
)
_INVENTORY_DETAIL_PATH_RE = re.compile(
    r"/inventory/\d+(?:/|$)|/viewdetails/", re.I
)
_TITLE_YEAR_RE = re.compile(r"^(?P<year>20\d{2}|19\d{2})\s+(?P<rest>.+)$")
_SAVE_PRICE_MSRP_RE = re.compile(
    r"save:\s*\$[\d,]+\s*\$(?P<price>[\d,]+)\s*msrp\s*\$(?P<msrp>[\d,]+)",
    re.I,
)
_HYUNDAI_SEARCH_TITLE_RE = re.compile(
    r"^(?P<year>20\d{2}|19\d{2})\s+(?P<make>[A-Za-z]+)\s+(?P<model>[A-Z0-9-]+)\s+(?P<trim>.+?)\s+Save:",
    re.I,
)
_SPACE_VEHICLES_JSON_RE = re.compile(
    r"space_vehicles_json\s*=\s*JSON\.parse\(\s*\"(?P<body>(?:\\.|[^\"])*)\"\s*\)",
    re.S,
)
# GA4 / ASC datalayer used by Sonic / LaFontaine / similar DMS: var ga4ASCDataLayerVehicle = '[{...}]';
_GA4_ASC_DATALAYER_RE = re.compile(
    r"var\s+ga4ASCDataLayerVehicle\s*=\s*'(?P<body>\[.*?\])'\s*;",
    re.S,
)
# Dealer Spike / Endeavor Suite embeds one JSON object per card directly in the HTML body.
_ENDEAVOR_ITEM_OBJECT_RE = re.compile(
    r"\{[^{}]*\"itemUrl\"\s*:\s*\"[^\"]+\"[^{}]*\}",
    re.S,
)
# Generic JS array var patterns: var resultCount = '42'; sonicDataLayerVehicleImpressions = '...'
_SONIC_RESULT_COUNT_RE = re.compile(r"var\s+resultCount\s*=\s*'(\d+)'", re.S)
_DISPLAY_RANGE_TOTAL_RES = (
    re.compile(
        r"\bshowing\s+(?P<start>\d{1,5})\s*(?:-|to|–|—)\s*(?P<end>\d{1,5})\s+of\s+(?P<total>\d{1,7})\b",
        re.I,
    ),
    re.compile(
        r"\b(?P<start>\d{1,5})\s*(?:-|to|–|—)\s*(?P<end>\d{1,5})\s+of\s+"
        r"(?P<total>\d{1,7})\s+(?:results?|vehicles?|listings?|matches?)\b",
        re.I,
    ),
)
_PAGE_OF_TOTAL_RE = re.compile(r"\bpage\s*:?\s*(?P<page>\d{1,5})\s+of\s+(?P<total>\d{1,5})\b", re.I)
_GENERIC_CARD_ACTION_TEXTS = frozenset({"click for price", "more info", "details", "learn more"})
_KNOWN_MAKE_PREFIXES = tuple(
    sorted(
        {
            # Cars / motorcycles
            "Alfa Romeo",
            "BMW Motorrad",
            "Can-Am",
            "Harley-Davidson",
            "Indian Motorcycle",
            "Land Rover",
            "Mercedes-Benz",
            # Boats — SkipperBud's brand list (authoritative US marine retail reference)
            "ATX Surf Boats",
            "ATX",
            "Barletta",
            "Bennington",
            "Boston Whaler",
            "Carolina Classic",
            "Carver Yachts",
            "Chris Craft",
            "Cobalt",
            "Correct Craft",
            "Crestliner",
            "Cruisers Yachts",
            "Four Winns",
            "Godfrey",
            "Harris Pontoon",
            "JC Mfg",
            "Key West Boats",
            "Key West",
            "MB Sports",
            "MasterCraft",
            "Misty Harbor",
            "Palm Beach",
            "Ranger Boats",
            "Robalo",
            "Sea Fox",
            "Sea Nymph",
            "Sea Pro",
            "Sea Ray",
            "Sea-Doo",
            "South Bay",
            "Starcraft",
            "Sun Chaser",
            "Sun Tracker",
            "SunCatcher",
            "Tiara Yachts",
            "Willard Boat Works",
            "World Cat",
            "Yamaha Boats",
        },
        key=len,
        reverse=True,
    )
)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n<!-- truncated middle -->\n\n" + text[-half:]


def _extract_json_inventory(html: str, soup: BeautifulSoup) -> list[dict]:
    """Pull vehicle records from embedded JSON via parsing or regex fallback."""
    json_records: list[dict] = []

    for script in soup.find_all("script"):
        raw = script.string or ""
        if len(raw) < 200:
            continue

        sid = (script.get("id") or "").lower()
        stype = (script.get("type") or "").lower()
        is_data_script = sid == "__next_data__" or stype in (
            "application/json", "application/ld+json",
        )

        # Extract GA4 / Sonic / ASC datalayer inventory from inline JS scripts
        # regardless of script type: var ga4ASCDataLayerVehicle = '[{...}]';
        m_ga4 = _GA4_ASC_DATALAYER_RE.search(raw)
        if m_ga4:
            try:
                vehicles = json.loads(m_ga4.group("body"), strict=False)
                if isinstance(vehicles, list):
                    for v in vehicles:
                        if isinstance(v, dict) and (v.get("item_make") or v.get("item_id")):
                            normalized = {
                                "make": v.get("item_make"),
                                "model": v.get("item_model"),
                                "year": v.get("item_year") or None,
                                "vin": v.get("item_id"),
                                "price": v.get("item_price"),
                                "condition": v.get("item_condition"),
                                "colorExterior": v.get("item_color"),
                                "stock": v.get("item_number"),
                                "bodyStyle": v.get("item_type"),
                            }
                            json_records.append({k: v for k, v in normalized.items() if v not in (None, "", 0)})
                    if json_records:
                        logger.info("GA4 ASC datalayer: extracted %d vehicle records from inline JS", len(json_records))
            except (json.JSONDecodeError, ValueError, AttributeError):
                pass

        if not is_data_script:
            continue

        try:
            blob = json.loads(raw, strict=False)
        except (json.JSONDecodeError, ValueError):
            for match in _SPACE_VEHICLES_JSON_RE.finditer(raw):
                try:
                    decoded = json.loads(f"\"{match.group('body')}\"")
                    blob = json.loads(decoded, strict=False)
                except (json.JSONDecodeError, ValueError):
                    continue
                _collect_vehicle_arrays(blob, json_records)
            continue

        _collect_vehicle_arrays(blob, json_records)

    for node in soup.find_all("input", attrs={"name": "boat_details"}):
        raw = node.get("value")
        if not raw:
            continue
        try:
            boat_details = json.loads(stdlib_html.unescape(str(raw)), strict=False)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(boat_details, dict):
            continue
        normalized = {
            "title": boat_details.get("title"),
            "stockNumber": boat_details.get("stockNumber"),
            "price": boat_details.get("price"),
            "sharePhoto": boat_details.get("sharePhoto"),
            "condition": boat_details.get("condition"),
            "owner": boat_details.get("owner"),
            "year": boat_details.get("year"),
            "make": boat_details.get("make"),
            "model": boat_details.get("model"),
        }
        if any(normalized.values()):
            json_records.append({k: v for k, v in normalized.items() if v not in (None, "", [], {})})

    # Dealer Spike / Endeavor pages may embed one JSON object per inventory card directly in body HTML.
    json_records.extend(_extract_endeavor_inventory_objects(html))

    regex_records = _extract_vehicles_regex(html)

    if len(regex_records) > len(json_records):
        return regex_records

    return [_normalize_schema_org(r) for r in json_records] if json_records else []


def _normalize_schema_org(rec: dict) -> dict:
    """Flatten schema.org Vehicle format to simple key-value pairs."""
    out: dict[str, Any] = {}
    for k, v in rec.items():
        if k.startswith("@"):
            continue
        if isinstance(v, dict):
            if k in ("trackingPricing", "pricing", "offers"):
                out[k] = v
            elif "name" in v:
                out[k] = v["name"]
            elif "value" in v:
                out[k] = v["value"]
            elif "contentUrl" in v:
                out[k] = v["contentUrl"]
            elif "price" in v:
                out["price"] = v["price"]
        else:
            out[k] = v

    if "manufacturer" in out and "make" not in out:
        out["make"] = out.pop("manufacturer")
    if "brand" in out and "make" not in out:
        out["make"] = out.pop("brand")
    if "manuf" in out and "make" not in out:
        out["make"] = out.pop("manuf")
    if "vehicleIdentificationNumber" in out and "vin" not in out:
        out["vin"] = out.pop("vehicleIdentificationNumber")
    if "mileageFromOdometer" in out and "mileage" not in out:
        mfo = out.pop("mileageFromOdometer")
        if isinstance(mfo, dict):
            mfo = mfo.get("value") or mfo.get("name")
        if mfo not in (None, "", []):
            out["mileage"] = mfo
    if "vehicleModelDate" in out and "year" not in out:
        out["year"] = out.pop("vehicleModelDate")
    if "color" in out and "colorExterior" not in out:
        out["colorExterior"] = out.pop("color")
    if "url" in out and "vdpUrl" not in out:
        out["vdpUrl"] = out.pop("url")

    return out


def _merge_vehicle_dicts(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        current = merged.get(key)
        if current in (None, "", [], {}):
            merged[key] = value
            continue
        if isinstance(current, dict) and isinstance(value, dict):
            nested = dict(current)
            for nk, nv in value.items():
                if nv not in (None, "", [], {}):
                    nested[nk] = nv
            merged[key] = nested
            continue
        if isinstance(current, list) and isinstance(value, list):
            if len(value) > len(current):
                merged[key] = value
            continue
        if isinstance(current, str) and isinstance(value, list):
            merged[key] = value
            continue
        if len(str(value)) > len(str(current)):
            merged[key] = value
    return merged


def _collect_vehicle_arrays(obj: Any, out: list[dict], depth: int = 0) -> None:
    """Recursively walk parsed JSON and collect dicts that look like vehicle inventory."""
    if depth > 12:
        return
    if isinstance(obj, dict):
        lower_keys = {k.lower() for k in obj.keys()}
        title = str(obj.get("name") or obj.get("title") or obj.get("vehicleTitle") or obj.get("item") or "").strip()
        has_vehicle_offer_record = (
            any(key in lower_keys for key in {"brand", "make", "manufacturer", "manuf", "itemmake"})
            and any(key in lower_keys for key in {"offers", "price", "itemprice"})
            and (
                any(
                    key in lower_keys
                    for key in {
                        "model",
                        "itemmodel",
                        "vehicleconfiguration",
                        "vehiclecondition",
                        "vehicleidentificationnumber",
                        "vin",
                        "vehiclemodeldate",
                        "bodystyle",
                        "bodytype",
                    }
                )
                or bool(_TITLE_YEAR_RE.match(title))
            )
        )
        if len(lower_keys & _INVENTORY_KEYS) >= 2 or has_vehicle_offer_record:
            out.append(obj)
            return
        for v in obj.values():
            _collect_vehicle_arrays(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _collect_vehicle_arrays(item, out, depth + 1)
    elif isinstance(obj, str) and len(obj) > 500:
        try:
            parsed = json.loads(obj, strict=False)
            _collect_vehicle_arrays(parsed, out, depth + 1)
        except (json.JSONDecodeError, ValueError):
            pass


def _extract_vehicles_regex(html: str) -> list[dict]:
    """Fallback: pull vehicle records from raw HTML using regex when JSON parsing fails."""
    inv_start = html.find('\\"inventory\\":[')
    if inv_start < 0:
        return []
    inv_start += len('\\"inventory\\":[')
    search_region = html[inv_start : inv_start + 500_000]

    records: list[dict] = []
    for m in _VEHICLE_FULL_REGEX.finditer(search_region):
        rec = {k: v for k, v in m.groupdict().items() if v is not None and v != "null"}
        if rec.get("make"):
            if rec.get("vdpUrl"):
                rec["vdpUrl"] = rec["vdpUrl"].replace("\\/", "/")
            records.append(rec)

    if records:
        logger.info("Regex fallback extracted %d vehicle records from HTML", len(records))
    return records


def _extract_endeavor_inventory_objects(html: str) -> list[dict[str, Any]]:
    """Extract Dealer Spike / Endeavor inventory card JSON blobs embedded in body HTML."""
    records: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for match in _ENDEAVOR_ITEM_OBJECT_RE.finditer(html):
        raw = match.group(0).strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw, strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        if not parsed.get("itemUrl"):
            continue
        dedupe_key = str(parsed.get("productId") or parsed.get("productGuid") or parsed.get("itemUrl")).strip()
        if not dedupe_key or dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        records.append(parsed)
    return records


def _vehicles_to_text(records: list[dict]) -> str:
    """Convert raw JSON vehicle records to a compact text block for the LLM."""
    lines: list[str] = []
    for rec in records:
        parts: list[str] = []
        for k, v in rec.items():
            if k.lower() in _VEHICLE_KEEP_KEYS and v not in (None, "", [], {}):
                parts.append(f"{k}={v}")
        if parts:
            lines.append(" | ".join(parts))
    return "\n".join(lines)


def _clean_html(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "meta",
                     "link", "head", "footer", "header", "nav", "form"]):
        tag.decompose()

    for tag in soup.find_all(href=True):
        tag["href"] = urljoin(base_url, tag["href"])
    for tag in soup.find_all(src=True):
        tag["src"] = urljoin(base_url, tag["src"])

    for tag in soup.find_all(True):
        attrs = dict(tag.attrs)
        for attr in attrs:
            if attr not in ["href", "src", "alt", "class"]:
                del tag[attr]

    return str(soup)


def _prepare_snippet_sync(html: str, base_url: str, max_chars: int) -> str:
    """Extract embedded JSON vehicle data + cleaned HTML, respecting the char budget."""
    # Always walk the full HTML for embedded JSON / JSON-LD (injected API payloads may be at the end).
    soup_full = BeautifulSoup(html, "lxml")
    json_records = _extract_json_inventory(html, soup_full)

    max_raw = max(max_chars * 3, 600_000)
    capped = html[:max_raw] if len(html) > max_raw else html

    json_section = ""
    if json_records:
        json_text = _vehicles_to_text(json_records)
        json_budget = min(max_chars * 3 // 4, len(json_text))
        json_section = (
            "=== EMBEDDED VEHICLE DATA (from page JSON) ===\n"
            + json_text[:json_budget]
            + "\n=== END VEHICLE DATA ===\n\n"
        )
        logger.info(
            "Extracted %d vehicle records from JSON (%d chars)",
            len(json_records),
            len(json_section),
        )

    cleaned = _clean_html(capped, base_url)
    html_budget = max(max_chars - len(json_section), max_chars // 4)
    cleaned = _truncate(cleaned, html_budget)

    return json_section + cleaned


def _coerce_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    s = str(val).strip().replace(",", "")
    if not s:
        return None
    lower = s.lower()
    m_k = re.search(r"(\d+(?:\.\d+)?)\s*k\b", lower)
    if m_k:
        return int(float(m_k.group(1)) * 1000)
    try:
        return int(float(s))
    except ValueError:
        m = re.search(r"\d+", s)
        return int(m.group(0)) if m else None


def _coerce_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    s = re.sub(r"[^\d.]", "", str(val))
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _coerce_bool(val: Any) -> bool | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    text = str(val).strip().lower()
    if text in {"true", "1", "yes", "y", "in stock", "instock"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _extract_price_from_text(text: str | None) -> float | None:
    if not text:
        return None
    for match in _TEXT_PRICE_RE.finditer(text):
        price = _coerce_float(match.group(0))
        if price and price > 500:
            return price
    return None


def _unwrap_quantitative_value(val: Any) -> Any:
    """schema.org QuantitativeValue and similar `{value: n}` wrappers."""
    if isinstance(val, dict):
        if "value" in val:
            return val.get("value")
        if "mileageValue" in val:
            return val.get("mileageValue")
    return val


# Ordered: most specific / common dealer API & DMS field names first
_MILEAGE_FIELD_KEYS: tuple[str, ...] = (
    "odometerMiles",
    "odometer_miles",
    "vehicleOdometer",
    "vehicle_odometer",
    "actualMileage",
    "actual_mileage",
    "mileageValue",
    "mileage_value",
    "odometerReading",
    "odometer_reading",
    "odometerValue",
    "odometer_value",
    "milesOdometer",
    "miles_odometer",
    "mileageFromOdometer",
    "displayMileage",
    "display_mileage",
    "odometer",
    "mileage",
    "miles",
    "mile",
    "odo",
)


def _mileage_int_from_flat_dict(d: dict[str, Any]) -> int | None:
    for key in _MILEAGE_FIELD_KEYS:
        if key not in d:
            continue
        raw = _unwrap_quantitative_value(d.get(key))
        miles = _coerce_int(raw)
        if miles is not None:
            return miles
    return None


def _mileage_int_from_dict(d: dict[str, Any]) -> int | None:
    m = _mileage_int_from_flat_dict(d)
    if m is not None:
        return m
    for nested_key in ("vehicle", "inventoryItem", "inventory", "unit", "attributes", "specs"):
        sub = d.get(nested_key)
        if isinstance(sub, dict):
            m = _mileage_int_from_flat_dict(sub)
            if m is not None:
                return m
    return None


def _extract_mileage_from_text(text: str | None) -> int | None:
    if not text:
        return None
    for match in _TEXT_MILEAGE_LABELED_RE.finditer(text):
        miles = _coerce_int(match.group(1))
        if miles is not None:
            return miles
    for match in _TEXT_ODOMETER_LABELED_RE.finditer(text):
        miles = _coerce_int(match.group(1))
        if miles is not None:
            return miles
    for match in _TEXT_MILEAGE_UNITS_RE.finditer(text):
        miles = _coerce_int(match.group(1))
        if miles is not None:
            return miles
    return None


def _extract_engine_hours_from_text(text: str | None) -> int | None:
    if not text:
        return None
    for match in _TEXT_ENGINE_HOURS_RE.finditer(text):
        hours = _coerce_int(match.group(1))
        if hours is not None:
            return hours
    return None


def _extract_vin_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = _TEXT_VIN_RE.search(text.upper())
    return match.group(1) if match else None


def _extract_hin_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = _TEXT_HIN_RE.search(text.upper())
    return match.group(1) if match else None


def _extract_stock_number_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = _TEXT_STOCK_RE.search(text)
    return match.group(1).upper() if match else None


def _normalize_vehicle_identifier(value: object, *, vehicle_category: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if _TEXT_VIN_RE.fullmatch(text):
        return text
    if vehicle_category == "boat" and _TEXT_HIN_RE.fullmatch(text):
        return text
    if re.fullmatch(r"[A-Z0-9-]{4,}", text):
        return text
    return None


def _pick_vehicle_identifier(
    d: dict[str, Any],
    *,
    vehicle_category: str,
    fallback_text: str | None = None,
) -> str | None:
    candidates = [
        d.get("vehicle_identifier"),
        d.get("vin"),
        d.get("vehicleIdentificationNumber"),
        d.get("vehicle_identification_number"),
        d.get("hin"),
        d.get("hullIdentificationNumber"),
        d.get("hull_id"),
        d.get("stock"),
        d.get("stockNo"),
        d.get("stock_no"),
        d.get("stockNumber"),
        d.get("stocknumber"),
        d.get("stock_number"),
        d.get("identifier"),
    ]
    for candidate in candidates:
        identifier = _normalize_vehicle_identifier(candidate, vehicle_category=vehicle_category)
        if identifier:
            return identifier
    if vehicle_category == "boat":
        fallback_hin = _extract_hin_from_text(fallback_text)
        if fallback_hin:
            return fallback_hin
    fallback_vin = _extract_vin_from_text(fallback_text)
    if fallback_vin:
        return fallback_vin
    return _extract_stock_number_from_text(fallback_text)


def _pick_usage_from_dict(
    d: dict[str, Any],
    *,
    vehicle_category: str,
    fallback_text: str | None = None,
) -> tuple[int | None, str | None]:
    hour_candidates = (
        d.get("engineHours"),
        d.get("engine_hours"),
        d.get("hours"),
        d.get("hourMeter"),
        d.get("hour_meter"),
    )
    if vehicle_category in {"boat", "other"}:
        for candidate in hour_candidates:
            hours = _coerce_int(candidate)
            if hours is not None:
                return hours, "hours"
        fallback_hours = _extract_engine_hours_from_text(fallback_text)
        if fallback_hours is not None:
            return fallback_hours, "hours"
    miles = _mileage_int_from_dict(d)
    if miles is not None:
        return miles, "miles"
    fallback_miles = _extract_mileage_from_text(fallback_text)
    if fallback_miles is not None:
        return fallback_miles, "miles"
    return None, None


def _parse_title_fields(raw_title: str | None) -> dict[str, Any]:
    title = (raw_title or "").strip()
    if not title:
        return {}
    title = re.sub(r"^(new|used|certified|cpo)\s+", "", title, flags=re.I)
    match = _TITLE_YEAR_RE.match(title)
    if not match:
        return {"raw_title": title}
    rest = match.group("rest").strip()
    parts = rest.split()
    out: dict[str, Any] = {"raw_title": title, "year": _coerce_int(match.group("year"))}
    rest_lower = rest.lower()
    for make_prefix in _KNOWN_MAKE_PREFIXES:
        prefix_lower = make_prefix.lower()
        if rest_lower == prefix_lower or rest_lower.startswith(f"{prefix_lower} "):
            remainder = rest[len(make_prefix):].strip()
            remainder_parts = remainder.split()
            out["make"] = make_prefix
            if remainder_parts:
                out["model"] = remainder_parts[0]
            if len(remainder_parts) >= 2:
                out["trim"] = " ".join(remainder_parts[1:])
            return out
    if parts:
        out["make"] = parts[0]
    if len(parts) >= 2:
        out["model"] = parts[1]
    if len(parts) >= 3:
        out["trim"] = " ".join(parts[2:])
    return out


def _pick_price_from_dict(d: dict[str, Any]) -> float | None:
    # First, look for a definitive final price in Dealer.com's pricing.dprice structure
    pricing_obj = d.get("pricing")
    if isinstance(pricing_obj, dict):
        dprice = pricing_obj.get("dprice")
        if isinstance(dprice, list):
            for row in dprice:
                if isinstance(row, dict) and row.get("isFinalPrice"):
                    p = _coerce_float(row.get("value"))
                    if p is not None and p > 0:
                        return p

    for key in (
        "price",
        "priceInet",
        "price_inet",
        "internetPrice",
        "sellingPrice",
        "salePrice",
        "askingPrice",
        "retailPrice",
        "retailValue",
        "itemPrice",
        "unitPrice",
        "msrp",
    ):
        p = _coerce_float(d.get(key))
        if p is not None and p > 0:
            return p
    for pricing_key in ("trackingPricing", "pricing"):
        pricing = d.get(pricing_key)
        if isinstance(pricing, dict):
            for key in ("internetPrice", "salePrice", "askingPrice", "retailPrice", "retailValue", "msrp"):
                p = _coerce_float(pricing.get(key))
                if p is not None and p > 0:
                    return p
            dprice = pricing.get("dprice")
            if isinstance(dprice, list):
                for row in dprice:
                    if not isinstance(row, dict):
                        continue
                    p = _coerce_float(row.get("value"))
                    if p is not None and p > 0:
                        return p
    offers = d.get("offers")
    if isinstance(offers, dict):
        for key in ("price", "lowPrice", "highPrice"):
            p = _coerce_float(offers.get(key))
            if p is not None and p > 0:
                return p
    return None


def _format_price_label(label: str, value: float) -> str:
    rounded = abs(value)
    if abs(value - round(rounded)) < 0.01:
        return f"{label}: ${rounded:,.0f}"
    return f"{label}: ${value:,.2f}"


def _walk_pricing_dicts(d: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for key in ("pricing", "trackingPricing"):
        p = d.get(key)
        if isinstance(p, dict):
            blocks.append(p)
    return blocks


def _extract_msrp_from_dict(d: dict[str, Any]) -> float | None:
    for label in ("msrp", "baseMsrp", "base_msrp", "listPrice", "list_price", "retailPrice"):
        m = _coerce_float(d.get(label))
        if m is not None and m > 0:
            return m
    for pricing in _walk_pricing_dicts(d):
        for label in ("msrp", "retailPrice", "retailValue", "listPrice"):
            m = _coerce_float(pricing.get(label))
            if m is not None and m > 0:
                return m
        dprice = pricing.get("dprice")
        if isinstance(dprice, list):
            for row in dprice:
                if not isinstance(row, dict):
                    continue
                lbl = str(row.get("label") or row.get("name") or "").lower()
                if "msrp" in lbl or row.get("type") == "msrp":
                    val = _coerce_float(row.get("value") or row.get("amount"))
                    if val is not None and val > 0:
                        return val
    return None


def _extract_dprice_enrichment(d: dict[str, Any]) -> tuple[list[str], float]:
    """Incentive lines and sum of explicit dealer discount rows from Dealer.com-style dprice."""
    incentive_labels: list[str] = []
    discount_sum = 0.0
    for pricing in _walk_pricing_dicts(d):
        dprice = pricing.get("dprice")
        if not isinstance(dprice, list):
            continue
        for row in dprice:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or row.get("name") or row.get("type") or "").strip()
            if not label:
                continue
            raw_val = row.get("value") if "value" in row else row.get("amount")
            val = _coerce_float(raw_val)
            ll = label.lower()
            if val is None:
                if any(k in ll for k in ("incentive", "rebate", "bonus", "credit", "allowance", "cash")):
                    incentive_labels.append(label)
                continue
            if any(
                k in ll
                for k in (
                    "dealer discount",
                    "dealer savings",
                    "dealer cash",
                    "discount",
                    "savings",
                    "price adjustment",
                    "reduction",
                )
            ):
                discount_sum += abs(val)
            elif any(k in ll for k in ("incentive", "rebate", "bonus", "credit", "allowance", "conquest", "loyalty")):
                incentive_labels.append(_format_price_label(label, val))
            elif row.get("isDeduction") or row.get("deduction"):
                discount_sum += abs(val)
    return incentive_labels, discount_sum


def _extract_feature_highlights(d: dict[str, Any], *, max_items: int = 12) -> list[str]:
    out: list[str] = []
    for key in (
        "highValueFeatures",
        "features",
        "packages",
        "includedPackages",
        "standardEquipment",
        "options",
        "factoryOptions",
        "equipment",
    ):
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            chunk = " ".join(v.split())
            if len(chunk) > 160:
                chunk = chunk[:157] + "…"
            out.append(chunk)
        elif isinstance(v, list):
            for item in v:
                if len(out) >= max_items:
                    return _dedupe_preserve_order(out)
                if isinstance(item, str) and item.strip():
                    text = " ".join(item.split())
                    if len(text) > 160:
                        text = text[:157] + "…"
                    out.append(text)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("label") or item.get("description") or item.get("code")
                    if name:
                        out.append(str(name).strip()[:160])
        if len(out) >= max_items:
            break
    return _dedupe_preserve_order(out)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        t = s.strip()
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def _parse_stock_date(raw: Any) -> str | None:
    if raw is None or raw is False:
        return None
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        if ts > 1e9:
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
            except (OSError, ValueError, OverflowError):
                return None
        return None
    s = str(raw).strip()
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        mo, da, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= da <= 31:
            return f"{yr:04d}-{mo:02d}-{da:02d}"
    m2 = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", s)
    if m2:
        yr, mo, da = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        if 1 <= mo <= 12 and 1 <= da <= 31:
            return f"{yr:04d}-{mo:02d}-{da:02d}"
    return None


def _extract_stock_date_and_days(d: dict[str, Any]) -> tuple[str | None, int | None]:
    explicit_days: int | None = None
    for key in ("daysOnLot", "days_on_lot", "daysInInventory", "ageInDays", "lotAge", "daysInStock"):
        di = _coerce_int(d.get(key))
        if di is not None and di >= 0:
            explicit_days = di
            break
    stock_raw = None
    for key in (
        "stockDate",
        "inventoryDate",
        "dateInStock",
        "inStockDate",
        "receivedDate",
        "inventoryAgeDate",
        "firstReceivedDate",
        "dateReceived",
    ):
        if d.get(key) not in (None, ""):
            stock_raw = d.get(key)
            break
    stock_iso = _parse_stock_date(stock_raw)
    days = explicit_days
    if days is None and stock_iso:
        try:
            y, mth, da = stock_iso.split("-")
            sd = date(int(y), int(mth), int(da))
            delta = (date.today() - sd).days
            if delta >= 0:
                days = delta
        except ValueError:
            pass
    return stock_iso, days


def _merge_pricing_enrichment(
    d: dict[str, Any],
    *,
    final_price: float | None,
) -> tuple[float | None, float | None, list[str]]:
    msrp = _extract_msrp_from_dict(d)
    incentive_labels, discount_from_rows = _extract_dprice_enrichment(d)
    dealer_discount = discount_from_rows if discount_from_rows > 0 else None
    if dealer_discount is None and msrp is not None and final_price is not None:
        gap = msrp - final_price
        if gap >= 50:
            dealer_discount = gap
    return msrp, dealer_discount, _dedupe_preserve_order(incentive_labels)


def _pick_price_from_pricelib(raw: Any) -> float | None:
    if not raw:
        return None
    try:
        decoded = base64.b64decode(str(raw)).decode("utf-8", errors="ignore")
    except Exception:
        return None
    candidates: list[float] = []
    for label in (
        "calc_FINAL PRICE",
        "calc_FINAL PRICE".lower(),
        "calc_INTERNET PRICE",
        "Internet Price",
        "A/Z Plan Price",
        "MSRP",
    ):
        m = re.search(rf"{re.escape(label)}:([0-9]+(?:\.[0-9]+)?)", decoded, re.I)
        if m:
            candidates.append(float(m.group(1)))
    return min(candidates) if candidates else None


def _pick_year(d: dict[str, Any]) -> int | None:
    y = (
        d.get("year")
        or d.get("vehicleModelDate")
        or d.get("modelYear")
        or d.get("itemYear")
        or d.get("vehicleYear")
        or d.get("yearValue")
    )
    return _coerce_int(y)


def _pick_inventory_location(d: dict[str, Any]) -> str | None:
    for key in (
        "location",
        "inventoryLocation",
        "dealerLocation",
        "locationName",
        "lotLocation",
        "storeName",
        "store",
        "accountName",
        "dealerName",
        "dealer_name",
        "owner",
        "cityState",
    ):
        value = d.get(key)
        if isinstance(value, list) and value:
            value = value[0]
        if isinstance(value, dict):
            value = (
                value.get("name")
                or value.get("text")
                or value.get("label")
                or value.get("value")
                or value.get("city")
            )
        if value:
            return str(value).strip()
    return None


def _pick_vehicle_condition(
    d: dict[str, Any],
    *,
    raw_title: str | None = None,
    listing_url: str | None = None,
    status_text: str | None = None,
) -> str | None:
    for key in (
        "vehicle_condition",
        "vehicleCondition",
        "condition",
        "newUsed",
        "new_used",
        "inventoryType",
        "inventory_type",
        "itemCondition",
        "usageStatus",
    ):
        normalized = normalize_vehicle_condition(d.get(key))
        if normalized:
            return normalized
    return (
        normalize_vehicle_condition(status_text)
        or normalize_vehicle_condition(raw_title)
        or normalize_vehicle_condition(listing_url)
    )


def _build_availability_status(
    *,
    status_text: str | None,
    is_in_stock: bool | None,
    is_in_transit: bool | None,
    is_offsite: bool | None,
    is_shared_inventory: bool | None,
) -> str | None:
    if is_in_transit:
        return "In transit"
    if is_offsite or is_shared_inventory:
        return "Transfer or shared inventory"
    if is_in_stock is True:
        return "On lot"
    if status_text:
        norm = status_text.strip().lower()
        if norm == "live":
            return "Listed online"
        return status_text
    return None


def _vehicle_merge_key(v: VehicleListing) -> str:
    if v.vehicle_identifier:
        return f"id:{v.vehicle_identifier}"
    if v.vin:
        return f"vin:{v.vin}"
    return f"{v.listing_url or ''}|{v.raw_title or ''}"


def _normalize_listing_for_category(v: VehicleListing, *, vehicle_category: str) -> VehicleListing:
    usage_value = v.usage_value
    usage_unit = v.usage_unit
    if usage_value is None and v.mileage is not None:
        usage_value = v.mileage
    if usage_unit is None and usage_value is not None:
        usage_unit = "miles"
    identifier = v.vehicle_identifier or v.vin or _pick_vehicle_identifier(
        {},
        vehicle_category=vehicle_category,
        fallback_text=v.raw_title,
    )
    return v.model_copy(
        update={
            "vehicle_category": vehicle_category or v.vehicle_category or "car",
            "usage_value": usage_value,
            "usage_unit": usage_unit,
            "vehicle_identifier": identifier,
        }
    )


def _prefer_vehicle_fields(existing: VehicleListing, incoming: VehicleListing) -> VehicleListing:
    merged = existing.model_dump()
    incoming_data = incoming.model_dump()
    for key, value in incoming_data.items():
        if value in (None, "", [], {}):
            continue
        current = merged.get(key)
        if current in (None, "", [], {}):
            merged[key] = value
            continue
        if key == "price":
            try:
                curr_num = float(current)
                inc_num = float(value)
            except Exception:
                continue
            if curr_num <= 0 < inc_num:
                merged[key] = value
        elif key == "mileage":
            try:
                curr_num = int(current)
                inc_num = int(value)
            except Exception:
                continue
            if curr_num <= 1 < inc_num:
                merged[key] = value
        elif key in ("incentive_labels", "feature_highlights"):
            merged[key] = _dedupe_preserve_order(list(current or []) + list(value or []))[
                :24
            ]
        elif key == "days_on_lot":
            try:
                ci = int(current) if current is not None else None
                vi = int(value) if value is not None else None
            except Exception:
                continue
            if vi is None:
                continue
            if ci is None or vi > ci:
                merged[key] = value
        elif key == "dealer_discount":
            try:
                cc = float(current) if current is not None else 0.0
                iv = float(value) if value is not None else 0.0
            except Exception:
                continue
            if iv > cc:
                merged[key] = value
        elif key == "msrp":
            try:
                cc = float(current) if current is not None else None
                iv = float(value) if value is not None else None
            except Exception:
                continue
            if iv is None:
                continue
            if cc is None or iv > cc:
                merged[key] = value
        else:
            if len(str(value)) > len(str(current)):
                merged[key] = value
    return VehicleListing(**merged)


def dict_to_vehicle_listing(
    d: dict[str, Any],
    base_url: str,
    *,
    vehicle_category: str = "car",
) -> VehicleListing | None:
    """Map a loose inventory/schema dict to VehicleListing; returns None if not vehicle-like."""
    make = (
        d.get("make")
        or d.get("manufacturer")
        or d.get("brand")
        or d.get("manuf")
        or d.get("itemMake")
        or d.get("vehicleMake")
        or d.get("makeName")
    )
    model = d.get("model") or d.get("itemModel") or d.get("vehicleModel") or d.get("modelName")
    vin = d.get("vin") or d.get("vehicleIdentificationNumber") or d.get("vehicle_identification_number")
    if isinstance(make, dict):
        make = make.get("name")
    if isinstance(model, dict):
        model = model.get("name")
    title_hint = d.get("title") or d.get("name") or d.get("vehicleTitle") or d.get("item")
    if isinstance(title_hint, list):
        raw_title = " ".join(str(x).strip() for x in title_hint if str(x).strip()) or None
    else:
        raw_title = str(title_hint).strip() if title_hint else None
    title_fields = _parse_title_fields(raw_title)
    make_s = str(make).strip() if make else (str(title_fields.get("make")).strip() if title_fields.get("make") else None)
    model_s = str(model).strip() if model else (str(title_fields.get("model")).strip() if title_fields.get("model") else None)
    normalized_category = (vehicle_category or "car").strip().lower() or "car"
    identifier_s = _pick_vehicle_identifier(
        d,
        vehicle_category=normalized_category,
        fallback_text=raw_title,
    )
    vin_s = _normalize_vehicle_identifier(vin, vehicle_category="car") if vin else None
    if not make_s and not model_s and not identifier_s:
        return None
    if not make_s and not model_s:
        # Identifier-only without any title context is too weak for display.
        if not raw_title:
            return None

    vdp = (
        d.get("vdpUrl")
        or d.get("vdp_url")
        or d.get("listing_url")
        or d.get("url")
        or d.get("itemUrl")
        or d.get("sameAs")
        or d.get("link")
        or d.get("detailUrl")
        or d.get("vehicleUrl")
        or d.get("vdpPath")
    )
    listing_url = None
    if isinstance(vdp, list) and vdp:
        vdp = vdp[0]
    if vdp:
        listing_url = urljoin(base_url, str(vdp).replace("\\/", "/"))

    images_value = d.get("images")
    first_gallery_image = images_value[0] if isinstance(images_value, list) and images_value else None
    img = (
        d.get("image_url")
        or d.get("imageUrl")
        or d.get("image")
        or first_gallery_image
        or d.get("itemThumbNailUrl")
        or d.get("primaryImageUrl")
        or d.get("sharePhoto")
    )
    if isinstance(img, list) and img:
        img = img[0]
    if isinstance(img, dict):
        img = img.get("url") or img.get("contentUrl") or img.get("uri") or img.get("src")
    image_url = urljoin(base_url, str(img).replace("\\/", "/")) if img else None

    trim = d.get("trim")
    if isinstance(trim, dict):
        trim = trim.get("name")
    trim_s = str(trim).strip() if trim else None
    inventory_location = _pick_inventory_location(d)
    body_style = (
        d.get("bodyStyle")
        or d.get("bodytype")
        or d.get("bodyType")
        or d.get("bodystyle")
        or d.get("itemType")
        or d.get("itemSubtype")
    )
    if isinstance(body_style, dict):
        body_style = body_style.get("name")
    body_style_s = str(body_style).strip() if body_style else None
    exterior_color = (
        d.get("colorExterior")
        or d.get("exteriorColor")
        or d.get("extColorName")
        or d.get("extColor")
        or d.get("exterior_color")
        or d.get("ext_color")
        or d.get("colorName")
        or d.get("color")
    )
    if isinstance(exterior_color, dict):
        exterior_color = (
            exterior_color.get("name")
            or exterior_color.get("text")
            or exterior_color.get("label")
            or exterior_color.get("value")
        )
    exterior_color_s = str(exterior_color).strip() if exterior_color else None
    status_text = (
        d.get("status")
        or d.get("availabilityStatus")
        or d.get("availability")
        or d.get("inventoryStatus")
        or d.get("stockStatus")
        or d.get("vehicleStatus")
    )
    if isinstance(status_text, list) and status_text:
        status_text = status_text[0]
    if isinstance(status_text, dict):
        status_text = (
            status_text.get("name")
            or status_text.get("status")
            or status_text.get("text")
            or status_text.get("label")
        )
    status_text_norm = str(status_text).strip().lower() if status_text else ""
    if status_text:
        status_text = str(status_text).replace("_", " ").strip().title()
    is_offsite = _coerce_bool(
        d.get("offSite") or d.get("offsite") or d.get("isOffsite") or d.get("is_offsite")
    )
    is_shared_inventory = _coerce_bool(
        d.get("sharedVehicle") or d.get("shared_inventory") or d.get("isSharedInventory")
    )
    is_in_transit = _coerce_bool(
        d.get("inTransit") or d.get("in_transit") or d.get("isInTransit")
    )
    is_in_stock = _coerce_bool(
        d.get("inStock") or d.get("in_stock") or d.get("isInStock")
    )
    if is_in_transit is None and any(token in status_text_norm for token in ("in transit", "arriving", "en route")):
        is_in_transit = True
    if is_offsite is None and any(
        token in status_text_norm
        for token in ("off site", "off-site", "dealer trade", "transfer", "shared")
    ):
        is_offsite = True
    if is_in_stock is None and any(token in status_text_norm for token in ("in stock", "on lot", "available")):
        is_in_stock = True

    if not raw_title:
        title_parts = [str(x) for x in [_pick_year(d), make_s, model_s, trim_s] if x]
        raw_title = " ".join(title_parts) if title_parts else None
    vehicle_condition = _pick_vehicle_condition(
        d,
        raw_title=raw_title,
        listing_url=listing_url,
        status_text=str(status_text) if status_text else None,
    )

    final_price = _pick_price_from_dict(d)
    msrp, dealer_discount, incentive_labels = _merge_pricing_enrichment(d, final_price=final_price)
    features = _extract_feature_highlights(d)
    stock_date, days_on_lot = _extract_stock_date_and_days(d)
    usage_value, usage_unit = _pick_usage_from_dict(
        d,
        vehicle_category=normalized_category,
        fallback_text=raw_title,
    )

    return VehicleListing(
        vehicle_category=normalized_category,
        year=_pick_year(d) or _coerce_int(title_fields.get("year")),
        make=make_s,
        model=model_s,
        trim=trim_s or (str(title_fields.get("trim")).strip() if title_fields.get("trim") else None),
        body_style=body_style_s,
        exterior_color=exterior_color_s,
        price=final_price,
        mileage=usage_value if usage_unit == "miles" else None,
        usage_value=usage_value,
        usage_unit=usage_unit,
        vehicle_condition=vehicle_condition,
        vin=vin_s,
        vehicle_identifier=identifier_s or vin_s,
        image_url=image_url,
        listing_url=listing_url,
        raw_title=raw_title,
        inventory_location=inventory_location,
        availability_status=_build_availability_status(
            status_text=str(status_text) if status_text else None,
            is_in_stock=is_in_stock,
            is_in_transit=is_in_transit,
            is_offsite=is_offsite,
            is_shared_inventory=is_shared_inventory,
        ),
        is_offsite=is_offsite,
        is_in_transit=is_in_transit,
        is_in_stock=is_in_stock,
        is_shared_inventory=is_shared_inventory,
        msrp=msrp,
        dealer_discount=dealer_discount,
        incentive_labels=incentive_labels,
        feature_highlights=features,
        stock_date=stock_date,
        days_on_lot=days_on_lot,
    )


def _vehicle_record_key(d: dict[str, Any]) -> str:
    vehicle_category = str(d.get("vehicle_category") or "car").strip().lower() or "car"
    identifier = _pick_vehicle_identifier(d, vehicle_category=vehicle_category)
    vin = str(d.get("vin") or d.get("vehicleIdentificationNumber") or "").strip()
    url = str(
        d.get("vdpUrl")
        or d.get("vdp_url")
        or d.get("url")
        or d.get("listing_url")
        or d.get("itemUrl")
        or ""
    ).strip()
    if identifier:
        return f"id:{identifier}"
    if vin:
        return f"vin:{vin}"
    return url


def collect_structured_vehicle_dicts(html: str, page_url: str) -> list[dict[str, Any]]:
    """Merge generic embedded JSON inventory with platform-specific JSON-LD vehicles."""
    soup = BeautifulSoup(html, "lxml")
    generic = _extract_json_inventory(html, soup)
    merged: list[dict[str, Any]] = []
    by_key: dict[str, int] = {}
    for r in generic:
        k = _vehicle_record_key(r)
        if k not in by_key:
            by_key[k] = len(merged)
            merged.append(r)
        else:
            idx = by_key[k]
            merged[idx] = _merge_vehicle_dicts(merged[idx], r)
    extra = provider_enriched_vehicle_dicts(html, page_url)
    if extra:
        for d in extra:
            nd = _normalize_schema_org(d)
            k = _vehicle_record_key(nd)
            if nd.get("make") or nd.get("model") or nd.get("vehicleIdentificationNumber"):
                if k not in by_key:
                    by_key[k] = len(merged)
                    merged.append(nd)
                else:
                    idx = by_key[k]
                    merged[idx] = _merge_vehicle_dicts(merged[idx], nd)
    return merged


def _page_looks_like_inventory_results(page_url: str, html: str) -> bool:
    lower_url = (page_url or "").lower()
    if any(
        token in lower_url
        for token in (
            "/inventory",
            "/search/inventory",
            "searchnew",
            "searchused",
            "--inventory",
            "page=xallinventory",
            "page=xnewinventory",
            "page=xpreownedinventory",
            "all-inventory",
            "new-inventory",
            "used-inventory",
        )
    ):
        return True
    lower_html = (html or "").lower()
    if re.search(r"\b\d{1,5}\s*(?:-|to|–|—)\s*\d{1,5}\s+of\s+\d{1,7}\s+results?\b", lower_html):
        return True
    return "search inventory" in lower_html and "sort by" in lower_html and "results" in lower_html


def _text_or_none(node: Any) -> str | None:
    if not node:
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def _first_srcset_candidate(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    first = raw.split(",", 1)[0].strip()
    if not first:
        return None
    return first.split()[0].strip() or None


def _normalize_dom_image_candidate(raw: str | None) -> str | None:
    src = (raw or "").strip().strip("'\"")
    if not src:
        return None
    lower = src.lower()
    if lower.startswith("data:image/"):
        return None
    if lower.endswith(".svg") or "copy.svg" in lower or "icon" in lower:
        return None
    return src


def _pick_dom_vehicle_image(card: Any, page_url: str) -> str | None:
    # Dealer Spike: hero image on div[role=img] via background-image, no <img> in modern browsers
    for node in card.select(".image-container-image[role=img], .image-container-image"):
        style = (node.get("style") or "").strip()
        bg_match = re.search(r"""background-image\s*:\s*url\((['"]?)(.*?)\1\)""", style, re.I)
        if bg_match:
            src = _normalize_dom_image_candidate(bg_match.group(2).strip())
            if src:
                return urljoin(page_url, src)
    preferred_selectors = (
        ".hero-carousel__background-image--grid",
        ".hero-carousel__background-image--list",
        ".boat-image-container",
        ".itemImage img",
        ".vehicle__image[data-src]",
        ".image",
        "img[data-src]",
        "img[data-lazy-src]",
        ".vehicle-image img",
        "img",
        "noscript img",
    )
    for selector in preferred_selectors:
        for img in card.select(selector):
            candidates: list[str | None] = [
                img.get("data-src"),
                img.get("data-lazy-src"),
                _first_srcset_candidate(img.get("data-srcset")),
                _first_srcset_candidate(img.get("srcset")),
                img.get("data-original"),
                img.get("data-lazy"),
                img.get("src"),
            ]
            raw_bg = (img.get("data-dsp-small-image") or "").strip()
            if raw_bg.startswith("url(") and raw_bg.endswith(")"):
                candidates.append(raw_bg[4:-1].strip().strip("'\""))
            style = (img.get("style") or "").strip()
            bg_match = re.search(r"""background-image\s*:\s*url\((['"]?)(.*?)\1\)""", style, re.I)
            if bg_match:
                candidates.append(bg_match.group(2).strip())

            for candidate in candidates:
                src = _normalize_dom_image_candidate(candidate)
                if not src:
                    continue
                if "|" in src:
                    src = src.split("|", 1)[0].strip()
                src = _normalize_dom_image_candidate(src)
                if src:
                    return urljoin(page_url, src)
    return None


def _parse_dom_vehicle_payload(card: Any) -> dict[str, Any]:
    raw = card.get("data-vehicle")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_search_result_card_vehicles(
    html: str,
    page_url: str,
    *,
    vehicle_category: str = "car",
) -> list[VehicleListing]:
    soup = BeautifulSoup(html, "lxml")
    vehicles: list[VehicleListing] = []
    seen: set[str] = set()

    for anchor in soup.select('a.car[href*="/detail/"], a.c-widget--vehicle'):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        listing_url = urljoin(page_url, href)
        card_text = anchor.get_text(" ", strip=True)
        if not card_text:
            continue

        hyundai_title_match = _HYUNDAI_SEARCH_TITLE_RE.match(card_text)
        if hyundai_title_match:
            title_part = " ".join(
                x.strip()
                for x in (
                    hyundai_title_match.group("year"),
                    hyundai_title_match.group("make"),
                    hyundai_title_match.group("model"),
                    hyundai_title_match.group("trim"),
                )
                if x and x.strip()
            )
        else:
            title_part = re.split(
                r"\s+(?:Save:|MSRP|Retail|Price)\b",
                card_text,
                maxsplit=1,
                flags=re.I,
            )[0].strip()
        title_fields = _parse_title_fields(title_part)
        raw_title = title_fields.get("raw_title") or title_part or None
        usage_value, usage_unit = _pick_usage_from_dict(
            {},
            vehicle_category=vehicle_category,
            fallback_text=card_text,
        )
        vin = _extract_vin_from_text(card_text)
        vehicle_identifier = _pick_vehicle_identifier(
            {"vin": vin},
            vehicle_category=vehicle_category,
            fallback_text=card_text,
        )
        price = None
        price_match = _SAVE_PRICE_MSRP_RE.search(card_text)
        if price_match:
            price = _coerce_float(price_match.group("price"))
        if price is None:
            price = _extract_price_from_text(card_text)

        image_url = None
        img = anchor.select_one("img[src]")
        if img and img.get("src"):
            image_url = urljoin(page_url, str(img.get("src")))

        vehicle = VehicleListing(
            vehicle_category=vehicle_category,
            year=_coerce_int(title_fields.get("year")),
            make=str(title_fields.get("make")).strip() if title_fields.get("make") else None,
            model=str(title_fields.get("model")).strip() if title_fields.get("model") else None,
            trim=str(title_fields.get("trim")).strip() if title_fields.get("trim") else None,
            price=price,
            mileage=usage_value if usage_unit == "miles" else None,
            usage_value=usage_value,
            usage_unit=usage_unit,
            vehicle_condition=normalize_vehicle_condition(raw_title) or normalize_vehicle_condition(listing_url),
            vin=vin,
            vehicle_identifier=vehicle_identifier or vin,
            image_url=image_url,
            listing_url=listing_url,
            raw_title=raw_title,
        )
        key = _vehicle_merge_key(vehicle)
        if key in seen:
            continue
        seen.add(key)
        if any([vehicle.make, vehicle.model, vehicle.vin, vehicle.raw_title]):
            vehicles.append(vehicle)

    return vehicles


def _canonical_inventory_detail_url(page_url: str, href: str) -> str | None:
    abs_url = urljoin(page_url, (href or "").strip())
    parts = urlsplit(abs_url)
    path = parts.path.lower()
    if not _INVENTORY_DETAIL_PATH_RE.search(path):
        return None
    if "/form/" in path:
        return None
    query_keys = {k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)}
    if query_keys.intersection({"video", "photo"}):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _extract_inventory_anchor_card_vehicles(
    html: str,
    page_url: str,
    *,
    vehicle_category: str = "car",
) -> list[VehicleListing]:
    lower_url = (page_url or "").lower()
    lower_html = (html or "").lower()
    # Keep this fallback scoped to SRP-like pages so homepage featured inventory
    # does not masquerade as the full inventory set.
    if "/inventory" not in lower_url and "showing 1 -" not in lower_html and "results" not in lower_html:
        return []

    soup = BeautifulSoup(html, "lxml")
    vehicles: list[VehicleListing] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        listing_url = _canonical_inventory_detail_url(page_url, str(anchor.get("href") or ""))
        if not listing_url or listing_url in seen_urls:
            continue

        container = None
        for parent in anchor.parents:
            if getattr(parent, "name", None) not in {"article", "li", "div", "section"}:
                continue
            card_text = parent.get_text(" ", strip=True)
            if len(card_text) < 60 or len(card_text) > 2500:
                continue
            lower_text = card_text.lower()
            if not re.search(r"\b(?:19|20)\d{2}\b", card_text):
                continue
            if not any(token in lower_text for token in ("more info", "click for price", "$", " mi ", " mileage", " stock")):
                continue
            container = parent
            break

        if container is None:
            continue

        card_text = container.get_text(" ", strip=True)
        raw_title = _text_or_none(container.select_one("h1, h2, h3, h4, h5, h6"))
        if raw_title and raw_title.strip().lower() in _GENERIC_CARD_ACTION_TEXTS:
            raw_title = None
        if not raw_title:
            card_text_prefix = re.split(r"\b(?:CLICK FOR PRICE|MORE INFO)\b", card_text, maxsplit=1, flags=re.I)[0].strip()
            raw_title = card_text_prefix or None

        title_fields = _parse_title_fields(raw_title or card_text)
        raw_title = title_fields.get("raw_title") or raw_title
        if not any((title_fields.get("year"), title_fields.get("make"), title_fields.get("model"))):
            continue

        usage_value, usage_unit = _pick_usage_from_dict(
            {},
            vehicle_category=vehicle_category,
            fallback_text=card_text,
        )
        stock_match = _TEXT_STOCK_RE.search(card_text)
        stock_value = stock_match.group(1) if stock_match else None
        image_url = _pick_dom_vehicle_image(container, page_url)
        card_prices = [
            price
            for price in (_coerce_float(match.group(0)) for match in _TEXT_PRICE_RE.finditer(card_text))
            if price and price > 500
        ]
        current_price = min(card_prices) if card_prices else None
        msrp_price = max(card_prices) if len(card_prices) >= 2 else None

        vehicle = VehicleListing(
            vehicle_category=vehicle_category,
            year=_coerce_int(title_fields.get("year")),
            make=str(title_fields.get("make")).strip() if title_fields.get("make") else None,
            model=str(title_fields.get("model")).strip() if title_fields.get("model") else None,
            trim=str(title_fields.get("trim")).strip() if title_fields.get("trim") else None,
            price=current_price or _extract_price_from_text(card_text),
            mileage=usage_value if usage_unit == "miles" else None,
            usage_value=usage_value,
            usage_unit=usage_unit,
            vehicle_condition=normalize_vehicle_condition(raw_title) or normalize_vehicle_condition(card_text) or normalize_vehicle_condition(listing_url),
            vehicle_identifier=stock_value,
            image_url=image_url,
            listing_url=listing_url,
            raw_title=str(raw_title).strip() if raw_title else None,
            msrp=msrp_price if msrp_price and current_price and msrp_price - current_price >= 50 else None,
            dealer_discount=(msrp_price - current_price) if msrp_price and current_price and msrp_price - current_price >= 50 else None,
        )
        if not any([vehicle.make, vehicle.model, vehicle.raw_title]):
            continue
        seen_urls.add(listing_url)
        vehicles.append(vehicle)

    return vehicles


def extract_dom_vehicle_cards(
    html: str,
    page_url: str,
    *,
    vehicle_category: str = "car",
    model_filter: str = "",
) -> list[VehicleListing]:
    """
    Pull listings from rendered SRP cards, primarily for DealerOn-style pages that
    expose data-* attrs after JS render but little/no embedded JSON.
    """
    soup = BeautifulSoup(html, "lxml")
    vehicles: list[VehicleListing] = []
    seen: set[str] = set()
    inventory_context = _page_looks_like_inventory_results(page_url, html)

    selectors = (
        ".vehicle-card",
        ".inventory-card",
        ".inventoryList-bike",
        "li.featuredVehicle",
        ".result-wrap.new-vehicle",
        ".new-vehicle[data-vehicle]",
        ".brandInventoryCard",
        ".hit",
        ".sbiGrid .item",
        ".inventory-model-single",
        ".unit-row",
        ".inv-card",
        ".v7list-results__item",
        ".v7list-vehicle",
        ".si-vehicle-box",
        ".carbox",
        ".mmx-boat-card",
        ".inventory-vehicle-block",
        ".vehicle-box",
        ".vehicle-specials",
        "[data-vehicle-vin]",
        "li[data-unit-id]",
        "li[data-unit-condition]",
        ".c-widget--vehicle",
        "li[data-component='result-tile']",
        "[data-component='result-tile']",
    )
    for card in soup.select(", ".join(selectors)):
        classes = set(card.get("class") or [])
        classes_lower = {str(cls).lower() for cls in classes}
        if "skeleton" in classes_lower:
            continue
        if "featuredvehicle" in classes_lower and model_filter.strip() and not inventory_context:
            continue

        payload = _parse_dom_vehicle_payload(card)
        card_text = card.get_text(" ", strip=True)
        tv_title = " ".join(
            part
            for part in (
                _text_or_none(card.select_one(".vehicle-heading__year")),
                _text_or_none(card.select_one(".vehicle-heading__name")),
                _text_or_none(card.select_one(".vehicle-heading__model")),
            )
            if part
        ).strip()
        tv_condition = _text_or_none(card.select_one(".vehicle-specs__item--condition .vehicle-specs__value"))
        tv_location = _text_or_none(card.select_one(".vehicle-specs__item--location .vehicle-specs__value"))
        tv_stock = _text_or_none(card.select_one(".vehicle-specs__item--stock-number .vehicle-specs__value"))
        tv_vin = _text_or_none(card.select_one(".vehicle-specs__item--vin .vehicle-specs__value"))
        tv_mileage = (
            _text_or_none(card.select_one(".vehicle-specs__item--mileage .vehicle-specs__value"))
            or _text_or_none(card.select_one(".vehicle-specs__item--odometer .vehicle-specs__value"))
            or _text_or_none(card.select_one(".vehicle-specs__item--miles .vehicle-specs__value"))
        )
        room58_vin = card.select_one(".mm-wmbp-button[vin]")
        room58_stock = _text_or_none(card.select_one(".inventoryModel-keyDetails-item-description[aria-label='Stock number']"))
        room58_color = _text_or_none(card.select_one(".inventoryModel-keyDetails-item-description[aria-label='Color']"))
        tv_current_price = _text_or_none(card.select_one(".vehicle-price--current .vehicle-price__price"))
        tv_old_price = _text_or_none(card.select_one(".vehicle-price--old .vehicle-price__price"))
        tv_savings = _text_or_none(card.select_one(".vehicle-price--savings .vehicle-price__price"))
        basspro_title = _text_or_none(card.select_one(".mname"))
        basspro_condition = _text_or_none(card.select_one(".condition"))
        basspro_location = _text_or_none(card.select_one(".locname"))
        basspro_price = _text_or_none(card.select_one(".price"))
        onewater_title = " ".join(
            part
            for part in (
                _text_or_none(card.select_one(".yearMake")),
                _text_or_none(card.select_one(".model")),
            )
            if part
        ).strip()
        onewater_condition = _text_or_none(card.select_one(".lastInfo .condition")) or _text_or_none(card.select_one(".lIRight .condition"))
        onewater_location = _text_or_none(card.select_one(".dealer"))
        onewater_stock = _text_or_none(card.select_one(".itemNumber"))
        onewater_price = _text_or_none(card.select_one(".priceBlock .price"))
        marinemax_title = _text_or_none(card.select_one(".title"))
        marinemax_condition_meta = _text_or_none(card.select_one(".condition-and-type"))
        marinemax_stock = _text_or_none(card.select_one(".stock-number"))
        if marinemax_stock:
            marinemax_stock = marinemax_stock.replace("#", " ").strip()
        marinemax_price = _text_or_none(card.select_one(".current-price"))
        marinemax_old_price = _text_or_none(card.select_one(".old-price"))
        temptation_make = _text_or_none(card.select_one(".boat-make h5"))
        temptation_model = _text_or_none(card.select_one(".boat-make h5 span"))
        temptation_price = _text_or_none(card.select_one(".main-boat-price"))
        temptation_location = _text_or_none(card.select_one(".boat-location"))
        temptation_status = _text_or_none(card.select_one(".listing-title"))
        colony_title = _text_or_none(card.select_one("h2"))
        colony_details: dict[str, str] = {}
        for detail in card.select(".hit-content .flex.divide-x > div"):
            spans = detail.select("span")
            if len(spans) < 2:
                continue
            label = _text_or_none(spans[0])
            value = _text_or_none(spans[-1])
            if label and value:
                colony_details[label.strip().lower().rstrip(":")] = value.strip()
        wilson_title = _text_or_none(card.select_one(".unit-name-vlp"))
        wilson_status = _text_or_none(card.select_one(".unit-status"))
        wilson_price = _text_or_none(card.select_one(".unit-sale"))
        wilson_specs: dict[str, str] = {}
        for row in card.select(".vlp-spec-row .d-flex"):
            columns = [text.strip() for text in row.stripped_strings if text and text.strip()]
            if len(columns) >= 2:
                wilson_specs[columns[0].strip().lower().rstrip(":")] = columns[-1].strip()
        gp_title = _text_or_none(card.select_one(".inv-content h3")) or _text_or_none(card.select_one("h3"))
        gp_stock = _text_or_none(card.select_one(".inv-stock"))
        gp_price = _text_or_none(card.select_one(".inv-price"))
        gp_location = _text_or_none(card.select_one(".inv-location"))
        # Dealer Spike homepage / SRP featured tiles (e.g. Club Royale)
        ds_spike_price_raw = _text_or_none(card.select_one("li.featuredVehicleAttr.price span.value"))
        ds_spike_make = _text_or_none(card.select_one("li.featuredVehicleAttr.manuf span.value"))
        ds_spike_model = _text_or_none(card.select_one("li.featuredVehicleAttr.model span.value"))
        ds_spike_year = _coerce_int(_text_or_none(card.select_one("li.featuredVehicleAttr.year span.value")))
        ds_spike_stock = _text_or_none(card.select_one("li.featuredVehicleAttr.stockno span.value"))
        ds_spike_price = _coerce_float(ds_spike_price_raw.replace("$", "").replace(",", "")) if ds_spike_price_raw else None
        vin = (
            card.get("data-vin")
            or card.get("data-vehicle-vin")
            or card.get("data-dotagging-item-id")
            or card.get("data-boat-hin")
            or payload.get("vin")
            or (room58_vin.get("vin") if room58_vin is not None else None)
            or tv_vin
            or _extract_vin_from_text(card_text)
        )
        make = (
            card.get("data-make")
            or card.get("data-vehicle-make")
            or card.get("data-dotagging-item-make")
            or card.get("data-unit-make")
            or card.get("data-boat-make")
            or colony_details.get("manufacturer")
            or payload.get("make")
            or ds_spike_make
        )
        model = (
            card.get("data-model")
            or card.get("data-vehicle-model-name")
            or card.get("data-dotagging-item-model")
            or card.get("data-boat-model")
            or payload.get("model")
            or ds_spike_model
        )
        year = _coerce_int(
            card.get("data-year")
            or card.get("data-vehicle-model-year")
            or card.get("data-dotagging-item-year")
            or card.get("data-unit-year")
            or card.get("data-boat-year")
            or payload.get("year")
            or ds_spike_year
        )
        trim = card.get("data-trim") or card.get("data-vehicle-trim") or card.get("data-dotagging-item-variant") or payload.get("trim")
        odom_merge: dict[str, Any] = dict(payload)
        for attr, pkey in (
            ("data-odometer", "mileage"),
            ("data-mileage", "mileage"),
            ("data-vehicle-mileage", "mileage"),
            ("data-miles", "miles"),
            ("data-odometer-miles", "odometerMiles"),
            ("data-dotagging-item-odometer", "odometer"),
        ):
            val = card.get(attr)
            if val not in (None, ""):
                odom_merge[pkey] = val
        if tv_mileage:
            odom_merge["mileage"] = tv_mileage
        usage_value, usage_unit = _pick_usage_from_dict(
            odom_merge,
            vehicle_category=vehicle_category,
            fallback_text=card_text,
        )
        msrp_attr = _coerce_float(
            card.get("data-msrp")
            or card.get("data-list-price")
            or card.get("data-retail-price")
            or payload.get("msrp")
            or tv_old_price
            or marinemax_old_price
        )
        price = _coerce_float(
            card.get("data-price")
            or card.get("data-vehicle-price")
            or card.get("data-dotagging-item-price")
            or payload.get("price")
            or payload.get("internetPrice")
            or payload.get("salePrice")
            or tv_current_price
            or basspro_price
            or onewater_price
            or marinemax_price
            or temptation_price
            or wilson_price
            or gp_price
            or ds_spike_price
        )
        if price in (None, 0.0):
            price = _pick_price_from_pricelib(card.get("data-pricelib")) or price
        if price in (None, 0.0) and msrp_attr:
            price = msrp_attr
        card_msrp: float | None = None
        dealer_disc: float | None = None
        if msrp_attr and price and msrp_attr - price >= 50:
            card_msrp = msrp_attr
            dealer_disc = msrp_attr - price
        if dealer_disc in (None, 0.0):
            tv_savings_value = _coerce_float(tv_savings)
            if tv_savings_value and tv_savings_value > 0:
                dealer_disc = tv_savings_value
        save_match = _SAVE_PRICE_MSRP_RE.search(card_text or "")
        if save_match:
            sm_price = _coerce_float(save_match.group("price"))
            sm_msrp = _coerce_float(save_match.group("msrp"))
            if sm_msrp and sm_price and sm_msrp > sm_price:
                card_msrp = card_msrp or sm_msrp
                if price in (None, 0.0):
                    price = sm_price
                dealer_disc = dealer_disc or max(0.0, sm_msrp - (price or sm_price))
        pl = payload or {}
        payload_features = _extract_feature_highlights(pl, max_items=8)
        dom_days = _coerce_int(card.get("data-days-on-lot") or pl.get("daysOnLot"))
        dom_stock_payload = dict(pl)
        if card.get("data-stock-date"):
            dom_stock_payload.setdefault("stockDate", card.get("data-stock-date"))
        stock_dom, days_dom = _extract_stock_date_and_days(dom_stock_payload)
        if dom_days is not None:
            days_dom = dom_days
        is_in_stock = _coerce_bool(
            card.get("data-instock")
            or card.get("data-in-stock")
            or card.get("data-is-in-stock")
        )
        is_in_transit = _coerce_bool(
            card.get("data-intransit")
            or card.get("data-in-transit")
            or card.get("data-is-in-transit")
        )
        inventory_location = (
            card.get("data-dotagging-item-location")
            or card.get("data-location")
            or card.get("data-inventory-location")
            or card.get("data-dealer-location")
            or payload.get("inventoryLocation")
            or payload.get("dealerLocation")
            or payload.get("location")
        )
        if isinstance(inventory_location, dict):
            inventory_location = (
                inventory_location.get("name")
                or inventory_location.get("text")
                or inventory_location.get("label")
            )
        exterior_color = (
            card.get("data-exterior-color")
            or card.get("data-exteriorcolor")
            or card.get("data-color-exterior")
            or card.get("data-dotagging-item-color")
            or payload.get("colorExterior")
            or payload.get("exteriorColor")
            or payload.get("extColorName")
            or payload.get("extColor")
            or payload.get("color")
            or room58_color
        )
        if isinstance(exterior_color, dict):
            exterior_color = (
                exterior_color.get("name")
                or exterior_color.get("text")
                or exterior_color.get("label")
                or exterior_color.get("value")
            )
        card_status_text = (
            _text_or_none(card.select_one(".promotionBannerText"))
            or temptation_status
            or wilson_status
            or _text_or_none(card.select_one(".fearuredCardLocation span:last-child"))
            or card.get("data-status")
            or card.get("data-availability")
            or payload.get("status")
            or payload.get("availabilityStatus")
            or payload.get("availability")
        )
        if isinstance(card_status_text, dict):
            card_status_text = (
                card_status_text.get("name")
                or card_status_text.get("status")
                or card_status_text.get("text")
                or card_status_text.get("label")
            )
        if card_status_text not in (None, ""):
            card_status_text = str(card_status_text).strip()
        status_hint = str(card_status_text or card_text or "").lower()
        if is_in_transit is None and any(token in status_hint for token in ("in transit", "arriving", "en route")):
            is_in_transit = True
        if is_in_stock is None and any(token in status_hint for token in ("in stock", "on lot", "available")):
            is_in_stock = True
        availability_status = _build_availability_status(
            status_text=card_status_text,
            is_in_stock=is_in_stock,
            is_in_transit=is_in_transit,
            is_offsite=False,
            is_shared_inventory=False,
        )

        anchor = card if getattr(card, "name", None) == "a" else card.select_one("a[href]")
        listing_url = urljoin(page_url, anchor["href"]) if anchor and anchor.get("href") else None
        if (
            model_filter.strip()
            and listing_url
            and "xinventorydetail" in listing_url.lower()
            and not inventory_context
        ):
            continue

        image_url = _pick_dom_vehicle_image(card, page_url)

        payload_title = " ".join(
            str(x).strip()
            for x in (payload.get("year"), payload.get("make"), payload.get("model"), payload.get("trim"))
            if x not in (None, "") and str(x).strip()
        )
        raw_title = (
            card.get("data-name")
            or basspro_title
            or onewater_title
            or marinemax_title
            or _text_or_none(card.select_one(".inventoryList-bike-details-title > a"))
            or _text_or_none(card.select_one(".vehicle-heading__link"))
            or _text_or_none(card.select_one(".featuredCardHeading"))
            or colony_title
            or (
                " ".join(
                    part
                    for part in [card.get("data-boat-year"), card.get("data-boat-make"), card.get("data-boat-model")]
                    if part
                )
                or None
            )
            or wilson_title
            or gp_title
            or tv_title
            or _text_or_none(card.select_one(".vehicle-card__title"))
            or _text_or_none(card.select_one(".vehicleTitle"))
            or _text_or_none(card.select_one(".hit-title"))
            or _text_or_none(card.select_one(".hit-title a"))
            or _text_or_none(card.select_one(".srp-vehicle-title"))
            or _text_or_none(card.select_one(".vehicle-title"))
            or payload_title
            or payload.get("title")
            or payload.get("name")
            or card.get("title")
            or card.get("aria-label")
        )
        if not raw_title and card_text:
            raw_title = re.split(
                r"\b(?:MSRP|Your\s+Price|Details|Disclosure|Exterior:|Interior:|Engine:|Transmission:|vin:|Stock:|Finance\s+for|Lease\s+for)\b|\$|Starting\s+at",
                card_text,
                maxsplit=1,
                flags=re.I,
            )[0].strip()
            raw_title = re.sub(
                r"^(?:Finance\s+a\s+|Lease\s+a\s+|Buy\s+a\s+|New\s+|Used\s+|Certified\s+Pre-Owned\s+|CPO\s+|\d+\s+Available\s+)+",
                "",
                raw_title,
                flags=re.I,
            ).strip()
        title_fields = _parse_title_fields(raw_title or card_text)
        if not raw_title:
            raw_title = title_fields.get("raw_title")
        if not make:
            make = title_fields.get("make")
        if not model:
            model = title_fields.get("model")
        if not make and temptation_make:
            make = temptation_make
        if not model and temptation_model:
            model = temptation_model
        if year is None:
            year = _coerce_int(title_fields.get("year"))
        if not trim:
            trim = title_fields.get("trim")
        if price in (None, 0.0):
            price = _extract_price_from_text(card_text) or price
        if usage_value is None:
            usage_value, usage_unit = _pick_usage_from_dict(
                {},
                vehicle_category=vehicle_category,
                fallback_text=card_text,
            )
        vehicle_condition = (
            normalize_vehicle_condition(card.get("data-condition"))
            or normalize_vehicle_condition(card.get("data-newused"))
            or normalize_vehicle_condition(card.get("data-vehiclecondition"))
            or normalize_vehicle_condition(card.get("data-unit-condition"))
            or normalize_vehicle_condition(payload.get("condition"))
            or normalize_vehicle_condition(payload.get("type"))
            or normalize_vehicle_condition(basspro_condition)
            or normalize_vehicle_condition(onewater_condition)
            or normalize_vehicle_condition(marinemax_condition_meta)
            or normalize_vehicle_condition(tv_condition)
            or normalize_vehicle_condition(wilson_specs.get("condition"))
            or normalize_vehicle_condition(raw_title)
            or normalize_vehicle_condition(card_text)
            or normalize_vehicle_condition(listing_url)
        )
        if availability_status is None and room58_vin is not None and vehicle_condition in {"new", "used"}:
            availability_status = "New" if vehicle_condition == "new" else "Used"
        vehicle_identifier = _pick_vehicle_identifier(
            {
                "vin": vin,
                "hin": payload.get("hin"),
                "hullIdentificationNumber": payload.get("hullIdentificationNumber"),
                "boatHin": card.get("data-boat-hin"),
                "stock_number": card.get("data-boat-stock-number"),
                "stock": (
                    card.get("data-stock")
                    or payload.get("stock")
                    or tv_stock
                    or room58_stock
                    or onewater_stock
                    or marinemax_stock
                    or wilson_specs.get("stock number")
                    or gp_stock
                    or ds_spike_stock
                    or colony_details.get("stock #")
                ),
                "stockNo": card.get("data-stock-no") or payload.get("stockNo"),
            },
            vehicle_category=vehicle_category,
            fallback_text=card_text,
        )

        key = f"{vin or ''}|{listing_url or ''}|{raw_title or ''}"
        if key in seen:
            continue
        seen.add(key)

        if not any([make, model, vin, raw_title]):
            continue

        vehicles.append(
            VehicleListing(
                vehicle_category=vehicle_category,
                year=year,
                make=str(make).strip() if make else None,
                model=str(model).strip() if model else None,
                trim=str(trim).strip() if trim else None,
                exterior_color=str(exterior_color).strip() if exterior_color else None,
                price=price,
                mileage=usage_value if usage_unit == "miles" else None,
                usage_value=usage_value,
                usage_unit=usage_unit,
                vehicle_condition=vehicle_condition,
                vin=str(vin).strip() if vin else None,
                vehicle_identifier=vehicle_identifier or (str(vin).strip() if vin else None),
                image_url=image_url,
                listing_url=listing_url,
                raw_title=str(raw_title).strip() if raw_title else None,
                inventory_location=str(
                    inventory_location
                    or basspro_location
                    or onewater_location
                    or tv_location
                    or temptation_location
                    or wilson_specs.get("location")
                    or gp_location
                    or colony_details.get("location")
                ).strip()
                if (
                    inventory_location
                    or basspro_location
                    or onewater_location
                    or tv_location
                    or temptation_location
                    or wilson_specs.get("location")
                    or gp_location
                    or colony_details.get("location")
                )
                else None,
                availability_status=availability_status,
                is_offsite=False,
                is_in_transit=is_in_transit,
                is_in_stock=is_in_stock,
                is_shared_inventory=False,
                msrp=card_msrp,
                dealer_discount=dealer_disc,
                feature_highlights=payload_features,
                stock_date=stock_dom,
                days_on_lot=days_dom,
            )
        )

    return vehicles


def _query_lower_dict(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    return {k.lower(): v for k, v in parse_qsl(parts.query, keep_blank_values=True)}


def _page_number_from_url(url: str) -> int | None:
    q = _query_lower_dict(url)
    for k in ("page", "pt", "_p", "pn", "pg", "currentpage", "sbpage"):
        if k not in q:
            continue
        try:
            return int(q[k])
        except ValueError:
            continue
    return None


def _current_page_from_url(url: str) -> int:
    page_num = _page_number_from_url(url)
    return page_num if page_num is not None else 1


def _looks_like_pagination_anchor(a: Any) -> bool:
    cls = " ".join(a.get("class") or []).lower()
    rel = a.get("rel")
    rel_s = " ".join(rel).lower() if isinstance(rel, list) else str(rel or "").lower()
    text = a.get_text(strip=True).lower()
    aria = str(a.get("aria-label") or "").lower()
    parent_cls = ""
    parent = getattr(a, "parent", None)
    if parent is not None:
        parent_cls = " ".join(parent.get("class") or []).lower()
    combined = " ".join(x for x in (cls, rel_s, aria, parent_cls) if x)
    if any(token in combined for token in ("pagination", "pager", "page-item", "page-link", "next", "prev")):
        return True
    if text in {"next", "next page", "previous", "prev", "›", "»", "«", "‹"}:
        return True
    if text.isdigit() and ("page" in aria or "page" in combined):
        return True
    return False


def _is_non_advancing_paged_url(base_url: str, candidate_url: str) -> bool:
    current_page = _current_page_from_url(base_url)
    candidate_page = _page_number_from_url(candidate_url)
    return candidate_page is not None and candidate_page <= current_page


def _pagination_info(
    *,
    current_page: int | None = None,
    page_size: int | None = None,
    total_pages: int | None = None,
    total_results: int | None = None,
    source: str | None = None,
) -> PaginationInfo | None:
    payload: dict[str, int | str] = {}
    if current_page is not None and current_page > 0:
        payload["current_page"] = current_page
    if page_size is not None and page_size > 0:
        payload["page_size"] = page_size
    if total_pages is not None and total_pages > 0:
        payload["total_pages"] = total_pages
    if total_results is not None and total_results >= 0:
        payload["total_results"] = total_results
    if source:
        payload["source"] = source
    return PaginationInfo(**payload) if payload else None


def _merge_pagination_info(
    *infos: PaginationInfo | None,
    fallback_current_page: int | None = None,
    fallback_page_size: int | None = None,
) -> PaginationInfo | None:
    merged: dict[str, int | str] = {}
    for info in infos:
        if info is None:
            continue
        for key, value in info.model_dump(exclude_none=True).items():
            if key not in merged:
                merged[key] = value
    if not merged:
        return None
    if fallback_current_page and fallback_current_page > 1 and "current_page" not in merged:
        merged["current_page"] = fallback_current_page
    total_results = _coerce_int(merged.get("total_results"))
    page_size = _coerce_int(merged.get("page_size"))
    total_pages = _coerce_int(merged.get("total_pages"))
    current_page = _coerce_int(merged.get("current_page"))
    if (page_size is None or page_size <= 0) and fallback_page_size is not None and fallback_page_size > 0:
        merged["page_size"] = fallback_page_size
        page_size = fallback_page_size
    # Prefer total_pages derived from total_results when "Showing X–Y of Z" is authoritative —
    # visible page-number links often only reflect a short window (e.g. 1–5) and would cap pagination too early.
    if total_results is not None and page_size is not None and page_size > 0:
        computed_tp = max(1, (total_results + page_size - 1) // page_size)
        if total_pages is None or computed_tp > total_pages:
            merged["total_pages"] = computed_tp
            total_pages = computed_tp
    if current_page is not None and total_pages is not None and total_pages < current_page:
        merged["total_pages"] = current_page
    return PaginationInfo(**merged)


def _pagination_info_from_inventory_api(html: str, page_url: str) -> PaginationInfo | None:
    meta: dict[str, int] = {}
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return None
    for script in soup.find_all("script"):
        stype = (script.get("type") or "").lower()
        dsrc = (script.get("data-ms-source") or "").lower()
        if "application/json" not in stype and "inventory" not in dsrc:
            continue
        raw = script.string
        if not raw or len(raw) < 40:
            continue
        try:
            blob = json.loads(raw.strip(), strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        _walk_merge_inventory_pagination(blob, meta, depth=0)
    if not meta:
        return None
    current_page = max(meta.get("cur") or 0, _current_page_from_url(page_url))
    return _pagination_info(
        current_page=current_page,
        page_size=meta.get("size"),
        total_pages=meta.get("tp"),
        total_results=meta.get("total"),
        source="inventory_api",
    )


def _pagination_info_from_dom_summary(html: str, page_url: str) -> PaginationInfo | None:
    # Match on raw HTML first — SPA shells sometimes omit range text from stripped_strings.
    for pattern in _DISPLAY_RANGE_TOTAL_RES:
        match = pattern.search(html)
        if not match:
            continue
        start = _coerce_int(match.group("start"))
        end = _coerce_int(match.group("end"))
        total = _coerce_int(match.group("total"))
        if start is None or end is None or total is None or start <= 0 or end < start or total < end:
            continue
        page_size = end - start + 1
        current_page = ((start - 1) // page_size) + 1 if page_size > 0 else _current_page_from_url(page_url)
        return _pagination_info(
            current_page=current_page,
            page_size=page_size,
            total_results=total,
            source="dom_summary",
        )
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return None
    text = " ".join(soup.stripped_strings)
    for pattern in _DISPLAY_RANGE_TOTAL_RES:
        match = pattern.search(text)
        if not match:
            continue
        start = _coerce_int(match.group("start"))
        end = _coerce_int(match.group("end"))
        total = _coerce_int(match.group("total"))
        if start is None or end is None or total is None or start <= 0 or end < start or total < end:
            continue
        page_size = end - start + 1
        current_page = ((start - 1) // page_size) + 1 if page_size > 0 else _current_page_from_url(page_url)
        return _pagination_info(
            current_page=current_page,
            page_size=page_size,
            total_results=total,
            source="dom_summary",
        )
    match = _PAGE_OF_TOTAL_RE.search(text)
    if not match:
        return None
    current_page = _coerce_int(match.group("page"))
    total_pages = _coerce_int(match.group("total"))
    return _pagination_info(
        current_page=current_page or _current_page_from_url(page_url),
        total_pages=total_pages,
        source="dom_summary",
    )


def _pagination_info_from_page_links(html: str, page_url: str) -> PaginationInfo | None:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return None
    page_numbers: set[int] = set()
    for a in soup.find_all("a", href=True):
        parsed = urljoin(page_url, str(a["href"]))
        q = _query_lower_dict(parsed)
        raw = (
            q.get("page")
            or q.get("pt")
            or q.get("_p")
            or q.get("pn")
            or q.get("pg")
            or q.get("currentpage")
            or q.get("sbpage")
        )
        if not raw:
            data_val = str(a.get("data-val") or "").strip()
            raw = data_val if data_val.isdigit() and _looks_like_pagination_anchor(a) else None
        if not raw:
            continue
        try:
            page_num = int(raw)
        except ValueError:
            continue
        if page_num > 0:
            page_numbers.add(page_num)
    next_link = find_next_page_url(html, page_url)
    if not page_numbers and not next_link:
        return None
    total_pages = max(page_numbers) if page_numbers else None
    return _pagination_info(
        current_page=_current_page_from_url(page_url),
        total_pages=total_pages,
        source="page_links",
    )


def infer_inventory_pagination(
    html: str,
    page_url: str,
    *,
    fallback_page_size: int | None = None,
) -> PaginationInfo | None:
    current_page = _current_page_from_url(page_url)
    return _merge_pagination_info(
        _pagination_info_from_inventory_api(html, page_url),
        _pagination_info_from_dom_summary(html, page_url),
        _pagination_info_from_page_links(html, page_url),
        fallback_current_page=current_page,
        fallback_page_size=fallback_page_size,
    )


def _next_page_url_from_pagination(
    page_url: str,
    pagination: PaginationInfo | None,
    *,
    fallback_page_size: int | None = None,
) -> str | None:
    if pagination is None:
        return None
    current_page = pagination.current_page or _current_page_from_url(page_url)
    if current_page <= 0:
        return None
    if pagination.total_pages is not None and current_page < pagination.total_pages:
        return synthesize_next_page_url(page_url, current_page + 1)
    page_size = pagination.page_size or (fallback_page_size if fallback_page_size and fallback_page_size > 0 else None)
    if (
        pagination.total_results is not None
        and page_size is not None
        and page_size > 0
        and current_page * page_size < pagination.total_results
    ):
        return synthesize_next_page_url(page_url, current_page + 1)
    return None


def _pagination_link_tokens() -> tuple[str, ...]:
    return (
        "page=",
        "pt=",
        "_p=",
        "pn=",
        "pg=",
        "sbpage=",
        "p=",
        "offset=",
        "start=",
        "pageindex",
        "currentpage=",
    )


def infer_next_page_from_inventory_api(html: str, page_url: str, vehicles_on_page: int) -> str | None:
    """
    When anchors omit next-page links, use pagination fields from injected inventory API JSON
    (e.g. Dealer.com widget responses) to decide if another page exists.
    """
    fallback_page_size = vehicles_on_page if vehicles_on_page > 0 else None
    return _next_page_url_from_pagination(
        page_url,
        _pagination_info_from_inventory_api(html, page_url),
        fallback_page_size=fallback_page_size,
    )


def _try_merge_pagination_shard(d: dict[str, Any], target: dict[str, int]) -> None:
    lk = {str(k).lower(): v for k, v in d.items()}
    shard: dict[str, int] = {}
    for pk in ("page", "pagenumber", "currentpage", "number", "pageindex"):
        if pk not in lk:
            continue
        v = lk[pk]
        if isinstance(v, bool):
            continue
        try:
            shard["cur"] = int(v) if isinstance(v, int) else int(float(str(v).strip()))
            break
        except (ValueError, TypeError):
            continue
    for pk in ("pagesize", "size", "limit", "hitsperpage", "perpage", "resultsperpage", "recordsperpage"):
        if pk not in lk:
            continue
        v = lk[pk]
        try:
            shard["size"] = int(v) if isinstance(v, int) else int(float(str(v).strip()))
            break
        except (ValueError, TypeError):
            continue
    for pk in ("totalpages", "pagecount", "nbpages", "pagetotal"):
        if pk not in lk:
            continue
        v = lk[pk]
        try:
            shard["tp"] = int(v) if isinstance(v, int) else int(float(str(v).strip()))
            break
        except (ValueError, TypeError):
            continue
    for pk in ("totalcount", "totalrecords", "totalhits", "total", "recordcount", "resultcount", "numfound", "nbhits", "found"):
        if pk not in lk:
            continue
        v = lk[pk]
        if pk == "total" and isinstance(v, dict):
            continue
        try:
            shard["total"] = int(v) if isinstance(v, int) else int(float(str(v).strip()))
            break
        except (ValueError, TypeError):
            continue
    for pk in ("start", "offset", "from", "recordstart"):
        if pk not in lk:
            continue
        v = lk[pk]
        try:
            shard["start"] = int(v) if isinstance(v, int) else int(float(str(v).strip()))
            break
        except (ValueError, TypeError):
            continue
    if "cur" not in shard and "start" in shard and "size" in shard and shard["size"] > 0:
        shard["cur"] = shard["start"] // shard["size"] + 1
    if len(shard) < 2 and "tp" not in shard and "total" not in shard:
        return
    for key, value in shard.items():
        if value < 0:
            continue
        if key in {"tp", "total", "size"}:
            target[key] = max(target.get(key, 0), value)
        elif key not in target or target[key] <= 0:
            target[key] = value


def _walk_merge_inventory_pagination(obj: Any, target: dict[str, int], depth: int) -> None:
    if depth > 14:
        return
    if isinstance(obj, dict):
        _try_merge_pagination_shard(obj, target)
        for v in obj.values():
            _walk_merge_inventory_pagination(v, target, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:60]:
            _walk_merge_inventory_pagination(item, target, depth + 1)


def synthesize_next_page_url(page_url: str, next_page_num: int) -> str | None:
    """Build URL for page N, reusing an existing page query param when possible."""
    parts = urlsplit(page_url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    page_key_names = ("pt", "page", "_p", "pn", "pg", "currentpage", "sbpage")
    idx: int | None = None
    key_used: str | None = None
    for i, (k, v) in enumerate(pairs):
        if k.lower() not in page_key_names:
            continue
        try:
            int(v)
            idx, key_used = i, k
            break
        except ValueError:
            continue
    if idx is not None and key_used:
        new_pairs = list(pairs)
        new_pairs[idx] = (key_used, str(next_page_num))
        q = urlencode(new_pairs)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))
    path_lower = parts.path.lower()
    if "searchnew" in path_lower or "searchused" in path_lower:
        extra: list[tuple[str, str]] = [("pt", str(next_page_num))]
    elif "onewaterinventory.com" in parts.netloc.lower():
        extra = [("sbpage", str(next_page_num))]
    else:
        extra = [("page", str(next_page_num))]
    q = urlencode(list(pairs) + extra)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))


def _infer_next_page_url_from_showing_range(html: str, page_url: str) -> str | None:
    """Last-resort next URL when only the 'Showing X - Y of Z' banner proves more pages exist."""
    current_page = _current_page_from_url(page_url)
    if current_page <= 0:
        current_page = 1
    for pattern in _DISPLAY_RANGE_TOTAL_RES:
        m = pattern.search(html)
        if not m:
            continue
        start = _coerce_int(m.group("start"))
        end = _coerce_int(m.group("end"))
        total = _coerce_int(m.group("total"))
        if start is None or end is None or total is None or end < start or total < end:
            continue
        if total <= end:
            return None
        page_size = end - start + 1
        if page_size <= 0:
            continue
        total_pages = max(1, (total + page_size - 1) // page_size)
        if current_page < total_pages:
            return synthesize_next_page_url(page_url, current_page + 1)
    return None


def find_next_page_url(html: str, base_url: str) -> str | None:
    """Best-effort rel=next / pagination link without calling the LLM."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return None

    link = soup.find("link", attrs={"rel": lambda x: x and "next" in str(x).lower()})
    if link and link.get("href"):
        candidate = urljoin(base_url, str(link["href"]))
        if not _is_non_advancing_paged_url(base_url, candidate):
            return candidate

    for a in soup.find_all("a", href=True):
        rel = a.get("rel")
        rel_s = " ".join(rel).lower() if isinstance(rel, list) else str(rel or "").lower()
        if "next" in rel_s:
            candidate = urljoin(base_url, str(a["href"]))
            if _is_non_advancing_paged_url(base_url, candidate):
                continue
            return candidate

    current_page = _current_page_from_url(base_url)
    href_lower_tokens = _pagination_link_tokens()
    for a in soup.find_all("a", href=True):
        cls = " ".join(a.get("class") or []).lower()
        text = a.get_text(strip=True).lower()
        href = str(a["href"])
        href_l = href.lower()
        if "next" not in cls and text not in ("next", "next page", "›", "»"):
            continue
        if any(t in href_l for t in href_lower_tokens):
            candidate = urljoin(base_url, href)
            if _is_non_advancing_paged_url(base_url, candidate):
                continue
            return candidate
        data_val = str(a.get("data-val") or "").strip()
        if data_val == "+1":
            return synthesize_next_page_url(base_url, current_page + 1)
        if data_val.isdigit():
            next_page = int(data_val)
            if next_page > current_page:
                return synthesize_next_page_url(base_url, next_page)

    numbered_pages: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        parsed = urljoin(base_url, href)
        q = _query_lower_dict(parsed)
        page_val = (
            q.get("page")
            or q.get("pt")
            or q.get("_p")
            or q.get("pn")
            or q.get("pg")
            or q.get("currentpage")
            or q.get("sbpage")
        )
        if not page_val:
            data_val = str(a.get("data-val") or "").strip()
            page_val = data_val if data_val.isdigit() else None
        if not page_val:
            continue
        try:
            page_num = int(page_val)
        except ValueError:
            continue
        if page_num > current_page:
            numbered_pages.append((page_num, parsed if any(q.values()) else (synthesize_next_page_url(base_url, page_num) or parsed)))

    if numbered_pages:
        numbered_pages.sort(key=lambda item: item[0])
        return numbered_pages[0][1]
    return None


def try_extract_vehicles_without_llm(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
    vehicle_category: str = "car",
    platform_id: str | None = None,
) -> ExtractionResult | None:
    """
    If embedded/JSON-LD/inventory-api data yields concrete vehicles, map them without OpenAI.
    Returns None when structured data is missing or too weak.
    """
    dicts = collect_structured_vehicle_dicts(html, page_url)
    if platform_id is not None:
        from app.services.parser.factory import inventory_parser_for_platform

        dicts = inventory_parser_for_platform(platform_id).normalize_pricing_dicts(dicts)
    by_key: dict[str, VehicleListing] = {}
    for d in dicts:
        v = dict_to_vehicle_listing(d, page_url, vehicle_category=vehicle_category)
        if v:
            key = _vehicle_merge_key(v)
            by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    for v in extract_dom_vehicle_cards(
        html,
        page_url,
        vehicle_category=vehicle_category,
        model_filter=model_filter,
    ):
        key = _vehicle_merge_key(v)
        by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    for v in _extract_search_result_card_vehicles(html, page_url, vehicle_category=vehicle_category):
        key = _vehicle_merge_key(v)
        by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    for v in _extract_inventory_anchor_card_vehicles(html, page_url, vehicle_category=vehicle_category):
        key = _vehicle_merge_key(v)
        by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    all_vehicles = [
        _normalize_listing_for_category(
            apply_page_make_scope(v, page_url, make_filter),
            vehicle_category=vehicle_category,
        )
        for v in by_key.values()
    ]
    vehicles = [v for v in all_vehicles if listing_matches_filters(v, make_filter, model_filter)]
    fallback_page_size = len(all_vehicles) if all_vehicles else None
    pagination = infer_inventory_pagination(
        html,
        page_url,
        fallback_page_size=fallback_page_size,
    )
    next_u = find_next_page_url(html, page_url)
    if not next_u:
        next_u = _next_page_url_from_pagination(
            page_url,
            pagination,
            fallback_page_size=fallback_page_size,
        )
    if not next_u:
        next_u = _infer_next_page_url_from_showing_range(html, page_url)
    if not vehicles:
        # If we could not extract any raw listings (JS shells, failed inventory API POST, etc.)
        # but pagination heuristics still fire, returning an empty ExtractionResult would block
        # the orchestrator's LLM fallback. Only preserve empty+pagination when we actually
        # parsed vehicles and the user's filters removed every row (see parser tests).
        if (next_u or pagination is not None) and all_vehicles:
            return ExtractionResult(vehicles=[], next_page_url=next_u, pagination=pagination)
        return None

    logger.info(
        "Structured extraction: %d filtered vehicle(s) (%d raw) without LLM for %s",
        len(vehicles),
        len(all_vehicles),
        page_url,
    )
    return ExtractionResult(vehicles=vehicles, next_page_url=next_u, pagination=pagination)


async def extract_vehicles_from_html(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
    vehicle_category: str = "car",
) -> ExtractionResult:
    global _openai_disabled_reason
    if _openai_disabled_reason:
        logger.info(
            "Skipping LLM extraction for %s (%s); using deterministic fallback",
            page_url,
            _openai_disabled_reason,
        )
        return _build_no_llm_fallback_result(
            page_url=page_url,
            html=html,
            make_filter=make_filter,
            model_filter=model_filter,
            vehicle_category=vehicle_category,
        )
    if not settings.openai_api_key:
        logger.info("OPENAI_API_KEY is not set; using deterministic fallback for %s", page_url)
        return _build_no_llm_fallback_result(
            page_url=page_url,
            html=html,
            make_filter=make_filter,
            model_filter=model_filter,
            vehicle_category=vehicle_category,
        )

    snippet = await asyncio.to_thread(
        _prepare_snippet_sync, html, page_url, settings.max_html_chars
    )

    user_msg = (
        f"Page URL: {page_url}\n"
        f"Requested vehicle category: {vehicle_category}\n"
        f"User filters (strict — empty means no filter on that field):\n"
        f"  make: {make_filter or '(any)'}\n"
        f"  model: {model_filter or '(any)'}\n\n"
        f"HTML (possibly truncated):\n{snippet}"
    )

    try:
        sem = await _get_openai_semaphore()
        async with sem:
            client = await _get_openai_client()
            response = await client.beta.chat.completions.parse(
                model=settings.openai_extraction_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format=ExtractionResult,
                temperature=0.1,
                max_completion_tokens=4096,
            )
    except Exception as e:
        if _is_openai_quota_or_billing_error(e):
            _openai_disabled_reason = "openai_quota_or_billing_error"
            logger.warning(
                "OpenAI extraction disabled for this process after quota/billing error; "
                "continuing with deterministic parser fallback."
            )
            return _build_no_llm_fallback_result(
                page_url=page_url,
                html=html,
                make_filter=make_filter,
                model_filter=model_filter,
                vehicle_category=vehicle_category,
            )
        raise

    parsed = response.choices[0].message.parsed
    if not parsed:
        return ExtractionResult(vehicles=[], next_page_url=None)
    parsed = parsed.model_copy(
        update={
            "vehicles": [
                _normalize_listing_for_category(vehicle, vehicle_category=vehicle_category)
                for vehicle in parsed.vehicles
            ]
        }
    )
    fallback_page_size = max(
        len(parsed.vehicles),
        len(
            extract_dom_vehicle_cards(
                html,
                page_url,
                vehicle_category=vehicle_category,
                model_filter=model_filter,
            )
        ),
        len(_extract_search_result_card_vehicles(html, page_url, vehicle_category=vehicle_category)),
    )
    pagination = infer_inventory_pagination(
        html,
        page_url,
        fallback_page_size=fallback_page_size or None,
    )
    next_u = (
        parsed.next_page_url
        or find_next_page_url(html, page_url)
        or _next_page_url_from_pagination(
            page_url,
            pagination,
            fallback_page_size=fallback_page_size or None,
        )
    )
    if next_u != parsed.next_page_url or pagination != parsed.pagination:
        parsed = parsed.model_copy(update={"next_page_url": next_u, "pagination": pagination})
    return parsed
