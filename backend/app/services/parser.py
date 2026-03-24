"""LLM-assisted extraction of vehicle listings from arbitrary HTML."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from app.config import settings
from app.schemas import ExtractionResult, VehicleListing
from app.services.dealer_platforms import provider_enriched_vehicle_dicts
from app.services.inventory_filters import listing_matches_filters

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
- If there is a clear next-page link for inventory, set `next_page_url` to its absolute URL.
- Data may be provided as structured JSON extracted from the page. Parse it the same way.
"""

_INVENTORY_KEYS = {"make", "model", "vin", "stockno", "stock_no", "bodystyle", "bodytype"}

_VEHICLE_KEEP_KEYS = {
    "make", "model", "trim", "year", "miles", "mileage", "price",
    "priceinet", "price_inet", "pricesticker", "vin", "stockno",
    "stock_no", "bodytype", "bodystyle", "colorexterior", "colorinterior",
    "transmission", "engine", "drivetrain", "vdpurl", "vdp_url",
    "imagespath", "images_path", "imageurl", "image_url",
    "cylinders", "doors", "fueltype", "status",
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


def _pick_price_from_dict(d: dict[str, Any]) -> float | None:
    for key in ("price", "priceInet", "price_inet", "internetPrice", "sellingPrice"):
        p = _coerce_float(d.get(key))
        if p is not None and p > 0:
            return p
    offers = d.get("offers")
    if isinstance(offers, dict):
        for key in ("price", "lowPrice", "highPrice"):
            p = _coerce_float(offers.get(key))
            if p is not None and p > 0:
                return p
    return None


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


def dict_to_vehicle_listing(d: dict[str, Any], base_url: str) -> VehicleListing | None:
    """Map a loose inventory/schema dict to VehicleListing; returns None if not vehicle-like."""
    make = d.get("make") or d.get("manufacturer") or d.get("brand")
    model = d.get("model")
    vin = d.get("vin") or d.get("vehicleIdentificationNumber") or d.get("vehicle_identification_number")
    if isinstance(make, dict):
        make = make.get("name")
    if isinstance(model, dict):
        model = model.get("name")
    make_s = str(make).strip() if make else None
    model_s = str(model).strip() if model else None
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
    is_offsite = _coerce_bool(d.get("offSite") or d.get("offsite"))
    is_shared_inventory = _coerce_bool(d.get("sharedVehicle") or d.get("shared_inventory"))
    is_in_transit = _coerce_bool(d.get("inTransit") or d.get("in_transit"))
    is_in_stock = _coerce_bool(d.get("inStock") or d.get("in_stock"))
    status_text = d.get("status")
    if status_text:
        status_text = str(status_text).replace("_", " ").strip().title()

    title_parts = [str(x) for x in [_pick_year(d), make_s, model_s, trim_s] if x]
    raw_title = " ".join(title_parts) if title_parts else None

    return VehicleListing(
        year=_pick_year(d),
        make=make_s,
        model=model_s,
        trim=trim_s,
        price=_pick_price_from_dict(d),
        mileage=_coerce_int(miles),
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
    return f"{vin}|{url}"


def collect_structured_vehicle_dicts(html: str, page_url: str) -> list[dict[str, Any]]:
    """Merge generic embedded JSON inventory with platform-specific JSON-LD vehicles."""
    soup = BeautifulSoup(html, "lxml")
    generic = _extract_json_inventory(html, soup)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in generic:
        k = _vehicle_record_key(r)
        if k not in seen:
            seen.add(k)
            merged.append(r)
    extra = provider_enriched_vehicle_dicts(html, page_url)
    if extra:
        for d in extra:
            nd = _normalize_schema_org(d)
            k = _vehicle_record_key(nd)
            if k in seen:
                continue
            if nd.get("make") or nd.get("model") or nd.get("vehicleIdentificationNumber"):
                seen.add(k)
                merged.append(nd)
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


def extract_dom_vehicle_cards(html: str, page_url: str) -> list[VehicleListing]:
    """
    Pull listings from rendered SRP cards, primarily for DealerOn-style pages that
    expose data-* attrs after JS render but little/no embedded JSON.
    """
    soup = BeautifulSoup(html, "lxml")
    vehicles: list[VehicleListing] = []
    seen: set[str] = set()

    for card in soup.select(".vehicle-card"):
        classes = set(card.get("class") or [])
        if "skeleton" in classes:
            continue

        vin = card.get("data-vin") or card.get("data-dotagging-item-id")
        make = card.get("data-make") or card.get("data-dotagging-item-make")
        model = card.get("data-model") or card.get("data-dotagging-item-model")
        year = _coerce_int(card.get("data-year") or card.get("data-dotagging-item-year"))
        trim = card.get("data-trim") or card.get("data-dotagging-item-variant")
        mileage = _coerce_int(card.get("data-odometer") or card.get("data-dotagging-item-odometer"))
        price = _coerce_float(
            card.get("data-price")
            or card.get("data-msrp")
            or card.get("data-dotagging-item-price")
        )
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

        anchor = card.select_one("a[href]")
        listing_url = urljoin(page_url, anchor["href"]) if anchor and anchor.get("href") else None

        image_url = _pick_dom_vehicle_image(card, page_url)

        raw_title = (
            card.get("data-name")
            or _text_or_none(card.select_one(".vehicle-card__title"))
            or _text_or_none(card.select_one(".vehicleTitle"))
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

    for a in soup.find_all("a", href=True):
        cls = " ".join(a.get("class") or []).lower()
        text = a.get_text(strip=True).lower()
        href = str(a["href"])
        if "next" not in cls and text not in ("next", "next page", "›", "»"):
            continue
        if any(x in href.lower() for x in ("page=", "p=", "offset=", "start=", "pn=", "pageindex")):
            return urljoin(base_url, href)
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
    for d in dicts:
        v = dict_to_vehicle_listing(d, page_url)
        if v and listing_matches_filters(v, make_filter, model_filter):
            vehicles.append(v)

    for v in extract_dom_vehicle_cards(html, page_url):
        if not listing_matches_filters(v, make_filter, model_filter):
            continue
        key = f"{v.vin or ''}|{v.listing_url or ''}|{v.raw_title or ''}"
        if any(f"{x.vin or ''}|{x.listing_url or ''}|{x.raw_title or ''}" == key for x in vehicles):
            continue
        vehicles.append(v)

    if not vehicles:
        return None

    next_u = find_next_page_url(html, page_url)
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
    return parsed
