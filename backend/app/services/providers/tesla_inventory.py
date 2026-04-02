"""Tesla inventory extraction strategy."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.schemas import ExtractionResult, VehicleListing
from app.services.inventory_filters import listing_matches_filters, normalize_vehicle_condition
from app.services.parser import try_extract_vehicles_without_llm

_TESLA_MODEL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bmodel\s*3\b", re.I), "Model 3"),
    (re.compile(r"\bmodel\s*y\b", re.I), "Model Y"),
    (re.compile(r"\bmodel\s*s\b", re.I), "Model S"),
    (re.compile(r"\bmodel\s*x\b", re.I), "Model X"),
    (re.compile(r"\bcybertruck\b", re.I), "Cybertruck"),
)
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.I)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    cleaned = re.sub(r"[^\d-]", "", text)
    if cleaned in {"", "-"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _infer_model(raw: str) -> str | None:
    if not raw:
        return None
    for pattern, label in _TESLA_MODEL_PATTERNS:
        if pattern.search(raw):
            return label
    return None


def _walk_objects(obj: Any, out: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 16:
        return
    if isinstance(obj, dict):
        out.append(obj)
        for value in obj.values():
            _walk_objects(value, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_objects(item, out, depth + 1)


def _extract_json_objects_from_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    for script in soup.find_all("script"):
        script_type = (script.get("type") or "").lower()
        if script_type and "json" not in script_type:
            continue
        raw = (script.string or script.get_text() or "").strip()
        if len(raw) < 16:
            continue
        parsed: Any | None = None
        try:
            parsed = json.loads(raw)
        except Exception:
            pass
        # Some Tesla pages embed escaped JSON payload strings assigned to variables.
        if parsed is None:
            try:
                # Look for {"results":[...]} or similar within the script block
                m = re.search(r'(\{[\s\S]*"results"[\s\S]*\})', raw)
                if m:
                    parsed = json.loads(m.group(1))
            except Exception:
                pass
        if parsed is None:
            try:
                # Sometimes it's double-encoded string
                m = re.search(r'["\'](\{[\s\S]*"results"[\s\S]*\})["\']', raw)
                if m:
                    parsed = json.loads(m.group(1).encode('utf-8').decode('unicode_escape'))
            except Exception:
                pass
        if parsed is None:
            continue
        _walk_objects(parsed, out)
    return out


def _vin_from_dict(row: dict[str, Any]) -> str | None:
    for key in ("VIN", "vin", "vehicle_vin", "vehicleVin"):
        vin = str(row.get(key) or "").strip().upper()
        if vin and _VIN_RE.fullmatch(vin):
            return vin
    return None


def _listing_from_dict(row: dict[str, Any], *, page_url: str) -> VehicleListing | None:
    vin = _vin_from_dict(row)
    if not vin:
        return None
    raw_title = str(
        row.get("Title")
        or row.get("VehicleName")
        or row.get("vehicleTitle")
        or row.get("name")
        or row.get("Description")
        or ""
    ).strip()
    model = str(
        row.get("Model")
        or row.get("model")
        or row.get("ModelName")
        or row.get("TrimName")
        or ""
    ).strip()
    model = _infer_model(f"{model} {raw_title}") or (model if model else None)
    year = _coerce_int(row.get("Year") or row.get("year") or row.get("ModelYear"))
    price = _coerce_float(
        row.get("Price")
        or row.get("price")
        or row.get("InventoryPrice")
        or row.get("VehiclePrice")
        or row.get("CashPrice")
    )
    mileage = _coerce_int(row.get("Odometer") or row.get("Mileage") or row.get("mileage"))
    condition = normalize_vehicle_condition(
        row.get("Condition")
        or row.get("inventoryType")
        or row.get("VehicleCondition")
        or page_url
    )
    listing_url = str(
        row.get("URL")
        or row.get("Url")
        or row.get("VdpUrl")
        or row.get("listingUrl")
        or row.get("detail_url")
        or ""
    ).strip()
    if listing_url:
        listing_url = urljoin(page_url, listing_url)
    elif model:
        model_slug = model.lower().replace(" ", "")
        listing_url = f"https://www.tesla.com/inventory/{condition or 'new'}/{model_slug}/{vin}"
    else:
        listing_url = page_url
    trim = str(row.get("TrimName") or row.get("Trim") or row.get("TrimBadging") or "").strip() or None
    exterior_color = str(
        row.get("ExteriorColor")
        or row.get("PAINT")
        or row.get("Paint")
        or row.get("Color")
        or ""
    ).strip() or None
    image_url = str(
        row.get("Thumbnail")
        or row.get("ImageUrl")
        or row.get("image_url")
        or row.get("HeroImage")
        or ""
    ).strip() or None
    if image_url:
        image_url = urljoin(page_url, image_url)
    listing = VehicleListing(
        vehicle_category="car",
        year=year,
        make="Tesla",
        model=model,
        trim=trim,
        fuel_type="Electric",
        price=price,
        mileage=mileage,
        vehicle_condition=condition,
        vin=vin,
        vehicle_identifier=vin,
        image_url=image_url,
        listing_url=listing_url,
        raw_title=raw_title or None,
        exterior_color=exterior_color,
    )
    return listing


def _extract_structured_tesla_listings(
    *,
    html: str,
    page_url: str,
    make_filter: str,
    model_filter: str,
) -> list[VehicleListing]:
    candidate_dicts = _extract_json_objects_from_html(html)
    vehicles: list[VehicleListing] = []
    seen_vins: set[str] = set()
    for row in candidate_dicts:
        listing = _listing_from_dict(row, page_url=page_url)
        if listing is None:
            continue
        vin = (listing.vin or "").upper()
        if not vin or vin in seen_vins:
            continue
        if not listing_matches_filters(listing, make_filter, model_filter):
            continue
        seen_vins.add(vin)
        vehicles.append(listing)
    return vehicles


def extract_inventory(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
    vehicle_category: str = "car",
) -> ExtractionResult | None:
    # Tesla inventory pages often carry full inventory payloads in JSON scripts.
    parsed = _extract_structured_tesla_listings(
        html=html,
        page_url=page_url,
        make_filter=make_filter,
        model_filter=model_filter,
    )
    if parsed:
        return ExtractionResult(vehicles=parsed, next_page_url=None)
    return try_extract_vehicles_without_llm(
        page_url=page_url,
        html=html,
        make_filter=make_filter,
        model_filter=model_filter,
        vehicle_category=vehicle_category,
        platform_id="tesla_inventory",
    )
