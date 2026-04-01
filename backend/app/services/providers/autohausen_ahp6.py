"""Autohausen AHP6 inventory provider for VW group dealer widgets."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

from app.schemas import ExtractionResult, PaginationInfo, VehicleListing
from app.services.inventory_filters import listing_matches_filters

logger = logging.getLogger(__name__)

_AHP6_API_BASE = "https://apps.autohausen.de/ahp6/api"
_DEFAULT_LIMIT = 50
# Homepages often expose only publicKeyUsedVehicles / publicKeyNewVehicles (no bare publicKey).
_PUBLIC_KEY_RES = (
    re.compile(r"publicKey\s*:\s*'([^']+)'"),
    re.compile(r'publicKey\s*:\s*"([^"]+)"'),
    re.compile(r"publicKeyUsedVehicles\s*:\s*'([^']+)'"),
    re.compile(r'publicKeyUsedVehicles\s*:\s*"([^"]+)"'),
    re.compile(r"publicKeyNewVehicles\s*:\s*'([^']+)'"),
    re.compile(r'publicKeyNewVehicles\s*:\s*"([^"]+)"'),
)
_AHP6_INVENTORY_FALLBACK_PATHS = (
    "/gebrauchtwagen/fahrzeugsuche/",
    "/gebrauchtwagen/fahrzeugsuche",
    "/fahrzeugsuche/",
)
_DETAIL_PAGE_URI_RE = re.compile(r"detailPageUri:\s*'([^']+)'")
_FILTER_ARRAY_RE = {
    "typeextendedcode": re.compile(r"typeextendedcode:\s*\[([^\]]+)\]"),
    "dealeridIsNot": re.compile(r"dealeridIsNot:\s*\[([^\]]+)\]"),
}
_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
}
_GET_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _extract_public_key(html: str) -> str | None:
    text = html or ""
    for pattern in _PUBLIC_KEY_RES:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _html_looks_like_ahp6_shell(html: str) -> bool:
    h = (html or "").lower()
    return "vgrdapps.autohausen.ag" in h or "ahp6.render" in h or "apps.autohausen.de/ahp6" in h


def _fetch_inventory_html_for_public_key(page_url: str) -> tuple[str, str] | None:
    """Some fetches (CDN / ZenRows) omit inline widget config; inventory SRP usually includes keys."""
    for path in _AHP6_INVENTORY_FALLBACK_PATHS:
        candidate = urljoin(page_url, path)
        if candidate.rstrip("/") == page_url.rstrip("/"):
            continue
        try:
            response = requests.get(candidate, headers=_GET_HEADERS, timeout=22)
            response.raise_for_status()
            body = response.text or ""
            if _extract_public_key(body):
                return body, candidate
        except Exception as exc:
            logger.debug("AHP6 fallback fetch skipped for %s: %s", candidate, exc)
    return None


def _extract_detail_page_uri(html: str) -> str:
    match = _DETAIL_PAGE_URI_RE.search(html or "")
    if match:
        return match.group(1).strip()
    return "/gebrauchtwagen/fahrzeugsuche/:vehicleId"


def _extract_default_filter(html: str) -> dict[str, list[int]]:
    filters: dict[str, list[int]] = {}
    for key, pattern in _FILTER_ARRAY_RE.items():
        match = pattern.search(html or "")
        if not match:
            continue
        values = [int(token.strip()) for token in match.group(1).split(",") if token.strip().isdigit()]
        if values:
            filters[key] = values
    return filters


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{_AHP6_API_BASE}{path}",
        json=payload,
        headers=_REQUEST_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _catalog_maps(form_payload: dict[str, Any]) -> tuple[dict[int, str], dict[str, int], dict[int, dict[int, str]], dict[int, dict[str, int]]]:
    makes_by_id: dict[int, str] = {}
    make_ids_by_norm: dict[str, int] = {}
    models_by_make: dict[int, dict[int, str]] = {}
    model_ids_by_make_norm: dict[int, dict[str, int]] = {}

    for row in form_payload.get("make", []):
        label = str(row.get("label") or "").strip()
        value = str(row.get("value") or "").strip()
        if not label or not value.isdigit():
            continue
        make_id = int(value)
        makes_by_id[make_id] = label
        make_ids_by_norm[_norm(label)] = make_id

    model_payload = form_payload.get("model")
    if isinstance(model_payload, dict):
        for make_id_raw, rows in model_payload.items():
            if not str(make_id_raw).isdigit() or not isinstance(rows, list):
                continue
            make_id = int(make_id_raw)
            model_map: dict[int, str] = {}
            model_norm_map: dict[str, int] = {}
            for row in rows:
                label = str(row.get("label") or "").strip()
                value = str(row.get("value") or "").strip()
                if not label or not value.isdigit():
                    continue
                model_id = int(value)
                model_map[model_id] = label
                model_norm_map[_norm(label)] = model_id
            if model_map:
                models_by_make[make_id] = model_map
                model_ids_by_make_norm[make_id] = model_norm_map

    return makes_by_id, make_ids_by_norm, models_by_make, model_ids_by_make_norm


def _page_offset(page_url: str) -> int:
    query = dict(parse_qsl(urlsplit(page_url).query, keep_blank_values=True))
    raw = (query.get("ahp6_offset") or "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _with_page_offset(page_url: str, offset: int) -> str:
    parts = urlsplit(page_url)
    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "ahp6_offset"]
    if offset > 0:
        params.append(("ahp6_offset", str(offset)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _preferred_image(images: Any) -> str | None:
    if not isinstance(images, list):
        return None
    for image in images:
        if not isinstance(image, dict):
            continue
        for key in ("l", "xl", "m", "s", "xs"):
            url = str(image.get(key) or "").strip()
            if url:
                return url
    return None


def _vehicle_condition_from_row(row: dict[str, Any]) -> str | None:
    type_extended = _to_int(row.get("typeextendedcode"))
    if type_extended == 1:
        return "new"
    if type_extended in {2, 4}:
        return "used"
    offer_type = _to_int(row.get("offertypecode"))
    if offer_type == 1:
        return "used"
    if offer_type == 2:
        return "new"
    return None


def _make_filter_payload(
    *,
    make_filter: str,
    model_filter: str,
    make_ids_by_norm: dict[str, int],
    model_ids_by_make_norm: dict[int, dict[str, int]],
    default_filter: dict[str, list[int]],
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(default_filter)

    make_norm = _norm(make_filter)
    make_id = make_ids_by_norm.get(make_norm) if make_norm else None
    if make_id is not None:
        payload["make"] = [make_id]

    model_norm = _norm(model_filter)
    if model_norm and make_id is not None:
        model_map = model_ids_by_make_norm.get(make_id, {})
        model_id = model_map.get(model_norm)
        if model_id is not None:
            payload["model"] = [model_id]

    return payload


def _build_vehicle(
    *,
    row: dict[str, Any],
    page_url: str,
    detail_page_uri: str,
    makes_by_id: dict[int, str],
    models_by_make: dict[int, dict[int, str]],
) -> VehicleListing:
    make_id = _to_int(row.get("make"))
    model_id = _to_int(row.get("model"))
    make = makes_by_id.get(make_id) if make_id is not None else None
    model = models_by_make.get(make_id or -1, {}).get(model_id or -1)
    short_description = str(row.get("shortdescription") or "").strip()
    raw_title = " ".join(part for part in (make, short_description) if part) or short_description or None
    price = _to_float(row.get("customerprice") or row.get("price") or row.get("baseprice"))
    msrp = _to_float(row.get("listprice"))
    dealer_discount = (msrp - price) if msrp and price and msrp > price else None
    vehicle_id = _to_int(row.get("vehicleid"))
    detail_path = detail_page_uri.replace(":vehicleId", str(vehicle_id or "")).strip()
    listing_url = urljoin(page_url, detail_path) if detail_path else None
    registration_date = str(row.get("registrationdate") or "").strip()
    year = _to_int((registration_date[:4] if registration_date[:4].isdigit() else row.get("year")))

    inventory_location = str(row.get("location") or "").strip() or None
    if not inventory_location:
        selling_dealer = row.get("sellingdealer")
        if isinstance(selling_dealer, dict):
            inventory_location = (
                str(selling_dealer.get("name") or selling_dealer.get("label") or "").strip() or None
            )

    return VehicleListing(
        vehicle_category="car",
        year=year,
        make=make,
        model=model,
        trim=None,
        price=price,
        mileage=None,
        vehicle_condition=_vehicle_condition_from_row(row),
        vehicle_identifier=(str(vehicle_id) if vehicle_id is not None else None),
        image_url=_preferred_image(row.get("images")),
        listing_url=listing_url,
        raw_title=raw_title,
        inventory_location=inventory_location,
        msrp=msrp,
        dealer_discount=dealer_discount,
    )


def extract_inventory(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
    vehicle_category: str = "car",
) -> ExtractionResult | None:
    if vehicle_category != "car":
        return None

    work_html = html or ""
    effective_url = page_url
    public_key = _extract_public_key(work_html)
    if not public_key and _html_looks_like_ahp6_shell(work_html):
        recovered = _fetch_inventory_html_for_public_key(page_url)
        if recovered:
            work_html, effective_url = recovered
            public_key = _extract_public_key(work_html)
    if not public_key:
        return None

    try:
        form_payload = _post_json("/form", {"publicKey": public_key})
    except Exception as exc:
        logger.warning("AHP6 form fetch failed for %s: %s", effective_url, exc)
        return None

    makes_by_id, make_ids_by_norm, models_by_make, model_ids_by_make_norm = _catalog_maps(form_payload)
    default_filter = _extract_default_filter(work_html)
    filter_payload = _make_filter_payload(
        make_filter=make_filter,
        model_filter=model_filter,
        make_ids_by_norm=make_ids_by_norm,
        model_ids_by_make_norm=model_ids_by_make_norm,
        default_filter=default_filter,
    )
    offset = _page_offset(effective_url)

    try:
        list_payload = {
            "filter": filter_payload,
            "orderBy": "priceAsc",
            "offset": offset,
            "limit": _DEFAULT_LIMIT,
            "publicKey": public_key,
        }
        count_payload = {
            "filter": filter_payload,
            "publicKey": public_key,
        }
        rows_response = _post_json("/list", list_payload)
        count_response = _post_json("/count", count_payload)
    except Exception as exc:
        logger.warning("AHP6 inventory fetch failed for %s: %s", effective_url, exc)
        return None

    rows = rows_response.get("data")
    if not isinstance(rows, list):
        return None

    detail_page_uri = _extract_detail_page_uri(work_html)
    vehicles = [
        _build_vehicle(
            row=row,
            page_url=effective_url,
            detail_page_uri=detail_page_uri,
            makes_by_id=makes_by_id,
            models_by_make=models_by_make,
        )
        for row in rows
        if isinstance(row, dict)
    ]
    vehicles = [vehicle for vehicle in vehicles if listing_matches_filters(vehicle, make_filter, model_filter)]
    if not vehicles:
        return None

    total_results = _to_int(count_response.get("meta", {}).get("total"))
    next_offset = offset + _DEFAULT_LIMIT
    next_page_url = _with_page_offset(effective_url, next_offset) if total_results and next_offset < total_results else None

    return ExtractionResult(
        vehicles=vehicles,
        next_page_url=next_page_url,
        pagination=PaginationInfo(
            current_page=(offset // _DEFAULT_LIMIT) + 1,
            page_size=_DEFAULT_LIMIT,
            total_pages=((total_results + _DEFAULT_LIMIT - 1) // _DEFAULT_LIMIT) if total_results else None,
            total_results=total_results,
            source="ahp6_api",
        ),
    )
