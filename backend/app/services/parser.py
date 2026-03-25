"""LLM-assisted extraction of vehicle listings from arbitrary HTML."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from app.config import settings
from app.schemas import ExtractionResult, VehicleListing
from app.services.dealer_platforms import provider_enriched_vehicle_dicts
from app.services.inventory_filters import listing_matches_filters, normalize_vehicle_condition

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract vehicle inventory from dealership webpage HTML or JSON data.

Filtering (highest priority):
- The user message includes optional make and model filters.
- If a model filter is non-empty: return ONLY vehicles of that model. Match common variants
  (e.g. F-150, F150, F 150 are the same model). Do NOT return other models from the same make.
- If a make filter is non-empty but model is empty: return vehicles of that make only.
- If both filters are empty: extract all real vehicles for sale on the page.

Extraction rules:
- Only real vehicles for sale (cars, trucks, SUVs). Skip service specials, parts, disclaimers, nav.
- Prefer listing-specific URLs and images when present.
- Do not invent VINs, prices, or stock numbers; use null if not clearly present.
- Set `vehicle_condition` to `new` or `used` when clearly stated; otherwise use null.
- If there is a clear next-page link for inventory, set `next_page_url` to its absolute URL.
- Data may be provided as structured JSON extracted from the page. Parse it the same way.
"""

_INVENTORY_KEYS = {"make", "model", "vin", "stock", "stockno", "stock_no", "bodystyle", "bodytype"}

