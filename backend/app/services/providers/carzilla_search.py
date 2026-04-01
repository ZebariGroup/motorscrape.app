"""Carzilla search-shell provider for TYPO3 dealership inventory pages."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

from app.schemas import ExtractionResult
from app.services.inventory_filters import listing_matches_filters
from app.services.parser import try_extract_vehicles_without_llm

logger = logging.getLogger(__name__)

_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}
_REST_SERVICE_URL_RE = re.compile(r'RestServiceUrl\s*=\s*"([^"]+)"')
_ORDER_FIELD_RE = re.compile(r'data-params="[^"]*of=([^"&]+)')


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _extract_rest_service_url(html: str) -> str | None:
    match = _REST_SERVICE_URL_RE.search(html or "")
    return match.group(1).strip() if match else None


def _extract_order_field(html: str) -> str:
    match = _ORDER_FIELD_RE.search(html or "")
    return match.group(1).strip() if match else "SalePrice"


def _append_query(url: str, params: dict[str, Any]) -> str:
    parts = urlsplit(url)
    current = parse_qsl(parts.query, keep_blank_values=True)
    current.extend((key, str(value)) for key, value in params.items() if value not in (None, ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(current), parts.fragment))


def _results_page_url(page_url: str) -> str:
    parts = urlsplit(page_url)
    path = parts.path
    if "/fahrzeugsuche/trefferliste/" in path:
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    if path.endswith("/fahrzeugsuche/"):
        path = f"{path.rstrip('/')}/trefferliste/"
    elif "/fahrzeugsuche" in path:
        path = re.sub(r"/fahrzeugsuche/?", "/fahrzeugsuche/trefferliste/", path, count=1)
    else:
        path = "/fahrzeuge/fahrzeugsuche/trefferliste/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _make_id_from_initial_data(initial_data: dict[str, Any], make_filter: str) -> str | None:
    target = _norm(make_filter)
    catalog = initial_data.get("d", {}).get("SearchCatalog", {})
    makes = catalog.get("Makes") or catalog.get("makes") or []
    if not isinstance(makes, list):
        return None
    for row in makes:
        if not isinstance(row, dict):
            continue
        label = str(row.get("Name") or row.get("name") or row.get("Label") or row.get("label") or "").strip()
        identifier = str(row.get("Identifier") or row.get("identifier") or row.get("Id") or row.get("id") or "").strip()
        if label and identifier and _norm(label) == target:
            return identifier
    return None


def _fetch_json(url: str) -> dict[str, Any] | None:
    response = requests.get(url, headers=_REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def _fetch_text(url: str) -> str:
    response = requests.get(url, headers=_REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


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

    lower_path = urlsplit(page_url).path.lower()
    if "/fahrzeugsuche/trefferliste/" in lower_path:
        result = try_extract_vehicles_without_llm(
            page_url=page_url,
            html=html,
            make_filter=make_filter,
            model_filter=model_filter,
            vehicle_category=vehicle_category,
        )
        if result is None:
            return None
        result.vehicles = [vehicle for vehicle in result.vehicles if listing_matches_filters(vehicle, make_filter, model_filter)]
        return result if result.vehicles else None

    rest_service_url = _extract_rest_service_url(html)
    if not rest_service_url:
        return None

    try:
        initial_data_url = _append_query(
            urljoin(page_url, rest_service_url),
            {
                "method": "GetInitialData",
                "search": "1",
                "ca": "",
                "of": _extract_order_field(html),
            },
        )
        initial_data = _fetch_json(initial_data_url)
    except Exception as exc:
        logger.warning("Carzilla initial data fetch failed for %s: %s", page_url, exc)
        return None

    results_url = _results_page_url(page_url)
    query: dict[str, Any] = {"of": _extract_order_field(html)}
    if make_filter.strip():
        make_id = _make_id_from_initial_data(initial_data or {}, make_filter)
        if make_id:
            query["ma"] = make_id

    try:
        rendered_results_url = _append_query(results_url, query)
        results_html = _fetch_text(rendered_results_url)
    except Exception as exc:
        logger.warning("Carzilla results fetch failed for %s via %s: %s", page_url, results_url, exc)
        return None

    result = try_extract_vehicles_without_llm(
        page_url=rendered_results_url,
        html=results_html,
        make_filter=make_filter,
        model_filter=model_filter,
        vehicle_category=vehicle_category,
    )
    if result is None:
        return None
    result.vehicles = [vehicle for vehicle in result.vehicles if listing_matches_filters(vehicle, make_filter, model_filter)]
    return result if result.vehicles else None
