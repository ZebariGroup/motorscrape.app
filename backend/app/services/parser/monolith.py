"""LLM-assisted extraction of vehicle listings from arbitrary HTML."""

from __future__ import annotations

import asyncio
import base64
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
- When MSRP and a lower sale price are both shown, set `msrp` and `price` (sale), and set
  `dealer_discount` to the gap (msrp - sale) if not stated explicitly elsewhere.
- Capture visible incentives/rebates as short strings in `incentive_labels` (e.g. "Lease Credit: $1500").
- When packages, option groups, or notable equipment lists appear, add concise lines to `feature_highlights` (max ~6 strings).
- If a stock/arrival date or "days on lot" is shown, set `stock_date` as YYYY-MM-DD when parseable, and/or `days_on_lot` as an integer.
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
_PAGE_OF_TOTAL_RE = re.compile(r"\bpage\s+(?P<page>\d{1,5})\s+of\s+(?P<total>\d{1,5})\b", re.I)


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

    final_price = _pick_price_from_dict(d)
    msrp, dealer_discount, incentive_labels = _merge_pricing_enrichment(d, final_price=final_price)
    features = _extract_feature_highlights(d)
    stock_date, days_on_lot = _extract_stock_date_and_days(d)

    return VehicleListing(
        year=_pick_year(d) or _coerce_int(title_fields.get("year")),
        make=make_s,
        model=model_s,
        trim=trim_s or (str(title_fields.get("trim")).strip() if title_fields.get("trim") else None),
        body_style=body_style_s,
        exterior_color=exterior_color_s,
        price=final_price,
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
        msrp=msrp,
        dealer_discount=dealer_discount,
        incentive_labels=incentive_labels,
        feature_highlights=features,
        stock_date=stock_date,
        days_on_lot=days_on_lot,
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
        "[data-vehicle-vin]",
        ".c-widget--vehicle",
        "li[data-component='result-tile']",
        "[data-component='result-tile']",
    )
    for card in soup.select(", ".join(selectors)):
        classes = set(card.get("class") or [])
        if "skeleton" in classes:
            continue

        payload = _parse_dom_vehicle_payload(card)
        card_text = card.get_text(" ", strip=True)
        vin = (
            card.get("data-vin")
            or card.get("data-vehicle-vin")
            or card.get("data-dotagging-item-id")
            or payload.get("vin")
            or _extract_vin_from_text(card_text)
        )
        make = card.get("data-make") or card.get("data-vehicle-make") or card.get("data-dotagging-item-make") or payload.get("make")
        model = card.get("data-model") or card.get("data-vehicle-model-name") or card.get("data-dotagging-item-model") or payload.get("model")
        year = _coerce_int(card.get("data-year") or card.get("data-vehicle-model-year") or card.get("data-dotagging-item-year") or payload.get("year"))
        trim = card.get("data-trim") or card.get("data-vehicle-trim") or card.get("data-dotagging-item-variant") or payload.get("trim")
        mileage = _coerce_int(
            card.get("data-odometer")
            or card.get("data-dotagging-item-odometer")
            or payload.get("mileage")
            or payload.get("odometer")
        )
        msrp_attr = _coerce_float(
            card.get("data-msrp")
            or card.get("data-list-price")
            or card.get("data-retail-price")
            or payload.get("msrp")
        )
        price = _coerce_float(
            card.get("data-price")
            or card.get("data-vehicle-price")
            or card.get("data-dotagging-item-price")
            or payload.get("price")
            or payload.get("internetPrice")
            or payload.get("salePrice")
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


def _current_page_from_url(url: str) -> int:
    q = _query_lower_dict(url)
    for k in ("page", "pt", "_p", "pn", "currentpage"):
        if k in q:
            try:
                return int(q[k])
            except ValueError:
                continue
    return 1


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
    if total_pages is None and total_results is not None and page_size is not None and page_size > 0:
        merged["total_pages"] = max(1, (total_results + page_size - 1) // page_size)
        total_pages = _coerce_int(merged.get("total_pages"))
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
        raw = q.get("page") or q.get("pt") or q.get("_p") or q.get("pn") or q.get("currentpage")
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
        v = dict_to_vehicle_listing(d, page_url)
        if v:
            key = _vehicle_merge_key(v)
            by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    for v in extract_dom_vehicle_cards(html, page_url):
        key = _vehicle_merge_key(v)
        by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    for v in _extract_search_result_card_vehicles(html, page_url):
        key = _vehicle_merge_key(v)
        by_key[key] = _prefer_vehicle_fields(by_key[key], v) if key in by_key else v

    all_vehicles = [apply_page_make_scope(v, page_url, make_filter) for v in by_key.values()]
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
    if not vehicles:
        if next_u or pagination is not None:
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
    fallback_page_size = max(
        len(parsed.vehicles),
        len(extract_dom_vehicle_cards(html, page_url)),
        len(_extract_search_result_card_vehicles(html, page_url)),
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