_VEHICLE_KEEP_KEYS = {
    "make", "model", "trim", "year", "miles", "mileage", "price",
    "priceinet", "price_inet", "pricesticker", "vin", "stockno",
    "stock_no", "bodytype", "bodystyle", "colorexterior", "colorinterior",
    "transmission", "engine", "drivetrain", "vdpurl", "vdp_url",
    "imagespath", "images_path", "imageurl", "image_url",
    "cylinders", "doors", "fueltype", "status", "condition",
    "vehiclecondition", "newused", "inventorytype", "itemcondition",
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
_TEXT_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
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
            if "name" in v:
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
    if "vehicleIdentificationNumber" in out and "vin" not in out:
        out["vin"] = out.pop("vehicleIdentificationNumber")
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
        if len(lower_keys & _INVENTORY_KEYS) >= 2:
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


def _extract_mileage_from_text(text: str | None) -> int | None:
    if not text:
        return None
    for match in _TEXT_MILEAGE_LABELED_RE.finditer(text):
        miles = _coerce_int(match.group(1))
        if miles is not None:
            return miles
    for match in _TEXT_MILEAGE_UNITS_RE.finditer(text):
        miles = _coerce_int(match.group(1))
        if miles is not None:
            return miles
    return None


def _extract_vin_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = _TEXT_VIN_RE.search(text.upper())
    return match.group(1) if match else None


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
    if parts:
        out["make"] = parts[0]
    if len(parts) >= 2:
        out["model"] = parts[1]
    if len(parts) >= 3:
        out["trim"] = " ".join(parts[2:])
    return out


def _pick_price_from_dict(d: dict[str, Any]) -> float | None:
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
    y = d.get("year") or d.get("vehicleModelDate") or d.get("modelYear")
    return _coerce_int(y)


def _pick_inventory_location(d: dict[str, Any]) -> str | None:
    for key in ("location", "inventoryLocation", "accountName", "dealerName", "dealer_name"):
        value = d.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("text")
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
    if v.vin:
        return f"vin:{v.vin}"
    return f"{v.listing_url or ''}|{v.raw_title or ''}"


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
    return VehicleListing(**merged)


def dict_to_vehicle_listing(d: dict[str, Any], base_url: str) -> VehicleListing | None:
    """Map a loose inventory/schema dict to VehicleListing; returns None if not vehicle-like."""
    make = d.get("make") or d.get("manufacturer") or d.get("brand")
    model = d.get("model")
    vin = d.get("vin") or d.get("vehicleIdentificationNumber") or d.get("vehicle_identification_number")
    if isinstance(make, dict):
        make = make.get("name")
    if isinstance(model, dict):
        model = model.get("name")
    title_hint = d.get("title") or d.get("name") or d.get("vehicleTitle")
    if isinstance(title_hint, list):
        raw_title = " ".join(str(x).strip() for x in title_hint if str(x).strip()) or None
    else:
        raw_title = str(title_hint).strip() if title_hint else None
    title_fields = _parse_title_fields(raw_title)
    make_s = str(make).strip() if make else (str(title_fields.get("make")).strip() if title_fields.get("make") else None)
    model_s = str(model).strip() if model else (str(title_fields.get("model")).strip() if title_fields.get("model") else None)
    vin_s = str(vin).strip() if vin else None
    if not make_s and not model_s and not vin_s:
        return None
    if not make_s and not model_s:
        # VIN-only without make/model is too weak for display
        return None

    vdp = (
        d.get("vdpUrl")
        or d.get("vdp_url")
        or d.get("listing_url")
        or d.get("url")
        or d.get("sameAs")
        or d.get("link")
    )
    listing_url = None
    if isinstance(vdp, list) and vdp:
        vdp = vdp[0]
    if vdp:
        listing_url = urljoin(base_url, str(vdp).replace("\\/", "/"))

    img = (
        d.get("image_url")
        or d.get("imageUrl")
        or d.get("image")
        or d.get("primaryImageUrl")
    )
    if not img and isinstance(d.get("images"), list) and d["images"]:
        img = d["images"][0]
    if isinstance(img, list) and img:
        img = img[0]
    if isinstance(img, dict):
        img = img.get("url") or img.get("contentUrl") or img.get("uri") or img.get("src")
    image_url = urljoin(base_url, str(img).replace("\\/", "/")) if img else None

    miles = d.get("miles") or d.get("mileage") or d.get("odometer")
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
    )
    if isinstance(body_style, dict):
        body_style = body_style.get("name")
    body_style_s = str(body_style).strip() if body_style else None
    exterior_color = (
        d.get("colorExterior")
        or d.get("exteriorColor")
        or d.get("ext_color")
        or d.get("color")
    )
    if isinstance(exterior_color, dict):
        exterior_color = exterior_color.get("name")
    exterior_color_s = str(exterior_color).strip() if exterior_color else None
    is_offsite = _coerce_bool(d.get("offSite") or d.get("offsite"))
    is_shared_inventory = _coerce_bool(d.get("sharedVehicle") or d.get("shared_inventory"))
    is_in_transit = _coerce_bool(d.get("inTransit") or d.get("in_transit"))
    is_in_stock = _coerce_bool(d.get("inStock") or d.get("in_stock"))
    status_text = d.get("status")
    if status_text:
        status_text = str(status_text).replace("_", " ").strip().title()

    if not raw_title:
        title_parts = [str(x) for x in [_pick_year(d), make_s, model_s, trim_s] if x]
        raw_title = " ".join(title_parts) if title_parts else None
    vehicle_condition = _pick_vehicle_condition(
        d,
        raw_title=raw_title,
        listing_url=listing_url,
        status_text=str(status_text) if status_text else None,
    )

    return VehicleListing(
        year=_pick_year(d) or _coerce_int(title_fields.get("year")),
        make=make_s,
        model=model_s,
        trim=trim_s or (str(title_fields.get("trim")).strip() if title_fields.get("trim") else None),
        body_style=body_style_s,
        exterior_color=exterior_color_s,
        price=_pick_price_from_dict(d),
        mileage=_coerce_int(miles),
        vehicle_condition=vehicle_condition,
        vin=vin_s,
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
    )


def _vehicle_record_key(d: dict[str, Any]) -> str:
    vin = str(d.get("vin") or d.get("vehicleIdentificationNumber") or "").strip()
    url = str(
        d.get("vdpUrl") or d.get("vdp_url") or d.get("url") or d.get("listing_url") or ""
    ).strip()
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


def _text_or_none(node: Any) -> str | None:
    if not node:
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def _pick_dom_vehicle_image(card: Any, page_url: str) -> str | None:
    preferred_selectors = (
        ".hero-carousel__background-image--grid",
        ".hero-carousel__background-image--list",
        ".vehicle-image img",
        "img[src]",
    )
    for selector in preferred_selectors:
        for img in card.select(selector):
            src = (img.get("src") or "").strip()
            if not src:
                continue
            lower = src.lower()
            if lower.endswith(".svg") or "copy.svg" in lower or "icon" in lower:
                continue
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


def _extract_search_result_card_vehicles(html: str, page_url: str) -> list[VehicleListing]:
    soup = BeautifulSoup(html, "lxml")
    vehicles: list[VehicleListing] = []
    seen: set[str] = set()

    for anchor in soup.select('a.car[href*="/detail/"]'):
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
        vin = _extract_vin_from_text(card_text)
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
            year=_coerce_int(title_fields.get("year")),
            make=str(title_fields.get("make")).strip() if title_fields.get("make") else None,
            model=str(title_fields.get("model")).strip() if title_fields.get("model") else None,
            trim=str(title_fields.get("trim")).strip() if title_fields.get("trim") else None,
            price=price,
            mileage=_extract_mileage_from_text(card_text),
            vehicle_condition=normalize_vehicle_condition(raw_title) or normalize_vehicle_condition(listing_url),
            vin=vin,
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


def extract_dom_vehicle_cards(html: str, page_url: str) -> list[VehicleListing]:
    """
    Pull listings from rendered SRP cards, primarily for DealerOn-style pages that
    expose data-* attrs after JS render but little/no embedded JSON.
    """
    soup = BeautifulSoup(html, "lxml")
    vehicles: list[VehicleListing] = []
    seen: set[str] = set()

    selectors = (
        ".vehicle-card",
        ".result-wrap.new-vehicle",
        ".new-vehicle[data-vehicle]",
        ".si-vehicle-box",
        ".carbox",
        ".inventory-vehicle-block",
        ".vehicle-box",
        ".vehicle-specials",
    )
    for card in soup.select(", ".join(selectors)):
        classes = set(card.get("class") or [])
        if "skeleton" in classes:
            continue

        payload = _parse_dom_vehicle_payload(card)
        card_text = card.get_text(" ", strip=True)
        vin = (
            card.get("data-vin")
            or card.get("data-dotagging-item-id")
            or payload.get("vin")
            or _extract_vin_from_text(card_text)
        )
        make = card.get("data-make") or card.get("data-dotagging-item-make") or payload.get("make")
        model = card.get("data-model") or card.get("data-dotagging-item-model") or payload.get("model")
        year = _coerce_int(card.get("data-year") or card.get("data-dotagging-item-year") or payload.get("year"))
        trim = card.get("data-trim") or card.get("data-dotagging-item-variant") or payload.get("trim")
        mileage = _coerce_int(
            card.get("data-odometer")
            or card.get("data-dotagging-item-odometer")
            or payload.get("mileage")
            or payload.get("odometer")
        )
        price = _coerce_float(
            card.get("data-price")
            or card.get("data-msrp")
            or card.get("data-dotagging-item-price")
            or payload.get("price")
            or payload.get("internetPrice")
            or payload.get("salePrice")
            or payload.get("msrp")
        )
        if price in (None, 0.0):
            price = _pick_price_from_pricelib(card.get("data-pricelib")) or price
        is_in_stock = _coerce_bool(card.get("data-instock"))
        is_in_transit = _coerce_bool(card.get("data-intransit"))
        inventory_location = card.get("data-dotagging-item-location")
        availability_status = _build_availability_status(
            status_text=None,
            is_in_stock=is_in_stock,
            is_in_transit=is_in_transit,
            is_offsite=False,
            is_shared_inventory=False,
        )

        anchor = card if getattr(card, "name", None) == "a" else card.select_one("a[href]")
        listing_url = urljoin(page_url, anchor["href"]) if anchor and anchor.get("href") else None

        image_url = _pick_dom_vehicle_image(card, page_url)

        payload_title = " ".join(
            str(x).strip()
            for x in (payload.get("year"), payload.get("make"), payload.get("model"), payload.get("trim"))
            if x not in (None, "") and str(x).strip()
        )
        raw_title = (
            card.get("data-name")
            or _text_or_none(card.select_one(".vehicle-card__title"))
            or _text_or_none(card.select_one(".vehicleTitle"))
            or _text_or_none(card.select_one(".hit-title"))
            or _text_or_none(card.select_one(".hit-title a"))
            or _text_or_none(card.select_one(".srp-vehicle-title"))
            or _text_or_none(card.select_one(".vehicle-title"))
            or payload_title
            or payload.get("title")
            or payload.get("name")
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
        if year is None:
            year = _coerce_int(title_fields.get("year"))
        if not trim:
            trim = title_fields.get("trim")
        if price in (None, 0.0):
            price = _extract_price_from_text(card_text) or price
        if mileage is None:
            mileage = _extract_mileage_from_text(card_text)
        vehicle_condition = (
            normalize_vehicle_condition(card.get("data-condition"))
            or normalize_vehicle_condition(card.get("data-newused"))
            or normalize_vehicle_condition(card.get("data-vehiclecondition"))
            or normalize_vehicle_condition(payload.get("condition"))
            or normalize_vehicle_condition(payload.get("type"))
            or normalize_vehicle_condition(raw_title)
            or normalize_vehicle_condition(card_text)
            or normalize_vehicle_condition(listing_url)
        )

        key = f"{vin or ''}|{listing_url or ''}|{raw_title or ''}"
        if key in seen:
            continue
        seen.add(key)

        if not any([make, model, vin, raw_title]):
            continue

        vehicles.append(
            VehicleListing(
                year=year,
                make=str(make).strip() if make else None,
                model=str(model).strip() if model else None,
                trim=str(trim).strip() if trim else None,
                price=price,
                mileage=mileage,
                vehicle_condition=vehicle_condition,
                vin=str(vin).strip() if vin else None,
                image_url=image_url,
                listing_url=listing_url,
                raw_title=str(raw_title).strip() if raw_title else None,
                inventory_location=str(inventory_location).strip() if inventory_location else None,
                availability_status=availability_status,
                is_offsite=False,
                is_in_transit=is_in_transit,
                is_in_stock=is_in_stock,
                is_shared_inventory=False,
            )
        )

    return vehicles


def _query_lower_dict(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    return {k.lower(): v for k, v in parse_qsl(parts.query, keep_blank_values=True)}


def _current_page_from_url(url: str) -> int:
    q = _query_lower_dict(url)
    for k in ("page", "pt", "_p", "pn", "currentpage"):
        if k in q:
            try:
                return int(q[k])
            except ValueError:
                continue
    return 1


def _pagination_link_tokens() -> tuple[str, ...]:
    return (
        "page=",
        "pt=",
        "_p=",
        "pn=",
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
    cur = max(meta.get("cur") or 1, _current_page_from_url(page_url))
    tp = meta.get("tp")
    total = meta.get("total")
    size = meta.get("size") or (vehicles_on_page if vehicles_on_page > 0 else 12)

    has_next = False
    if tp is not None:
        has_next = cur < tp
    elif total is not None and size > 0:
        consumed = (cur - 1) * size + max(vehicles_on_page, 0)
        has_next = consumed < total
    if not has_next:
        return None
    return synthesize_next_page_url(page_url, cur + 1)


def _try_merge_pagination_shard(d: dict[str, Any], target: dict[str, int]) -> None:
    lk = {str(k).lower(): v for k, v in d.items()}
    shard: dict[str, int] = {}
    for pk in ("page", "pagenumber", "currentpage", "number"):
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
    for pk in ("pagesize", "size", "limit", "hitsperpage", "perpage"):
        if pk not in lk:
            continue
        v = lk[pk]
        try:
            shard["size"] = int(v) if isinstance(v, int) else int(float(str(v).strip()))
            break
        except (ValueError, TypeError):
            continue
    for pk in ("totalpages", "pagecount"):
        if pk not in lk:
            continue
        v = lk[pk]
        try:
            shard["tp"] = int(v) if isinstance(v, int) else int(float(str(v).strip()))
            break
        except (ValueError, TypeError):
            continue
    for pk in ("totalcount", "totalrecords", "totalhits", "total"):
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
    if "tp" in shard or "total" in shard:
        target.update(shard)


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
    page_key_names = ("pt", "page", "_p", "pn", "currentpage")
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
    else:
        extra = [("page", str(next_page_num))]
    q = urlencode(list(pairs) + extra)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))


def find_next_page_url(html: str, base_url: str) -> str | None:
    """Best-effort rel=next / pagination link without calling the LLM."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return None

    link = soup.find("link", attrs={"rel": lambda x: x and "next" in str(x).lower()})
    if link and link.get("href"):
        return urljoin(base_url, str(link["href"]))

    for a in soup.find_all("a", href=True):
        rel = a.get("rel")
        rel_s = " ".join(rel).lower() if isinstance(rel, list) else str(rel or "").lower()
        if "next" in rel_s:
            return urljoin(base_url, str(a["href"]))

    href_lower_tokens = _pagination_link_tokens()
    for a in soup.find_all("a", href=True):
        cls = " ".join(a.get("class") or []).lower()
        text = a.get_text(strip=True).lower()
        href = str(a["href"])
        href_l = href.lower()
        if "next" not in cls and text not in ("next", "next page", "›", "»"):
            continue
        if any(t in href_l for t in href_lower_tokens):
            return urljoin(base_url, href)

    current_page = _current_page_from_url(base_url)

    numbered_pages: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        parsed = urljoin(base_url, href)
        q = _query_lower_dict(parsed)
        page_val = q.get("page") or q.get("pt") or q.get("_p") or q.get("pn") or q.get("currentpage")
        if not page_val:
            continue
        try:
            page_num = int(page_val)
        except ValueError:
            continue
        if page_num > current_page:
            numbered_pages.append((page_num, parsed))

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
) -> ExtractionResult | None:
    """
    If embedded/JSON-LD/inventory-api data yields concrete vehicles, map them without OpenAI.
    Returns None when structured data is missing or too weak.
    """
    dicts = collect_structured_vehicle_dicts(html, page_url)
    vehicles: list[VehicleListing] = []
    by_key: dict[str, VehicleListing] = {}
    for d in dicts:
        v = dict_to_vehicle_listing(d, page_url)
        if v and listing_matches_filters(v, make_filter, model_filter):
            key = _vehicle_merge_key(v)
            by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    for v in extract_dom_vehicle_cards(html, page_url):
        if not listing_matches_filters(v, make_filter, model_filter):
            continue
        key = _vehicle_merge_key(v)
        by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    for v in _extract_search_result_card_vehicles(html, page_url):
        if not listing_matches_filters(v, make_filter, model_filter):
            continue
        key = _vehicle_merge_key(v)
        by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    vehicles = list(by_key.values())

    if not vehicles:
        return None

    next_u = find_next_page_url(html, page_url)
    if not next_u:
        next_u = infer_next_page_from_inventory_api(html, page_url, len(vehicles))
    logger.info(
        "Structured extraction: %d vehicle(s) without LLM for %s",
        len(vehicles),
        page_url,
    )
    return ExtractionResult(vehicles=vehicles, next_page_url=next_u)


async def extract_vehicles_from_html(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
) -> ExtractionResult:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    snippet = await asyncio.to_thread(
        _prepare_snippet_sync, html, page_url, settings.max_html_chars
    )

    user_msg = (
        f"Page URL: {page_url}\n"
        f"User filters (strict — empty means no filter on that field):\n"
        f"  make: {make_filter or '(any)'}\n"
        f"  model: {model_filter or '(any)'}\n\n"
        f"HTML (possibly truncated):\n{snippet}"
    )

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        max_retries=2,
        timeout=settings.openai_timeout,
    )
    response = await client.beta.chat.completions.parse(
        model=settings.openai_extraction_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format=ExtractionResult,
        temperature=0.1,
        max_tokens=4096,
    )

    parsed = response.choices[0].message.parsed
    if not parsed:
        return ExtractionResult(vehicles=[], next_page_url=None)
    next_u = parsed.next_page_url
    if not next_u:
        next_u = find_next_page_url(html, page_url)
    if not next_u:
        next_u = infer_next_page_from_inventory_api(html, page_url, len(parsed.vehicles))
    if next_u != parsed.next_page_url:
        parsed = parsed.model_copy(update={"next_page_url": next_u})
    return parsed
