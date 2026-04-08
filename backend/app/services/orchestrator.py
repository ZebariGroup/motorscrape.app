"""Coordinates Places → scrape → LLM parse with async iteration for SSE."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.schemas import DealershipFound, ExtractionResult, PaginationInfo, VehicleListing
from app.services.dealer_bias import dealer_preference_bias
from app.services.dealer_platforms import detect_platform_profile
from app.services.dealer_score_store import DealerScoreCard, NO_SCORE_DEFAULT, get_score_cards, record_scrape_outcome
from app.services.economics import build_search_economics, log_economics_line
from app.services.inventory_discovery import discover_sitemap_inventory_urls
from app.services.inventory_filters import (
    apply_eu_make_default_from_dealer_context,
    apply_page_make_scope,
    infer_vehicle_condition_from_page,
    listing_matches_filters,
    listing_matches_inventory_scope,
    listing_matches_vehicle_condition,
    normalize_vehicle_condition,
)
from app.services.inventory_result_cache import (
    get_inventory_cache_entry,
    inventory_listings_cache_key,
    set_cached_inventory_listings,
)
from app.services.inventory_tracking import build_listing_history_fields, inventory_history_key
from app.services.orchestrator_market import (
    historical_market_points_for_listing,
    market_valuation_enabled_for_listing,
)
from app.services.orchestrator_utils import (
    dedupe_dealers_by_domain,
    domain_fetch_limiter,
    effective_search_concurrency,
    guess_franchise_inventory_srp_url,
    guess_franchise_inventory_srp_urls,
    html_mentions_make,
    html_mentions_model,
    prefer_https_website_url,
)
from app.services.parser import monolith as parser_monolith
from app.services.parser import enrich_team_velocity_srp_pricing, extract_vehicles_from_html, try_extract_vehicles_without_llm
from app.services.places import (
    PlacesSearchMetrics,
    expand_large_radius_search_locations,
    find_car_dealerships,
    find_dealerships,
    resolve_search_location_center,
)
from app.services.platform_store import normalize_dealer_domain, platform_store
from app.services.provider_router import (
    ProviderRoute,
    _build_family_inventory_path_variants,
    _canonical_oneaudi_inventory_url,
    detect_or_lookup_provider,
    provider_route_from_cache_entry,
    record_provider_failure,
    remember_provider_success,
    resolve_inventory_url_for_provider,
    speculative_inventory_url,
    speculative_inventory_urls_for_unknown_site,
)
from app.services.providers import extract_with_provider
from app.services.search_errors import SearchErrorInfo, with_search_error
from app.services.scrape_logging import ScrapeRunRecorder
from app.services.scraper import PageKind, _looks_like_block_page, _sanitize_inventory_query_url, fetch_page_html
from app.services.vin_decoder import enrich_vehicle_listings_with_vin_data
from app.sse import sse_pack

logger = logging.getLogger(__name__)
_STREAM_LISTING_BATCH_SIZE = 24
# Sentinel placed on per-search SSE queue when a dealership worker finishes (see stream_search).
_SSE_STREAM_WORKER_DONE = object()

# Inventory-page family stacks that should override generic website platforms (DealerOn / Inspire / DDC).
_INVENTORY_FAMILY_PLATFORM_IDS = frozenset(
    {
        "ford_family_inventory",
        "gm_family_inventory",
        "toyota_lexus_oem_inventory",
    }
)


def _route_supports_team_velocity_style_inventory_reroute(route: ProviderRoute | None) -> bool:
    """True when /new-vehicles → /inventory/new style reroute is appropriate for this route."""
    if route is None:
        return False
    if route.platform_id == "team_velocity":
        return True
    if route.platform_id != "dealer_inspire":
        return False
    for h in route.inventory_path_hints or ():
        hl = (h or "").lower()
        if "inventory/new" in hl or "inventory/used" in hl:
            return True
    return False


def _team_velocity_inventory_url_from_model_hub(
    url: str | None,
    *,
    vehicle_condition: str,
) -> str | None:
    if not url:
        return None
    condition = (vehicle_condition or "").strip().lower()
    parts = urlsplit(url)
    path = parts.path.rstrip("/").lower()
    if path == "/new-vehicles" or path.startswith("/new-vehicles/"):
        suffix = path.removeprefix("/new-vehicles")
        return urlunsplit((parts.scheme, parts.netloc, f"/inventory/new{suffix}", "", ""))
    if path == "/used-vehicles" or path.startswith("/used-vehicles/"):
        suffix = path.removeprefix("/used-vehicles")
        return urlunsplit((parts.scheme, parts.netloc, f"/inventory/used{suffix}", "", ""))
    if condition not in {"new", "used"}:
        return None
    return None


def _oneaudi_all_inventory_urls(url: str | None) -> list[str]:
    if not url:
        return []
    variants = [
        _canonical_oneaudi_inventory_url(url, "new"),
        _canonical_oneaudi_inventory_url(url, "used"),
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in variants:
        normalized = candidate.rstrip("/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(candidate)
    return ordered


def _tesla_model_slug(model: str) -> str | None:
    norm = re.sub(r"[^a-z0-9]", "", (model or "").lower())
    if not norm:
        return None
    mapping = {
        "model3": "m3",
        "modely": "my",
        "models": "ms",
        "modelx": "mx",
        "cybertruck": "ct",
    }
    return mapping.get(norm)


def _extract_us_zip(value: str) -> str | None:
    matches = re.findall(r"\b(\d{5})(?:-\d{4})?\b", value or "")
    if not matches:
        return None
    # Addresses can contain 5-digit street numbers (e.g. "10250 ... CA 90067");
    # the postal code appears at the end, so prefer the last ZIP-shaped token.
    return matches[-1]


def _looks_like_tesla_site_url(url: str | None) -> bool:
    if not url:
        return False
    parts = urlsplit(url)
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    if not host.endswith("tesla.com"):
        return False
    path = parts.path.lower()
    return path.startswith("/findus/location/store") or path.startswith("/inventory")


def _is_tesla_make(make: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", (make or "").lower()) == "tesla"


def _tesla_inventory_has_location_scope(url: str | None) -> bool:
    if not url:
        return False
    parts = urlsplit(url)
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    if not host.endswith("tesla.com"):
        return False
    if not parts.path.lower().startswith("/inventory"):
        return False
    query = {k.lower(): v for k, v in parse_qsl(parts.query, keep_blank_values=True)}
    return bool(_extract_us_zip(str(query.get("zip") or "")))


def _tesla_inventory_urls(
    url: str | None,
    *,
    vehicle_condition: str,
    model: str = "",
    fallback_zip: str | None = None,
    fallback_range_miles: int | None = None,
) -> list[str]:
    if not url:
        return []
    parts = urlsplit(url)
    scheme = parts.scheme or "https"
    netloc = parts.netloc or "www.tesla.com"
    condition = (vehicle_condition or "all").strip().lower()
    models: list[str]
    requested_slug = _tesla_model_slug(model)
    if requested_slug:
        models = [requested_slug]
    else:
        models = ["m3", "my", "ms", "mx", "ct"]
    if condition == "used":
        scopes = ("used",)
    elif condition == "new":
        scopes = ("new",)
    else:
        scopes = ("new", "used")

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "arrangeby" not in query:
        query["arrangeby"] = "relevance"
    if not str(query.get("zip") or "").strip():
        inferred_zip = _extract_us_zip(fallback_zip or "")
        if inferred_zip:
            query["zip"] = inferred_zip
    if str(query.get("zip") or "").strip() and not str(query.get("range") or "").strip():
        range_miles = max(1, int(fallback_range_miles or 0))
        if range_miles > 0:
            query["range"] = str(range_miles)
    q = urlencode(query)

    out: list[str] = []
    seen: set[str] = set()
    for scope in scopes:
        for slug in models:
            candidate = urlunsplit((scheme, netloc, f"/inventory/{scope}/{slug}", q, ""))
            key = candidate.rstrip("/")
            if key and key not in seen:
                seen.add(key)
                out.append(candidate)
    return out


def _scope_filter_tokens(raw: str) -> set[str]:
    tokens: set[str] = set()
    for part in (raw or "").split(","):
        value = part.strip().lower()
        if not value:
            continue
        tokens.add(re.sub(r"[^a-z0-9]", "", value))
    return {token for token in tokens if token}


def _mv_median(values: list[float]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2 == 0:
        return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0
    return sorted_values[middle]


def _inventory_url_uses_scoped_filters(url: str | None, *, make: str, model: str) -> bool:
    if not url:
        return False
    parts = urlsplit(url)
    query = {k.lower(): v.lower() for k, v in parse_qsl(parts.query, keep_blank_values=True)}
    if _tesla_inventory_has_location_scope(url):
        return True
    if any(
        key in query
        for key in ("make", "model", "modelandtrim", "_dfr[make][0]", "_dfr[model][0]")
    ):
        return True
    haystack = re.sub(r"[^a-z0-9]", "", f"{parts.path} {parts.query}".lower())
    for token in _scope_filter_tokens(make).union(_scope_filter_tokens(model)):
        if token and token in haystack:
            return True
    return False


def _looks_like_zero_inventory_results_page(html: str, current_url: str | None) -> bool:
    if not html or not current_url:
        return False
    lower = html.lower()
    if "vehicle_results_label" in lower and re.search(r"results:\s*0\s+vehicles\b", lower, re.I):
        return True
    return any(
        marker in lower
        for marker in (
            "results: 0 vehicles",
            "0 vehicles",
            "0 results",
            "we apologize that we cannot find what you are looking for",
        )
    )


def _requested_model_values(raw: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for part in (raw or "").split(","):
        value = part.strip()
        if not value:
            continue
        key = re.sub(r"[^a-z0-9]", "", value.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        values.append(value)
    return values


def _dealer_on_multi_model_inventory_urls(
    base_url: str,
    *,
    make: str,
    model: str,
) -> list[str]:
    models = _requested_model_values(model)
    if len(models) < 2:
        return []
    cleaned = _drop_query_keys(
        base_url,
        {"make", "model", "modelandtrim", "search", "q", "page"},
    )
    parts = urlsplit(cleaned)
    path = parts.path.lower()
    if not (path.endswith("/searchnew.aspx") or path.endswith("/searchused.aspx")):
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for model_value in models:
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        if make.strip():
            params["Make"] = make.strip()
        params["Model"] = model_value
        params["ModelAndTrim"] = model_value
        scoped = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))
        if scoped in seen:
            continue
        seen.add(scoped)
        urls.append(scoped)
    return urls


def _dealer_inspire_multi_model_inventory_urls(
    base_url: str,
    *,
    vehicle_condition: str,
    make: str,
    model: str,
) -> list[str]:
    models = _requested_model_values(model)
    if len(models) < 2:
        return []
    condition = (vehicle_condition or "").strip().lower()
    if condition not in {"new", "used"}:
        return []
    parts = urlsplit(base_url)
    if not parts.scheme or not parts.netloc:
        return []

    root = "/used-vehicles/" if condition == "used" else "/new-vehicles/"
    canonical = urlunsplit((parts.scheme, parts.netloc, root, "", ""))
    base_updates: dict[str, str] = {"_dFR[type][0]": "Used" if condition == "used" else "New"}
    if make.strip():
        base_updates["_dFR[make][0]"] = make.strip()

    urls: list[str] = []
    seen: set[str] = set()
    for model_value in models:
        updates = dict(base_updates)
        updates["_dFR[model][0]"] = model_value
        scoped = _with_query_params(canonical, updates)
        if scoped in seen:
            continue
        seen.add(scoped)
        urls.append(scoped)
    return urls


def _looks_like_inventory_detail_href(href: str) -> bool:
    path = urlsplit(href).path.lower()
    if re.search(r"/inventory/\d+(?:/|$)", path):
        return True
    if "detail" in path:
        return True
    return bool(re.search(r"(?:^|[-_/])(?:19|20)\d{2}(?:[-_/]|$)", path))


def _find_inventory_url(
    html: str,
    base_url: str,
    *,
    vehicle_condition: str = "all",
    market_region: str = "us",
) -> str:
    """Heuristic to find the best 'inventory' link on a dealership homepage."""
    try:
        soup = BeautifulSoup(html, "lxml")
        best_url = base_url
        best_score = -1
        condition = (vehicle_condition or "all").strip().lower()
        eu = (market_region or "").strip().lower() == "eu"

        def _is_oem_inventory_jump_target(host: str, path: str) -> bool:
            host_l = (host or "").lower()
            path_l = (path or "").lower()
            if host_l == "gebrauchtwagen.mercedes-benz.de":
                return True
            if host_l == "traumsterne.mercedes-benz.de":
                return True
            if host_l.endswith("audi.de") and (
                "neuwagenboerse" in path_l or "gebrauchtwagenboerse" in path_l
            ):
                return True
            return False

        for a in soup.find_all("a", href=True):
            href_raw = str(a["href"])
            href_parts = urlsplit(href_raw)
            if href_parts.scheme and href_parts.scheme.lower() not in {"http", "https"}:
                continue
            href = href_raw.lower()
            href_query = {k.lower(): v.lower() for k, v in parse_qsl(href_parts.query, keep_blank_values=True)}
            href_path = href_parts.path.lower()
            text = a.get_text(strip=True).lower()
            href_fragment = href_parts.fragment.lower()
            score = 0

            if _looks_like_inventory_detail_href(href_raw):
                continue

            if eu:
                # EU OEM sites often expose stock via localized SRPs or OEM-hosted inventory hubs.
                if any(
                    tok in href
                    for tok in (
                        "used-cars",
                        "usedcars",
                        "/used/",
                        "new-cars",
                        "newcars",
                        "/new/",
                        "approved-used",
                        "stocklist",
                        "vehicle-search",
                        "cars-for-sale",
                        "used-cars-for-sale",
                        "gebrauchtwagen",
                        "neuwagen",
                        "fahrzeuge",
                        "occasion",
                        "voitures",
                        "vehicules",
                        "stock",
                        "parc-auto",
                        "search-results",
                    )
                ) or any(
                    tok in text
                    for tok in (
                        "used cars",
                        "new cars",
                        "approved used",
                        "our stock",
                        "used vehicles",
                        "new vehicles",
                        "occasion",
                        "véhicules",
                        "vehicules",
                        "stock list",
                    )
                ):
                    score += 24
                if any(tok in href for tok in ("neuwagenboerse", "gebrauchtwagenboerse", "fahrzeugsuche")):
                    score += 90
                if any(tok in href_path for tok in ("/de/neuwagen", "/de/gebrauchtwagen")):
                    score += 45

            if "inventory" in href or "inventory" in text:
                score += 20
            if any(token in href or token in text for token in ("boats", "boat", "marine", "motorcycle", "powersports")):
                score += 8
            if any(
                token in href
                for token in (
                    "default.asp?page=xallinventory",
                    "default.asp?page=xnewinventory",
                    "default.asp?page=xpreownedinventory",
                    "all-inventory-in-stock",
                    "new-inventory-in-stock",
                    "used-inventory-in-stock",
                )
            ):
                score += 60
            if "in stock" in text or "in-stock" in href:
                score += 30
            if any(token in href for token in ("manufacturer-models", "model-list")) or "model list" in text:
                score -= 80
            if any(
                token in href_path
                for token in ("/passengercars/news/", "/news/models/", "/company-news", "/offers/offers-new-vehicles")
            ):
                score -= 120
            if "showroom" in href or "showroom" in text:
                score -= 15
            if href_fragment:
                score -= 20
            if any(token in href or token in href_fragment for token in ("?make=", "&make=", "vc=", "sq=", "model=")):
                score -= 25
            if condition == "new":
                if "new-inventory" in href:
                    score += 40
                if "searchnew" in href:
                    score += 35
                if "inventory" in href and "new" in href:
                    score += 30
                if "new" in href or "new" in text:
                    score += 10
                if "used-inventory" in href:
                    score -= 10
                if "used" in href or "pre-owned" in text or "used" in text:
                    score -= 15
            elif condition == "used":
                if "used-inventory" in href or "used-vehicles" in href:
                    score += 40
                if "searchused" in href:
                    score += 35
                if "pre-owned" in href or "pre-owned" in text:
                    score += 25
                if "used" in href or "used" in text:
                    score += 20
                if "new-inventory" in href:
                    score -= 15
                if "searchnew" in href or ("new" in href or "new" in text):
                    score -= 10
            else:
                if "all-inventory" in href:
                    score += 45
                if "inventory" in href and "new" not in href and "used" not in href:
                    score += 15
                if "new-inventory" in href or "used-inventory" in href:
                    score += 5
                if "certified-inventory" in href or "certified" in text:
                    score -= 20
                # Avoid over-scoped inventory links for "all" searches (they often 404 or hide stock).
                condition_value = href_query.get("condition", "").strip().lower()
                if condition_value in {"pre-owned", "preowned", "used", "new"}:
                    score -= 10
                scoped_filter_keys = {"make", "model", "type", "category", "subcategory", "year"}
                empty_scoped_filters = sum(
                    1 for key in scoped_filter_keys if key in href_query and not href_query.get(key, "").strip()
                )
                if empty_scoped_filters:
                    score -= min(15, empty_scoped_filters * 5)

            # Penalize non-inventory links
            if any(x in href for x in ["service", "parts", "finance", "contact", "about", "specials", "privacy"]):
                score -= 20

            # Heavily penalize external links that aren't subdomains
            from urllib.parse import urlparse
            try:
                parsed_href = urlparse(a['href'])
                if parsed_href.netloc:
                    is_oem_inventory_jump = _is_oem_inventory_jump_target(parsed_href.netloc, parsed_href.path)
                    if is_oem_inventory_jump:
                        score += 80
                    if (
                        parsed_href.netloc.endswith("onewaterinventory.com")
                        and parsed_href.path.rstrip("/").lower() == "/search"
                        and "inventory" in text
                    ):
                        score += 120
                    base_netloc = urlparse(base_url).netloc
                    # If it's a completely different domain (not just a subdomain)
                    if (
                        not parsed_href.netloc.endswith(base_netloc.replace("www.", ""))
                        and not (
                            parsed_href.netloc.endswith("onewaterinventory.com")
                            and parsed_href.path.rstrip("/").lower() == "/search"
                        )
                        and not is_oem_inventory_jump
                    ):
                        score -= 50
            except Exception:
                pass

            if score > best_score and score > 0:
                best_score = score
                absolute_url = urljoin(base_url, href_raw)
                absolute_parts = urlsplit(absolute_url)
                if absolute_parts.scheme.lower() not in {"http", "https"}:
                    continue
                best_url = urlunsplit(
                    (absolute_parts.scheme, absolute_parts.netloc, absolute_parts.path, absolute_parts.query, "")
                )

        if condition == "all" and best_url:
            best_parts = urlsplit(best_url)
            best_query = {k.lower(): v.lower() for k, v in parse_qsl(best_parts.query, keep_blank_values=True)}
            if best_query:
                non_structural_keys = set(best_query) - {
                    "make",
                    "model",
                    "type",
                    "condition",
                    "category",
                    "subcategory",
                    "year",
                    "page",
                    "pg",
                }
                condition_value = best_query.get("condition", "").strip().lower()
                has_empty_filter = any(
                    key in best_query and not (best_query.get(key) or "").strip()
                    for key in ("make", "model", "type", "category", "subcategory", "year")
                )
                if not non_structural_keys and (
                    has_empty_filter or condition_value in {"pre-owned", "preowned", "used", "new"}
                ):
                    best_url = urlunsplit((best_parts.scheme, best_parts.netloc, best_parts.path, "", ""))
        if condition == "all" and best_url.rstrip("/") == base_url.rstrip("/"):
            # If scoring failed to pick a candidate but we did see inventory links, prefer
            # a broad inventory entrypoint over returning the homepage.
            for a in soup.find_all("a", href=True):
                abs_url = urljoin(base_url, str(a["href"]))
                parts = urlsplit(abs_url)
                if parts.scheme.lower() not in {"http", "https"}:
                    continue
                if "inventory" not in (parts.path or "").lower():
                    continue
                query = {k.lower(): v.lower() for k, v in parse_qsl(parts.query, keep_blank_values=True)}
                if query:
                    non_structural_keys = set(query) - {
                        "make",
                        "model",
                        "type",
                        "condition",
                        "category",
                        "subcategory",
                        "year",
                        "page",
                        "pg",
                    }
                    if non_structural_keys:
                        continue
                    condition_value = query.get("condition", "").strip().lower()
                    if any(not (query.get(k) or "").strip() for k in ("make", "model", "type")) or condition_value in {
                        "pre-owned",
                        "preowned",
                        "used",
                        "new",
                    }:
                        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
                return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        return best_url
    except Exception as e:
        logger.warning("Failed to parse inventory URL: %s", e)
        return base_url


def _dealer_inspire_model_inventory_urls(
    html: str,
    base_url: str,
    *,
    vehicle_condition: str,
    model: str = "",
) -> list[str]:
    condition = (vehicle_condition or "").strip().lower()
    root = "/used-vehicles" if condition == "used" else "/new-vehicles"
    model_tokens = _scope_filter_tokens(model)
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        abs_url = urljoin(base_url, str(a["href"]))
        path = urlsplit(abs_url).path.rstrip("/").lower()
        if not path.startswith(root + "/"):
            continue
        if path in {root, f"{root}/new-vehicle-specials"}:
            continue
        if not model_tokens and path.count("/") != 2:
            continue
        if model_tokens:
            combined = re.sub(r"[^a-z0-9]", "", f"{path} {a.get_text(strip=True).lower()}")
            if not any(token in combined for token in model_tokens):
                continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        out.append(abs_url)
    return out


def _team_velocity_model_inventory_urls(
    html: str,
    base_url: str,
    *,
    vehicle_condition: str,
    model: str = "",
) -> list[str]:
    condition = (vehicle_condition or "").strip().lower()
    if condition not in {"new", "used"}:
        return []
    target_root = f"/inventory/{condition}"
    model_tokens = _scope_filter_tokens(model)
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        abs_url = _sanitize_inventory_query_url(urljoin(base_url, str(a["href"])))
        parsed = urlsplit(abs_url)
        path = parsed.path.rstrip("/").lower()
        query = {k.lower(): v.lower() for k, v in parse_qsl(parsed.query, keep_blank_values=True)}
        if not (path.startswith(target_root + "/") or (path == "/--inventory" and model_tokens)):
            continue
        if model_tokens:
            combined = re.sub(r"[^a-z0-9]", "", f"{path} {a.get_text(strip=True).lower()} {parsed.query.lower()}")
            query_match = any(key in query for key in ("make", "model"))
            if not query_match and not any(token in combined for token in model_tokens):
                continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        out.append(abs_url)
    return out


def _listing_emit_key(v: Any) -> str:
    listing_url = str(getattr(v, "listing_url", "") or "").strip().lower()
    if listing_url:
        return f"url:{listing_url.rstrip('/')}"
    vin = str(getattr(v, "vin", "") or "").strip().lower()
    if vin:
        return f"vin:{vin}"
    vehicle_identifier = str(getattr(v, "vehicle_identifier", "") or "").strip().lower()
    if vehicle_identifier:
        return f"id:{vehicle_identifier}"
    raw_title = str(getattr(v, "raw_title", "") or "").strip().lower()
    return f"title:{raw_title}"


def _looks_like_model_index_batch(vdicts: list[dict[str, Any]], current_url: str) -> bool:
    path = urlsplit(current_url).path.rstrip("/").lower()
    if path not in {"/new-vehicles", "/used-vehicles", "/inventory/new", "/inventory/used"} or not vdicts:
        return False
    listing_urls: list[str] = []
    for row in vdicts:
        listing_url = str(row.get("listing_url") or "").strip().lower()
        if not listing_url:
            continue
        listing_urls.append(listing_url)
    if not listing_urls:
        return False
    for listing_url in listing_urls:
        listing_path = urlsplit(listing_url).path.rstrip("/").lower()
        if not listing_path.startswith(path + "/"):
            return False
        suffix = listing_path[len(path) :].strip("/")
        if not suffix:
            return False
        parts = [segment for segment in suffix.split("/") if segment]
        if not parts or len(parts) > 2:
            return False
        if any(
            token in listing_path
            for token in ("/viewdetails/", "/vehicle-details/", "/detail/", "/vdp/")
        ):
            return False
    return True


def _needs_vdp_enrichment(vehicles: list[VehicleListing]) -> bool:
    if not vehicles:
        return False
    missing_details = 0
    for v in vehicles:
        if (
            v.price is None
            and v.mileage is None
            and not v.availability_status
            and not v.inventory_location
            and bool(v.listing_url)
        ):
            missing_details += 1
    return missing_details >= max(1, len(vehicles) // 2)


def _needs_vdp_attribute_enrichment(vehicles: list[VehicleListing]) -> bool:
    if not vehicles:
        return False
    missing_fields = 0
    for v in vehicles:
        if not v.listing_url:
            continue
        if (not v.exterior_color) or (not v.availability_status) or (not v.inventory_location):
            missing_fields += 1
    return missing_fields >= max(1, len(vehicles) // 2)


def _needs_vdp_usage_enrichment(vehicles: list[VehicleListing]) -> bool:
    if not vehicles:
        return False
    candidates = [v for v in vehicles if v.listing_url]
    if not candidates:
        return False
    missing_usage = 0
    for v in candidates:
        if (v.usage_value is not None) or (v.mileage is not None):
            continue
        condition = (v.vehicle_condition or "").strip().lower()
        if condition and condition != "used":
            continue
        missing_usage += 1
    return missing_usage >= max(1, len(candidates) // 2)


def _price_fill_rate(listings: list[dict[str, Any]]) -> float:
    if not listings:
        return 0.0
    with_price = 0
    for listing in listings:
        price = listing.get("price")
        if isinstance(price, (int, float)) and float(price) > 0:
            with_price += 1
    return with_price / len(listings)


def _vin_fill_rate(listings: list[dict[str, Any]]) -> float:
    if not listings:
        return 0.0
    with_vin = 0
    for listing in listings:
        vin = str(listing.get("vin") or "").strip()
        identifier = str(listing.get("vehicle_identifier") or "").strip()
        if vin or identifier:
            with_vin += 1
    return with_vin / len(listings)


def _is_harley_search(make: str, route: ProviderRoute | None) -> bool:
    make_norm = re.sub(r"[^a-z0-9]", "", (make or "").lower())
    if "harley" in make_norm:
        return True
    return bool(route and route.platform_id == "harley_digital_showroom")


def _effective_absolute_page_cap(
    base_cap: int,
    *,
    make: str,
    route: ProviderRoute | None,
) -> int:
    cap = max(1, int(base_cap))
    if _is_harley_search(make, route) and route and route.platform_id in {"shift_digital", "harley_digital_showroom"}:
        harley_cap = max(1, int(getattr(settings, "harley_search_max_pages_per_dealer_cap", 24)))
        return max(cap, harley_cap)
    return cap


def _needs_harley_vdp_enrichment(vehicles: list[VehicleListing]) -> bool:
    if not vehicles:
        return False
    missing_price = 0
    missing_core = 0
    for v in vehicles:
        if not v.listing_url:
            continue
        if v.price is None:
            missing_price += 1
        if (not v.vin) or (not v.exterior_color) or (not v.availability_status):
            missing_core += 1
    threshold = max(1, len(vehicles) // 2)
    return missing_price >= threshold or missing_core >= threshold


def _first_dollar_amount(text: str) -> float | None:
    m = re.search(r"\$([0-9][0-9,]{2,})(?:\.\d{2})?", text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _extract_room58_tracking_payload(html: str) -> dict[str, Any] | None:
    m = re.search(
        r"TRACKING_DATA_LAYER\s*=\s*(\{.*?\})\s*;\s*(?:\(|window\.)",
        html,
        re.S,
    )
    if not m:
        return None
    try:
        payload = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _room58_detail_overlay(v: VehicleListing, html: str) -> VehicleListing | None:
    if not v.listing_url:
        return None
    try:
        parts = urlsplit(v.listing_url)
    except Exception:
        return None
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    if "harley" not in host:
        return None

    overlay_data: dict[str, Any] = {}
    id_match = re.search(r"/inventory/(\d+)(?:/|$)", parts.path.lower())
    if id_match:
        overlay_data["vehicle_identifier"] = id_match.group(1)

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = None
    if soup is not None:
        price_el = soup.select_one(".inventoryModel-details-price")
        msrp_el = soup.select_one(".inventoryModel-details-priceOld")
        if price_el is not None:
            price_val = _first_dollar_amount(price_el.get_text(" ", strip=True))
            if price_val is not None and price_val > 0:
                overlay_data["price"] = price_val
        if msrp_el is not None:
            msrp_val = _first_dollar_amount(msrp_el.get_text(" ", strip=True))
            if msrp_val is not None and msrp_val > 0:
                overlay_data["msrp"] = msrp_val
        if (
            overlay_data.get("price") is not None
            and overlay_data.get("msrp") is not None
            and overlay_data["msrp"] > overlay_data["price"]
        ):
            overlay_data["dealer_discount"] = overlay_data["msrp"] - overlay_data["price"]

    tracking = _extract_room58_tracking_payload(html)
    if tracking:
        details = tracking.get("vehicleDetails") if isinstance(tracking.get("vehicleDetails"), dict) else {}
        if not details and isinstance(tracking.get("formVehicle"), dict):
            details = tracking.get("formVehicle") or {}
        vin = str(details.get("vin") or "").strip()
        if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin.upper()):
            overlay_data["vin"] = vin.upper()
            overlay_data["vehicle_identifier"] = vin.upper()
        color = str(details.get("exteriorColor") or "").strip()
        if color:
            overlay_data["exterior_color"] = color
        status = str(details.get("status") or "").strip()
        if status:
            overlay_data["availability_status"] = status
            status_l = status.lower()
            if "new" in status_l:
                overlay_data["vehicle_condition"] = "new"
            elif "used" in status_l or "pre-owned" in status_l or "preowned" in status_l:
                overlay_data["vehicle_condition"] = "used"
        make = str(details.get("make") or "").strip()
        model = str(details.get("model") or "").strip()
        year_raw = str(details.get("year") or "").strip()
        if make:
            overlay_data["make"] = make
        if model:
            overlay_data["model"] = model
        if year_raw.isdigit():
            year_int = int(year_raw)
            if 1900 <= year_int <= 2100:
                overlay_data["year"] = year_int
        dealer_name = str(tracking.get("dealerName") or "").strip()
        dealer_city = str(tracking.get("dealerCity") or "").strip()
        dealer_state = str(tracking.get("dealerState") or "").strip()
        location = dealer_name
        if dealer_city and dealer_state:
            location = f"{dealer_name} ({dealer_city}, {dealer_state})" if dealer_name else f"{dealer_city}, {dealer_state}"
        elif dealer_city and dealer_name:
            location = f"{dealer_name} ({dealer_city})"
        if location:
            overlay_data["inventory_location"] = location

    if not overlay_data:
        return None
    return VehicleListing(
        vehicle_category=v.vehicle_category or "car",
        listing_url=v.listing_url,
        **overlay_data,
    )


def _generic_vehicle_detail_overlay(v: VehicleListing, html: str) -> VehicleListing | None:
    if not v.listing_url or not parser_monolith._page_looks_like_vehicle_detail(v.listing_url, html):
        return None

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return None

    page_text = soup.get_text(" ", strip=True)
    if not page_text:
        return None

    overlay_data: dict[str, Any] = {}
    raw_title: str | None = None

    title_node = soup.find("h1")
    if title_node is not None:
        raw_title = title_node.get_text(" ", strip=True)
    if not raw_title:
        meta = soup.find("meta", attrs={"property": "og:title"})
        if meta is not None and meta.get("content"):
            raw_title = str(meta.get("content")).strip()
    if not raw_title and soup.title is not None:
        raw_title = soup.title.get_text(" ", strip=True)
    if raw_title:
        raw_title = re.sub(r"\s+", " ", raw_title).strip()
        raw_title = re.split(r"\s+[|:-]\s+", raw_title, maxsplit=1)[0].strip()
        overlay_data["raw_title"] = raw_title
        normalized_title = re.sub(
            r"^(?:certified\s+pre[-\s]?owned|certified|cpo|used|new)\s+",
            "",
            raw_title,
            flags=re.I,
        )
        title_fields = parser_monolith._parse_title_fields(normalized_title)
        year = parser_monolith._coerce_int(title_fields.get("year"))
        if year is not None:
            overlay_data["year"] = year
        if title_fields.get("make"):
            overlay_data["make"] = str(title_fields["make"]).strip()
        if title_fields.get("model"):
            overlay_data["model"] = str(title_fields["model"]).strip()
        if title_fields.get("trim"):
            overlay_data["trim"] = str(title_fields["trim"]).strip()

    usage_value, usage_unit = parser_monolith._pick_usage_from_dict(
        {},
        vehicle_category=v.vehicle_category or "car",
        fallback_text=page_text,
    )
    if usage_value is not None and usage_unit is not None:
        overlay_data["usage_value"] = usage_value
        overlay_data["usage_unit"] = usage_unit
        if usage_unit == "miles":
            overlay_data["mileage"] = usage_value

    vin = parser_monolith._extract_vin_from_text(page_text)
    if vin:
        overlay_data["vin"] = vin
        overlay_data["vehicle_identifier"] = vin
    else:
        stock_number = parser_monolith._extract_stock_number_from_text(page_text)
        if stock_number:
            overlay_data["vehicle_identifier"] = stock_number

    condition = (
        normalize_vehicle_condition(raw_title)
        or normalize_vehicle_condition(page_text)
        or normalize_vehicle_condition(v.listing_url)
    )
    if condition:
        overlay_data["vehicle_condition"] = condition

    if not overlay_data:
        return None
    return VehicleListing(
        vehicle_category=v.vehicle_category or "car",
        listing_url=v.listing_url,
        **overlay_data,
    )


def _effective_dealer_timeout(
    requested_pages: int,
    *,
    dealer_score: float | None = None,
    failure_streak: int = 0,
) -> float:
    base_timeout = max(30.0, settings.dealership_timeout)
    if requested_pages >= 8:
        base_timeout = max(base_timeout, 240.0)
    elif requested_pages >= 5:
        base_timeout = max(base_timeout, 195.0)
    score = float(NO_SCORE_DEFAULT if dealer_score is None else dealer_score)
    low_score_threshold = float(getattr(settings, "dealer_score_budget_low_threshold", 40.0) or 40.0)
    streak_threshold = max(1, int(getattr(settings, "dealer_failure_streak_budget_threshold", 2) or 0))
    if failure_streak >= streak_threshold and score < low_score_threshold:
        return max(45.0, min(base_timeout, base_timeout * 0.55))
    if failure_streak >= streak_threshold:
        return max(50.0, min(base_timeout, base_timeout * 0.65))
    if score < low_score_threshold:
        return max(60.0, min(base_timeout, base_timeout * 0.75))
    return base_timeout


def _dealer_budget_page_cap(
    requested_pages: int,
    *,
    dealer_score: float | None = None,
    failure_streak: int = 0,
) -> int:
    cap = max(1, int(requested_pages or 1))
    score = float(NO_SCORE_DEFAULT if dealer_score is None else dealer_score)
    low_score_threshold = float(getattr(settings, "dealer_score_budget_low_threshold", 40.0) or 40.0)
    streak_threshold = max(1, int(getattr(settings, "dealer_failure_streak_budget_threshold", 2) or 0))
    if failure_streak >= streak_threshold and score < low_score_threshold:
        return min(cap, 1)
    if failure_streak >= streak_threshold or score < low_score_threshold:
        return min(cap, 2)
    return cap


def _effective_max_pages_for_route(
    requested_pages: int,
    route: ProviderRoute | None,
) -> int:
    """
    Return the initial page budget before site-driven auto-expansion.

    Searches still start from the caller's requested depth so short searches stay
    short when pagination clues are absent, but the pagination loop may raise the
    budget later when the site explicitly reports more result pages.
    """
    if requested_pages <= 0:
        return 1
    if route is not None and route.platform_id == "dealer_on":
        # DealerOn SRPs are render-heavy. Cap initial depth so slow dealers
        # don't consume the full worker budget.
        return min(requested_pages, 3)
    if route is not None and route.platform_id == "dealer_inspire":
        # Dealer Inspire consumes 7 ZenRows rendered calls per dealer on broad Ford searches
        # (45-page result sets), starving later dealers in the queue. Cap initial depth to
        # 2 pages — pagination auto-expansion still runs if the first pages succeed quickly.
        return min(requested_pages, 2)
    return requested_pages


def _pagination_target_pages(pagination: PaginationInfo | None) -> int | None:
    if pagination is None:
        return None
    if pagination.total_pages is not None and pagination.total_pages > 0:
        return pagination.total_pages
    if (
        pagination.total_results is not None
        and pagination.page_size is not None
        and pagination.page_size > 0
    ):
        return max(1, (pagination.total_results + pagination.page_size - 1) // pagination.page_size)
    return None


def _expand_page_budget(
    current_budget: int,
    *,
    pagination: PaginationInfo | None,
    has_pending_urls: bool,
    absolute_cap: int,
) -> int:
    budget = max(1, min(current_budget, absolute_cap))
    target_pages = _pagination_target_pages(pagination)
    if target_pages is not None:
        budget = max(budget, min(target_pages, absolute_cap))
    if has_pending_urls and budget < absolute_cap:
        budget += 1
    return budget


def _pagination_progress_payload(
    pagination: PaginationInfo | None,
    *,
    pages_scraped: int | None = None,
) -> dict[str, Any]:
    if pagination is None and pages_scraped is None:
        return {}
    payload: dict[str, Any] = {}
    if pages_scraped is not None and pages_scraped >= 0:
        payload["pages_scraped"] = pages_scraped
    if pagination is None:
        return payload
    target_pages = _pagination_target_pages(pagination)
    if pagination.current_page is not None:
        payload["current_page_number"] = pagination.current_page
    if target_pages is not None:
        payload["reported_total_pages"] = target_pages
    if pagination.total_results is not None:
        payload["reported_total_results"] = pagination.total_results
    if pagination.page_size is not None:
        payload["reported_page_size"] = pagination.page_size
    if pagination.source:
        payload["pagination_source"] = pagination.source
    return payload


def _drop_query_keys(url: str, keys: set[str]) -> str:
    parts = urlsplit(url)
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in keys
    ]
    query = urlencode(query_pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _with_query_params(url: str, updates: dict[str, str]) -> str:
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in updates.items():
        value_s = str(value or "").strip()
        if value_s:
            params[key] = value_s
    query = urlencode(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _inventory_url_recovery_candidates(
    *,
    inv_url: str,
    base_url: str,
    route: ProviderRoute | None,
    make: str,
    model: str,
    vehicle_condition: str,
    fallback_zip: str | None = None,
    fallback_range_miles: int | None = None,
) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = {inv_url.rstrip("/")}

    def add(url: str | None) -> None:
        if not url:
            return
        norm = url.rstrip("/")
        if not norm or norm in seen:
            return
        seen.add(norm)
        candidates.append(url)

    condition = (vehicle_condition or "all").strip().lower()
    parsed_base = urlsplit(inv_url or base_url)
    if not parsed_base.scheme or not parsed_base.netloc:
        parsed_base = urlsplit(base_url)
    model_values = _requested_model_values(model)
    make_norm = re.sub(r"[^a-z0-9]+", "-", make.strip().lower()).strip("-")

    if route and route.platform_id == "dealer_on":
        path = "/searchused.aspx" if condition == "used" else "/searchnew.aspx"
        canonical = urlunsplit((parsed_base.scheme, parsed_base.netloc, path, "", ""))
        if model_values:
            for m in model_values[:2]:
                add(_with_query_params(canonical, {"Make": make, "Model": m, "ModelAndTrim": m}))
        add(_with_query_params(canonical, {"Make": make}))
    elif route and route.platform_id == "dealer_inspire":
        path = "/used-vehicles/" if condition == "used" else "/new-vehicles/"
        canonical = urlunsplit((parsed_base.scheme, parsed_base.netloc, path, "", ""))
        base_updates: dict[str, str] = {}
        if condition == "new":
            base_updates["_dFR[type][0]"] = "New"
        elif condition == "used":
            base_updates["_dFR[type][0]"] = "Used"
        if make.strip():
            base_updates["_dFR[make][0]"] = make.strip()
        if model_values:
            for m in model_values[:2]:
                updates = dict(base_updates)
                updates["_dFR[model][0]"] = m
                add(_with_query_params(canonical, updates))
        add(_with_query_params(canonical, base_updates))
        add(canonical)
    elif route and route.platform_id == "dealer_dot_com":
        if condition == "used":
            path = "/used-inventory/index.htm"
        elif condition == "all":
            path = "/all-inventory/index.htm"
        else:
            path = "/new-inventory/index.htm"
        canonical = urlunsplit((parsed_base.scheme, parsed_base.netloc, path, "", ""))
        if model_values:
            for m in model_values[:2]:
                add(_with_query_params(canonical, {"make": make, "model": m}))
        add(_with_query_params(canonical, {"make": make}))
    elif route and route.platform_id in {
        "ford_family_inventory",
        "gm_family_inventory",
        "honda_acura_inventory",
        "toyota_lexus_oem_inventory",
    }:
        inv_path = "/inventory/used" if condition == "used" else "/inventory/new"
        broad_srp = urlunsplit((parsed_base.scheme, parsed_base.netloc, inv_path, "", ""))
        if model_values and make_norm:
            for m in model_values[:2]:
                model_norm = re.sub(r"[^a-z0-9]+", "-", m.strip().lower()).strip("-")
                if model_norm:
                    if route.platform_id == "ford_family_inventory":
                        for candidate in _build_family_inventory_path_variants(
                            urlunsplit((parsed_base.scheme, parsed_base.netloc, inv_path, "", "")),
                            make,
                            m,
                            condition=condition,
                        ):
                            add(candidate)
                    else:
                        add(urlunsplit((parsed_base.scheme, parsed_base.netloc, f"{inv_path}/{make_norm}-{model_norm}", "", "")))
        add(broad_srp)
    elif route and route.platform_id == "tesla_inventory":
        for candidate in _tesla_inventory_urls(
            inv_url or base_url,
            vehicle_condition=condition,
            model=model_values[0] if model_values else "",
            fallback_zip=fallback_zip,
            fallback_range_miles=fallback_range_miles,
        ):
            add(candidate)
    elif not route:
        canonical = guess_franchise_inventory_srp_url(base_url, condition) or ""
        if canonical:
            parsed_canonical = urlsplit(canonical)
            path = parsed_canonical.path.rstrip("/").lower()
            if path in {"/inventory/new", "/inventory/used"}:
                for m in model_values[:2]:
                    model_norm = re.sub(r"[^a-z0-9]+", "-", m.strip().lower()).strip("-")
                    if not make_norm or not model_norm:
                        continue
                    add(urlunsplit((parsed_canonical.scheme, parsed_canonical.netloc, f"{path}/{make_norm}-{model_norm}", "", "")))
        for candidate in speculative_inventory_urls_for_unknown_site(
            base_url,
            condition,
            make=make,
            model=model,
        ):
            add(candidate)

    # Cross-stack safety net for misdetected inventory routes (common on express.* sites):
    # try generic OEM and Dealer.com canonical SRP paths on both current and www hosts.
    try:
        parsed_inv = urlsplit(inv_url or base_url)
        candidate_hosts = [parsed_inv.netloc]
        host_only = parsed_inv.netloc.lower().split("@")[-1].split(":")[0]
        if host_only.startswith("express."):
            base_host = host_only.removeprefix("express.")
            if base_host:
                candidate_hosts.append(f"www.{base_host}")
        generic_paths: list[str] = []
        if condition == "used":
            generic_paths.extend(("/inventory/used", "/used-inventory/index.htm"))
        elif condition == "all":
            generic_paths.extend(("/inventory/new", "/all-inventory/index.htm"))
        else:
            generic_paths.extend(("/inventory/new", "/new-inventory/index.htm"))
        for host in candidate_hosts:
            for path in generic_paths:
                add(urlunsplit((parsed_inv.scheme or "https", host, path, "", "")))
    except Exception:
        pass

    add(guess_franchise_inventory_srp_url(base_url, vehicle_condition))
    return candidates


def _bounded_phase_timeout(
    *,
    base_timeout: float,
    dealer_timeout: float,
    elapsed_seconds: float,
    reserve_seconds: float = 8.0,
    min_timeout: float = 5.0,
) -> float | None:
    """
    Cap a phase timeout (fetch/parse) to the remaining per-dealer budget.

    Returning None signals there is not enough budget left to start a safe phase.
    """
    remaining = max(0.0, float(dealer_timeout) - float(elapsed_seconds) - max(0.0, float(reserve_seconds)))
    if remaining < min_timeout:
        return None
    return max(min_timeout, min(float(base_timeout), remaining))


def _cap_unknown_platform_fetch_timeout(
    base_timeout: float,
    *,
    page_kind: PageKind,
    platform_id: str | None,
) -> float:
    if platform_id is not None:
        return float(base_timeout)
    if page_kind == "homepage":
        return min(float(base_timeout), 45.0)
    if page_kind == "inventory":
        return min(float(base_timeout), 55.0)
    return float(base_timeout)


def _merge_vehicle_detail(base: VehicleListing, enriched: VehicleListing) -> VehicleListing:
    base_data = base.model_dump()
    enriched_data = enriched.model_dump()
    merged = dict(base_data)
    for key, value in enriched_data.items():
        if value in (None, "", [], {}):
            continue
        current = merged.get(key)
        if current in (None, "", [], {}):
            merged[key] = value
    return VehicleListing(**merged)


async def _enrich_vehicle_from_vdp(
    v: VehicleListing,
    *,
    prefer_detail_overlay: bool = False,
) -> VehicleListing:
    if not v.listing_url:
        return v
    try:
        html, _ = await fetch_page_html(v.listing_url, page_kind="inventory", prefer_render=False)
        detail_overlay, ext = await asyncio.to_thread(
            _extract_vdp_overlay_and_listings,
            vehicle=v,
            html=html,
            prefer_detail_overlay=prefer_detail_overlay,
        )
    except Exception:
        return v
    if not ext:
        return _merge_vehicle_detail(v, detail_overlay) if detail_overlay else v
    candidates = ext.vehicles
    if v.vehicle_identifier:
        for candidate in candidates:
            if (
                candidate.vehicle_identifier
                and candidate.vehicle_identifier.upper() == v.vehicle_identifier.upper()
            ):
                enriched = _merge_vehicle_detail(v, candidate)
                return _merge_vehicle_detail(enriched, detail_overlay) if detail_overlay else enriched
    if v.vin:
        for candidate in candidates:
            if candidate.vin and candidate.vin.upper() == v.vin.upper():
                enriched = _merge_vehicle_detail(v, candidate)
                return _merge_vehicle_detail(enriched, detail_overlay) if detail_overlay else enriched
    if v.listing_url:
        for candidate in candidates:
            if candidate.listing_url and candidate.listing_url.rstrip("/") == v.listing_url.rstrip("/"):
                enriched = _merge_vehicle_detail(v, candidate)
                return _merge_vehicle_detail(enriched, detail_overlay) if detail_overlay else enriched
    if detail_overlay:
        return _merge_vehicle_detail(v, detail_overlay)
    if candidates:
        return _merge_vehicle_detail(v, candidates[0])
    return v


def _extract_vdp_overlay_and_listings(
    *,
    vehicle: VehicleListing,
    html: str,
    prefer_detail_overlay: bool,
) -> tuple[VehicleListing | None, ExtractionResult | None]:
    detail_overlay = _room58_detail_overlay(vehicle, html) if prefer_detail_overlay else None
    generic_overlay = _generic_vehicle_detail_overlay(vehicle, html)
    if detail_overlay is not None and generic_overlay is not None:
        detail_overlay = _merge_vehicle_detail(detail_overlay, generic_overlay)
    elif generic_overlay is not None:
        detail_overlay = generic_overlay
    ext = try_extract_vehicles_without_llm(
        page_url=vehicle.listing_url or "",
        html=html,
        make_filter=vehicle.make or "",
        model_filter="",
        vehicle_category=vehicle.vehicle_category or "car",
    )
    return detail_overlay, ext


def _extract_canonical_homepage_url(html: str) -> str | None:
    try:
        soup = BeautifulSoup(html, "lxml")
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            canonical_href = canonical["href"].strip()
            if canonical_href.startswith("http"):
                return canonical_href
    except Exception:
        return None
    return None


def _extract_inventory_page_sync(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
    vehicle_category: str,
    platform_id: str | None,
) -> tuple[ExtractionResult | None, str | None]:
    ext_result = extract_with_provider(
        platform_id,
        page_url=page_url,
        html=html,
        make_filter=make_filter,
        model_filter=model_filter,
        vehicle_category=vehicle_category,
    )
    if ext_result is not None:
        return ext_result, f"provider:{platform_id}" if platform_id else "provider"

    ext_result = try_extract_vehicles_without_llm(
        page_url=page_url,
        html=html,
        make_filter=make_filter,
        model_filter=model_filter,
        vehicle_category=vehicle_category,
        platform_id=platform_id,
    )
    return ext_result, "structured" if ext_result is not None else None


def _chunk_listings(rows: list[dict[str, Any]], size: int = _STREAM_LISTING_BATCH_SIZE) -> list[list[dict[str, Any]]]:
    if size <= 0 or len(rows) <= size:
        return [rows]
    return [rows[i : i + size] for i in range(0, len(rows), size)]


async def stream_search(
    location: str,
    make: str,
    model: str,
    *,
    vehicle_category: str = "car",
    vehicle_condition: str = "all",
    radius_miles: int = 50,
    inventory_scope: str = "all",
    prefer_small_dealers: bool = False,
    max_dealerships: int | None = None,
    max_pages_per_dealer: int | None = None,
    outcome_holder: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    recorder: ScrapeRunRecorder | None = None,
    market_region: str = "us",
) -> AsyncIterator[str]:
    """
    Yield SSE-formatted strings: status, dealership, vehicles, error, done.
    """
    cid_log = f"[{correlation_id}] " if correlation_id else ""
    mr = (market_region or "us").strip().lower()
    if mr not in ("us", "eu"):
        mr = "us"
    market_region = mr
    logger.info(
        f"{cid_log}Starting search: location={location}, category={vehicle_category}, make={make}, model={model}, region={market_region}"
    )
    if recorder is not None:
        recorder.event(
            event_type="search_started",
            phase="search",
            level="info",
            message="Search started.",
            payload={
                "location": location,
                "make": make,
                "model": model,
                "vehicle_category": vehicle_category,
                "vehicle_condition": vehicle_condition,
                "inventory_scope": inventory_scope,
                "prefer_small_dealers": prefer_small_dealers,
                "radius_miles": radius_miles,
                "market_region": market_region,
            },
        )
    requested_dealerships = max(1, min(max_dealerships or settings.max_dealerships, 20))
    requested_pages = max(
        1,
        min(
            max_pages_per_dealer or settings.max_pages_per_dealer,
            settings.search_max_pages_per_dealer_cap,
        ),
    )
    t0 = time.perf_counter()
    fetch_metrics: dict[str, int] = defaultdict(int)
    extraction_metrics: dict[str, int] = defaultdict(int)
    warmed_inventory_cache: dict[str, dict[str, Any] | None] = {}
    platform_cache_entries: dict[str, Any] = {}
    dealer_score_cards: dict[str, DealerScoreCard] = {}
    dealer_last_fetch_method: dict[str, str] = {}
    places_metrics = PlacesSearchMetrics()
    candidate_limit = min(requested_dealerships * max(1, settings.places_candidate_limit_multiplier), 30)
    historical_snapshot_pool: list[dict[str, Any]] = []
    historical_snapshot_pool_loaded = False
    completed_dealer_count = 0
    successful_dealer_count = 0
    streamed_vehicle_count = 0

    def _load_historical_snapshot_pool() -> list[dict[str, Any]]:
        nonlocal historical_snapshot_pool_loaded, historical_snapshot_pool
        if historical_snapshot_pool_loaded:
            return historical_snapshot_pool
        historical_snapshot_pool_loaded = True
        if recorder is None or recorder.user_id is None:
            return historical_snapshot_pool
        try:
            prior_runs = recorder.store.list_scrape_runs(user_id=recorder.user_id, limit=30)
        except Exception:
            return historical_snapshot_pool
        aggregated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for run in prior_runs:
            if correlation_id and getattr(run, "correlation_id", None) == correlation_id:
                continue
            observed_at = getattr(run, "started_at", None)
            snapshot = getattr(run, "listings_snapshot", None)
            if not isinstance(snapshot, list):
                continue
            for item in snapshot:
                if not isinstance(item, dict):
                    continue
                identity = "|".join(
                    [
                        str(item.get("vin") or "").strip().upper(),
                        str(item.get("vehicle_identifier") or "").strip().upper(),
                        str(item.get("listing_url") or "").strip().lower(),
                        str(item.get("price") or "").strip(),
                    ]
                )
                if identity in seen:
                    continue
                seen.add(identity)
                enriched_item = dict(item)
                if observed_at is not None:
                    enriched_item["_market_observed_at"] = observed_at
                aggregated.append(enriched_item)
                if len(aggregated) >= 4000:
                    break
            if len(aggregated) >= 4000:
                break
        historical_snapshot_pool = aggregated
        return historical_snapshot_pool

    def _score_card_for_domain(domain: str) -> DealerScoreCard:
        return dealer_score_cards.get(domain, DealerScoreCard())

    def _current_economics_snapshot() -> dict[str, Any]:
        return build_search_economics(
            fetch_metrics=dict(fetch_metrics),
            extraction_metrics=dict(extraction_metrics),
            places_metrics=places_metrics.as_dict(),
            requested_dealerships=requested_dealerships,
            requested_pages=requested_pages,
            radius_miles=radius_miles,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            vehicle_condition=vehicle_condition,
            inventory_scope=inventory_scope,
            ok=True,
        )

    def _search_has_budget_relief_targets() -> bool:
        enough_dealers = completed_dealer_count >= max(
            1,
            int(getattr(settings, "search_budget_relief_dealer_target", 2) or 0),
        )
        enough_vehicles = streamed_vehicle_count >= max(
            1,
            int(getattr(settings, "search_budget_relief_vehicle_target", 40) or 0),
        )
        return enough_dealers or enough_vehicles

    def _search_budget_pressure() -> bool:
        economics = _current_economics_snapshot()
        drivers = economics.get("drivers", {})
        return (
            float(economics.get("cost_driver_units") or 0.0)
            >= float(getattr(settings, "search_cost_soft_limit_units", 28.0) or 0.0)
            or int(drivers.get("managed_fetch_events") or 0)
            >= max(1, int(getattr(settings, "search_managed_fetch_budget", 18) or 0))
            or int(drivers.get("pages_llm") or 0)
            >= max(1, int(getattr(settings, "search_llm_page_budget", 12) or 0))
        )

    def _dealer_budget_relief_active(score_card: DealerScoreCard) -> bool:
        if not _search_has_budget_relief_targets() or not _search_budget_pressure():
            return False
        return (
            float(score_card.score) < float(getattr(settings, "dealer_score_budget_low_threshold", 40.0) or 40.0)
            or int(score_card.failure_streak or 0)
            >= max(1, int(getattr(settings, "dealer_failure_streak_budget_threshold", 2) or 0))
        )

    def finalize_done(base: dict[str, Any], *, ok: bool, status: str | None = None) -> dict[str, Any]:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        md = int(base.get("max_dealerships", requested_dealerships))
        mp = int(base.get("max_pages_per_dealer", requested_pages))
        rm = int(base.get("radius_miles", radius_miles))
        vc = str(base.get("vehicle_condition", vehicle_condition))
        invs = str(base.get("inventory_scope", inventory_scope))
        economics = build_search_economics(
            fetch_metrics=dict(fetch_metrics),
            extraction_metrics=dict(extraction_metrics),
            places_metrics=places_metrics.as_dict(),
            requested_dealerships=md,
            requested_pages=mp,
            radius_miles=rm,
            duration_ms=duration_ms,
            vehicle_condition=vc,
            inventory_scope=invs,
            ok=ok,
        )
        payload = {
            **base,
            **(recorder.summary_metrics() if recorder is not None else {}),
            "duration_ms": duration_ms,
            "places_metrics": places_metrics.as_dict(),
            "economics": economics,
            "correlation_id": correlation_id,
        }
        if outcome_holder is not None:
            outcome_holder.clear()
            outcome_holder.update(payload)
        log_economics_line(logger, economics, user_hint=cid_log.strip())
        logger.info(f"{cid_log}Search finished: ok={ok}, duration={duration_ms}ms")
        if recorder is not None:
            recorder.event(
                event_type="search_finished",
                phase="search",
                level="info",
                message=f"Search finished with ok={ok}.",
                payload=payload,
            )
            recorder.finalize(
                ok=ok,
                summary=payload,
                economics=economics,
                error_message=str(base.get("error_message")) if base.get("error_message") else None,
                status=status,
            )
        return payload

    def search_failure_payload(
        error: SearchErrorInfo,
        *,
        base: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        merged = {"ok": False, **(base or {})}
        merged["status"] = status or error.status
        return with_search_error(merged, error.with_correlation_id(correlation_id))

    if _is_tesla_make(make):
        error = SearchErrorInfo(
            code="search.unsupported_tesla",
            message=(
                "Tesla inventory is temporarily unsupported. Tesla's national inventory pages are currently "
                "served behind Akamai challenge pages even on ZIP-scoped URLs, so we cannot return reliable "
                "results without wasting search time and cost."
            ),
            phase="search",
        )
        if recorder is not None:
            recorder.event(
                event_type="search_unsupported",
                phase="search",
                level="warning",
                message=error.message,
                payload={"make": make, "model": model, "location": location, "error": error.to_summary()},
            )
        yield sse_pack("search_error", error.with_correlation_id(correlation_id).to_payload())
        yield sse_pack(
            "done",
            finalize_done(
                search_failure_payload(
                    error,
                    base={
                        "dealerships": 0,
                        "dealer_discovery_count": 0,
                        "dealer_deduped_count": 0,
                        "radius_miles": radius_miles,
                        "vehicle_condition": vehicle_condition,
                        "inventory_scope": inventory_scope,
                        "max_dealerships": requested_dealerships,
                        "max_pages_per_dealer": requested_pages,
                        "effective_search_concurrency": 0,
                    },
                ),
                ok=False,
                status="failed",
            ),
        )
        return

    yield sse_pack("status", {"message": "Finding local dealerships…", "phase": "places"})

    async def _discover_dealers(*, query_variant_limit: int | None = None) -> list[DealershipFound]:
        locations = [loc.strip() for loc in location.split("|") if loc.strip()]
        if not locations:
            locations = [location]
        if len(locations) > 5:
            locations = locations[:5]

        async def _fetch_for_loc(
            loc: str,
            *,
            location_center_override: tuple[float, float] | None = None,
        ) -> list[DealershipFound]:
            if (vehicle_category or "car").strip().lower() == "car":
                return await find_car_dealerships(
                    loc,
                    make=make,
                    model=model,
                    prefer_small_dealers=prefer_small_dealers,
                    limit=candidate_limit,
                    radius_miles=radius_miles,
                    market_region=market_region,
                    metrics=places_metrics,
                    query_variant_limit=query_variant_limit,
                    location_center_override=location_center_override,
                )
            return await find_dealerships(
                loc,
                make=make,
                model=model,
                vehicle_category=vehicle_category,
                prefer_small_dealers=prefer_small_dealers,
                limit=candidate_limit,
                radius_miles=radius_miles,
                market_region=market_region,
                metrics=places_metrics,
                query_variant_limit=query_variant_limit,
                location_center_override=location_center_override,
            )

        async def _fetch_for_locations(
            loc_list: list[str],
            *,
            location_center_override: tuple[float, float] | None = None,
        ) -> list[DealershipFound]:
            results = await asyncio.gather(
                *[
                    _fetch_for_loc(
                        loc,
                        location_center_override=location_center_override,
                    )
                    for loc in loc_list
                ]
            )
            all_dealers: list[DealershipFound] = []
            seen_place_ids: set[str] = set()
            for dealers in results:
                for d in dealers:
                    if d.place_id not in seen_place_ids:
                        seen_place_ids.add(d.place_id)
                        all_dealers.append(d)
            return all_dealers

        all_dealers = await _fetch_for_locations(locations)
        should_expand_locations = (
            len(locations) == 1
            and radius_miles >= 150
            and bool((make or "").strip() or (model or "").strip())
            and len(all_dealers) < min(6, candidate_limit)
        )
        if should_expand_locations:
            base_location_center = await resolve_search_location_center(
                locations[0],
                metrics=places_metrics,
            )
            expanded_locations = await expand_large_radius_search_locations(
                locations[0],
                radius_miles=radius_miles,
                market_region=market_region,
                max_locations=5,
                metrics=places_metrics,
            )
            extra_locations = [loc for loc in expanded_locations if loc not in locations]
            if extra_locations:
                all_dealers = await _fetch_for_locations(
                    locations + extra_locations,
                    location_center_override=base_location_center,
                )
        return all_dealers

    async def _warm_dealer_metadata(candidate_dealers: list[DealershipFound]) -> None:
        dealer_domains = [normalize_dealer_domain((dealer.website or "").strip()) for dealer in candidate_dealers]
        missing_domains = sorted({domain for domain in dealer_domains if domain and domain not in platform_cache_entries})
        if missing_domains:
            platform_entries = await asyncio.gather(
                *(asyncio.to_thread(platform_store.get, domain) for domain in missing_domains)
            )
            platform_cache_entries.update(
                {
                    domain: entry
                    for domain, entry in zip(missing_domains, platform_entries, strict=False)
                    if entry is not None
                }
            )
        if settings.inventory_cache_enabled and candidate_dealers:
            cache_warm_pairs: list[tuple[str, str]] = []
            for dealer in candidate_dealers:
                website = prefer_https_website_url((dealer.website or "").strip())
                domain = normalize_dealer_domain(website)
                inv_cache_key = inventory_listings_cache_key(
                    website=website,
                    domain=domain,
                    make=make,
                    model=model,
                    vehicle_category=vehicle_category,
                    vehicle_condition=vehicle_condition,
                    inventory_scope=inventory_scope,
                    max_pages=requested_pages,
                )
                if inv_cache_key in warmed_inventory_cache:
                    continue
                cache_warm_pairs.append((inv_cache_key, website))
            if cache_warm_pairs:
                cache_warm_results = await asyncio.gather(
                    *[
                        asyncio.to_thread(get_inventory_cache_entry, cache_key, allow_stale=True)
                        for cache_key, _website in cache_warm_pairs
                    ]
                )
                warmed_inventory_cache.update(
                    {
                        cache_key: cached
                        for (cache_key, _website), cached in zip(cache_warm_pairs, cache_warm_results, strict=False)
                    }
                )

    async def _rank_dealers(candidate_dealers: list[DealershipFound]) -> list[DealershipFound]:
        ranked = dedupe_dealers_by_domain(candidate_dealers)
        await _warm_dealer_metadata(ranked)
        if len(ranked) > 1:
            dealer_domains = [normalize_dealer_domain((dealer.website or "").strip()) for dealer in ranked]
            dealer_score_cards.update(await asyncio.to_thread(get_score_cards, dealer_domains))

            def _dealer_sort_key(dealer: DealershipFound) -> tuple[int, int, float, int]:
                website = prefer_https_website_url((dealer.website or "").strip())
                domain = normalize_dealer_domain(website)
                score_card = dealer_score_cards.get(domain, DealerScoreCard())
                inv_cache_key = inventory_listings_cache_key(
                    website=website,
                    domain=domain,
                    make=make,
                    model=model,
                    vehicle_category=vehicle_category,
                    vehicle_condition=vehicle_condition,
                    inventory_scope=inventory_scope,
                    max_pages=requested_pages,
                )
                cached_inventory = warmed_inventory_cache.get(inv_cache_key) or {}
                cache_hint_score = 0
                if cached_inventory.get("listings"):
                    cache_hint_score = 1 if cached_inventory.get("_cache_is_stale") else 2
                platform_entry = platform_cache_entries.get(domain)
                route_hint_score = 0
                if platform_entry is not None:
                    if platform_entry.is_usable:
                        route_hint_score += 20
                    if platform_entry.inventory_url_hint:
                        route_hint_score += 8
                    if not platform_entry.requires_render:
                        route_hint_score += 4
                    route_hint_score -= min(int(platform_entry.failure_count or 0), 3) * 5
                route_hint_score -= min(int(score_card.failure_streak or 0), 3) * 4
                if prefer_small_dealers and vehicle_category == "car":
                    route_hint_score += dealer_preference_bias(
                        dealer.name,
                        website,
                        search_make=make,
                    )
                return (
                    cache_hint_score,
                    route_hint_score,
                    float(score_card.score),
                    -int(score_card.failure_streak or 0),
                )

            ranked.sort(key=_dealer_sort_key, reverse=True)
        return ranked

    def _dealership_queue_payload(index: int, total: int, dealer: DealershipFound) -> dict[str, Any]:
        website = prefer_https_website_url((dealer.website or "").strip())
        domain = normalize_dealer_domain(website)
        inv_cache_key = inventory_listings_cache_key(
            website=website,
            domain=domain,
            make=make,
            model=model,
            vehicle_category=vehicle_category,
            vehicle_condition=vehicle_condition,
            inventory_scope=inventory_scope,
            max_pages=requested_pages,
        )
        cached_inventory = warmed_inventory_cache.get(inv_cache_key) or {}
        platform_entry = platform_cache_entries.get(domain)
        queued_info = "Waiting for an open scrape worker."
        if cached_inventory.get("listings"):
            queued_info = (
                "Stale cache hit ready while inventory refreshes."
                if cached_inventory.get("_cache_is_stale")
                else "Cache hit ready to stream inventory."
            )
        elif platform_entry is not None and platform_entry.inventory_url_hint:
            queued_info = "Queued with a known inventory route."
        return {
            "index": index,
            "total": total,
            "name": dealer.name,
            "website": website,
            "address": dealer.address,
            "status": "queued",
            "info": queued_info,
            "platform_id": platform_entry.platform_id if platform_entry is not None else None,
            "strategy_used": platform_entry.extraction_mode if platform_entry is not None else None,
        }

    seed_query_limit = min(3, max(1, int(settings.places_text_query_variant_cap or 1)))
    progressive_discovery_enabled = requested_dealerships > 1 and seed_query_limit < max(
        1, int(settings.places_text_query_variant_cap or 1)
    )
    full_discovery_task: asyncio.Task[list[DealershipFound]] | None = None
    final_discovery_logged = False
    try:
        if progressive_discovery_enabled:
            seed_candidates = await _discover_dealers(query_variant_limit=seed_query_limit)
            raw_dealer_count = len(seed_candidates)
            deduped_dealer_count = len(dedupe_dealers_by_domain(seed_candidates))
            dealers = (await _rank_dealers(seed_candidates))[:requested_dealerships]
            full_discovery_task = asyncio.create_task(_discover_dealers())
        else:
            discovered_dealers = await _discover_dealers()
            raw_dealer_count = len(discovered_dealers)
            deduped_dealer_count = len(dedupe_dealers_by_domain(discovered_dealers))
            dealers = (await _rank_dealers(discovered_dealers))[:requested_dealerships]
    except Exception as e:
        logger.exception(f"{cid_log}Places search failed")
        error = SearchErrorInfo(
            code="places.lookup_failed",
            message=str(e),
            phase="places",
            retryable=True,
        )
        if recorder is not None:
            recorder.event(
                event_type="places_failed",
                phase="places",
                level="error",
                message=error.message,
                payload={"error": error.to_summary(), "places_metrics": places_metrics.as_dict()},
            )
        yield sse_pack("search_error", error.with_correlation_id(correlation_id).to_payload())
        yield sse_pack("done", finalize_done(search_failure_payload(error), ok=False))
        return

    if not dealers and full_discovery_task is None:
        if recorder is not None:
            recorder.event(
                event_type="dealers_empty",
                phase="places",
                level="info",
                message="No dealerships with websites found.",
                payload={"dealer_discovery_count": raw_dealer_count, "dealer_deduped_count": deduped_dealer_count},
            )
        yield sse_pack("status", {"message": "No dealerships with websites found.", "phase": "places"})
        yield sse_pack(
            "done",
            finalize_done(
                {
                    "ok": True,
                    "dealerships": 0,
                    "vehicle_category": vehicle_category,
                    "radius_miles": radius_miles,
                    "vehicle_condition": vehicle_condition,
                    "inventory_scope": inventory_scope,
                    "max_dealerships": requested_dealerships,
                    "max_pages_per_dealer": requested_pages,
                },
                ok=True,
            ),
        )
        return

    effective_concurrency = effective_search_concurrency(requested_pages=requested_pages)
    scrape_status_message = (
        (
            "Finding additional dealerships before scraping inventory… "
            f"(requested {requested_dealerships}, radius {radius_miles} mi, "
            f"condition {vehicle_condition}, category {vehicle_category}, workers {effective_concurrency})"
        )
        if not dealers and full_discovery_task is not None
        else (
            f"Found {len(dealers)} dealerships. Scraping inventory… "
            f"(requested {requested_dealerships}, radius {radius_miles} mi, "
            f"condition {vehicle_condition}, category {vehicle_category}, workers {effective_concurrency})"
        )
    )
    yield sse_pack(
        "status",
        {
            "message": scrape_status_message,
            "phase": "scrape",
            "dealer_discovery_count": raw_dealer_count,
            "dealer_deduped_count": deduped_dealer_count,
            "dealerships_queued": len(dealers),
        },
    )

    sem = asyncio.Semaphore(effective_concurrency)
    metrics_lock = asyncio.Lock()
    inv_url_cache: dict[str, str] = {}

    async def process_one(index: int, d: DealershipFound, sse_stream_queue: asyncio.Queue[str | object]) -> None:
        nonlocal completed_dealer_count, successful_dealer_count, streamed_vehicle_count

        async def _emit(raw: str) -> None:
            await sse_stream_queue.put(raw)

        dealer_started_at = time.perf_counter()
        website = prefer_https_website_url((d.website or "").strip())
        dealer_zip = _extract_us_zip(d.address or "") or _extract_us_zip(location)
        logger.info(f"{cid_log}Processing dealer {index}: {d.name} ({website})")
        if recorder is not None:
            recorder.note_dealer_started(dealership_name=d.name, dealership_website=website)
            recorder.event(
                event_type="dealer_started",
                phase="scrape",
                level="info",
                message=f"Started dealership scrape for {d.name}.",
                dealership_name=d.name,
                dealership_website=website,
                payload={"index": index, "total": len(dealers)},
            )
        domain = normalize_dealer_domain(website)
        platform_entry = platform_cache_entries.get(domain)
        fetch_methods_used: list[str] = []
        ford_recovery_urls: list[str] = []
        inv_cache_key = inventory_listings_cache_key(
            website=website,
            domain=domain,
            make=make,
            model=model,
            vehicle_category=vehicle_category,
            vehicle_condition=vehicle_condition,
            inventory_scope=inventory_scope,
            max_pages=requested_pages,
        )
        listings_for_cache: list[dict] = []
        total_vehicles = 0
        dealer_failed = False
        score_recorded = False
        stale_cache_seed_listings: list[dict[str, Any]] = []
        score_card = _score_card_for_domain(domain)
        dealer_timeout = _effective_dealer_timeout(
            requested_pages,
            dealer_score=score_card.score,
            failure_streak=score_card.failure_streak,
        )
        fetch_timeout = min(settings.scrape_timeout * 3 + 5.0, max(20.0, dealer_timeout * 0.5))
        parse_timeout = min(settings.openai_timeout + 5.0, max(20.0, dealer_timeout * 0.35))

        async def _fetch(
            url: str,
            page_kind: PageKind,
            *,
            prefer_render: bool = False,
            platform_id: str | None = None,
        ) -> tuple[str, str]:
            host_key = normalize_dealer_domain(url) or domain or "unknown"
            local_fetch_metrics: dict[str, int] = {}
            allow_escalation = not _dealer_budget_relief_active(score_card)
            async with domain_fetch_limiter(host_key):
                html, method = await fetch_page_html(
                    url,
                    page_kind=page_kind,
                    prefer_render=prefer_render,
                    allow_escalation=allow_escalation,
                    metrics=local_fetch_metrics,
                    platform_id=platform_id,
                )
            fetch_methods_used.append(method)
            if domain:
                dealer_last_fetch_method[domain] = method
            async with metrics_lock:
                key = f"fetch_{method}"
                fetch_metrics[key] += 1
                for metric_key, metric_value in local_fetch_metrics.items():
                    if metric_value:
                        fetch_metrics[metric_key] += metric_value
            return html, method

        async def _try_oneaudi_initial_inventory_alternates(primary_url: str) -> bool:
            nonlocal current_html, current_method, inv_url, current_url
            if not (
                route
                and route.platform_id == "oneaudi_falcon"
                and vehicle_condition == "all"
                and primary_url
                and "/inventory/" in urlsplit(primary_url).path.lower()
            ):
                return False
            for retry_url in _oneaudi_all_inventory_urls(primary_url):
                if retry_url.rstrip("/") == primary_url.rstrip("/"):
                    continue
                await _emit(
                    sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": d.name,
                            "website": website,
                            "current_url": retry_url,
                            "status": "scraping",
                        },
                    )
                )
                try:
                    retry_timeout = _phase_timeout(fetch_timeout, reserve_seconds=6.0)
                    if retry_timeout is None:
                        raise RuntimeError("dealer_time_budget_exhausted")
                    current_html, current_method = await asyncio.wait_for(
                        _fetch(
                            retry_url,
                            page_kind="inventory",
                            prefer_render=bool(route.requires_render),
                            platform_id=route.platform_id,
                        ),
                        timeout=retry_timeout,
                    )
                    inv_url = retry_url
                    current_url = retry_url
                    route.inventory_url_hint = retry_url
                    logger.info(
                        "Recovered OneAudi initial inventory URL for %s via alternate %s",
                        d.name,
                        retry_url,
                    )
                    return True
                except Exception as retry_error:
                    logger.debug(
                        "OneAudi initial inventory retry failed for %s via %s: %s",
                        d.name,
                        retry_url,
                        retry_error,
                    )
            return False

        def _phase_timeout(
            base_timeout: float,
            *,
            reserve_seconds: float = 20.0,
            min_timeout: float = 5.0,
        ) -> float | None:
            elapsed = time.perf_counter() - dealer_started_at
            return _bounded_phase_timeout(
                base_timeout=base_timeout,
                dealer_timeout=dealer_timeout,
                elapsed_seconds=elapsed,
                reserve_seconds=reserve_seconds,
                min_timeout=min_timeout,
            )

        async def append_dealer_error(
            message: str,
            *,
            current_url: str | None = None,
            phase: str = "scrape",
            platform_id: str | None = None,
            fetch_method: str | None = None,
        ) -> None:
            nonlocal dealer_failed
            dealer_failed = True
            lowered = message.lower()
            if "timed out" in lowered:
                error_code = "dealer.timeout"
            elif any(token in lowered for token in ("403", "blocked", "captcha", "cloudflare", "akamai", "denied")):
                error_code = "dealer.fetch_blocked"
            elif phase == "parse":
                error_code = "dealer.parse_failed"
            else:
                error_code = "dealer.scrape_failed"
            if recorder is not None:
                recorder.note_dealer_failed()
                recorder.note_dealer_issue(
                    issue_type="error",
                    platform_id=platform_id,
                    fetch_method=fetch_method,
                )
                recorder.event(
                    event_type="dealer_error",
                    phase=phase,
                    level="warning",
                    message=message,
                    dealership_name=d.name,
                    dealership_website=website,
                    payload={
                        "index": index,
                        "current_url": current_url,
                        "platform_id": platform_id,
                        "fetch_method": fetch_method,
                        "error_code": error_code,
                    },
                )
            await _emit(
                sse_pack(
                    "dealership",
                    {
                        "index": index,
                        "total": len(dealers),
                        "name": d.name,
                        "website": website,
                        **({"current_url": current_url} if current_url else {}),
                        "status": "error",
                        "error": message,
                    },
                )
            )

        async def _record_dealer_score(*, used_cache: bool = False) -> None:
            nonlocal score_recorded
            if score_recorded or used_cache or not domain:
                return
            score_rows = listings_for_cache or stale_cache_seed_listings
            elapsed_s = time.perf_counter() - dealer_started_at
            await asyncio.to_thread(
                record_scrape_outcome,
                domain,
                listings=total_vehicles,
                price_fill=_price_fill_rate(score_rows),
                vin_fill=_vin_fill_rate(score_rows),
                elapsed_s=elapsed_s,
                failed=dealer_failed or (total_vehicles <= 0 and not score_rows),
            )
            score_recorded = True

        await _emit(
            sse_pack(
                "dealership",
                {
                    "index": index,
                    "total": len(dealers),
                    "name": d.name,
                    "website": website,
                    "address": d.address,
                    "status": "scraping",
                    "info": "Contacting the dealership website…",
                },
            )
        )
        if True:
            if inv_cache_key in warmed_inventory_cache:
                cached_inv = warmed_inventory_cache[inv_cache_key]
            else:
                cached_inv = await asyncio.to_thread(get_inventory_cache_entry, inv_cache_key, allow_stale=True)
            if cached_inv and cached_inv.get("listings"):
                fetch_methods_used.append("inventory_cache")
                cached_listings = cached_inv["listings"]
                cached_is_stale = bool(cached_inv.get("_cache_is_stale"))
                total_cached = 0
                for listing_chunk in _chunk_listings(cached_listings):
                    total_cached += len(listing_chunk)
                    if recorder is not None:
                        recorder.note_vehicle_batch(batch_size=len(listing_chunk), fetch_method="inventory_cache")
                        recorder.capture_listing_batch(
                            dealership=d.name, website=website, listings=listing_chunk
                        )
                    await _emit(
                        sse_pack(
                            "vehicles",
                            {
                                "dealership": d.name,
                                "website": website,
                                "current_url": website,
                                "count": len(listing_chunk),
                                "listings": listing_chunk,
                            },
                        )
                    )
                if not cached_is_stale:
                    await _emit(
                        sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "status": "done",
                                "listings_found": total_cached,
                                "fetch_methods": fetch_methods_used,
                                "platform_id": cached_inv.get("platform_id"),
                                "platform_source": "cache",
                                "strategy_used": "inventory_cache",
                                "from_cache": True,
                                "info": "Loaded from warm inventory cache.",
                            },
                        )
                    )
                    async with metrics_lock:
                        completed_dealer_count += 1
                        successful_dealer_count += 1
                        streamed_vehicle_count += total_cached
                    if recorder is not None:
                        recorder.note_dealer_done(listings_found=total_cached)
                        recorder.event(
                            event_type="dealer_done",
                            phase="scrape",
                            level="info",
                            message=f"Finished dealership scrape for {d.name}.",
                            dealership_name=d.name,
                            dealership_website=website,
                            payload={
                                "index": index,
                                "listings_found": total_cached,
                                "from_cache": True,
                                "fetch_methods": fetch_methods_used,
                            },
                        )
                    await _record_dealer_score(used_cache=True)
                    return
                stale_cache_seed_listings = [
                    dict(item) for item in cached_listings if isinstance(item, dict)
                ]
                total_vehicles = total_cached
                await _emit(
                    sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": d.name,
                            "website": website,
                            "status": "scraping",
                            "listings_found": total_cached,
                            "fetch_methods": fetch_methods_used,
                            "platform_id": cached_inv.get("platform_id"),
                            "platform_source": "cache",
                            "strategy_used": "inventory_cache",
                            "from_cache": True,
                            "info": "Loaded from stale inventory cache while refreshing dealership data.",
                        },
                    )
                )

            # 1. Try a known inventory route first when platform cache already has a usable hint.
            base_url = website
            homepage_html: str | None = None
            homepage_method: str | None = None
            seed_inventory_url: str | None = None
            prefetched_route = (
                provider_route_from_cache_entry(platform_entry, cache_status="warm")
                if platform_entry is not None and platform_entry.is_usable
                else None
            )
            prefetched_inventory_url = (
                platform_entry.inventory_url_hint
                if platform_entry is not None and platform_entry.inventory_url_hint
                else speculative_inventory_url(
                    domain,
                    platform_entry.platform_id,
                    vehicle_condition,
                    website=website,
                )
                if platform_entry is not None and platform_entry.is_usable
                else None
            )
            if prefetched_route is None and _looks_like_tesla_site_url(website):
                hinted_route = detect_or_lookup_provider(
                    domain=domain,
                    website=website,
                    homepage_html="",
                )
                if hinted_route is not None and hinted_route.platform_id == "tesla_inventory":
                    prefetched_route = hinted_route
                    prefetched_inventory_url = website
            prefetched_html: str | None = None
            prefetched_method: str | None = None
            if prefetched_route and prefetched_inventory_url:
                candidate_inventory_url = resolve_inventory_url_for_provider(
                    "",
                    base_url,
                    prefetched_route,
                    fallback_url=prefetched_inventory_url,
                    make=make,
                    model=model,
                    vehicle_condition=vehicle_condition,
                )
                candidate_inventory_urls = [candidate_inventory_url] if candidate_inventory_url else []
                if prefetched_route.platform_id == "tesla_inventory":
                    candidate_inventory_urls = _tesla_inventory_urls(
                        candidate_inventory_url,
                        vehicle_condition=vehicle_condition,
                        model=model,
                        fallback_zip=dealer_zip,
                        fallback_range_miles=radius_miles,
                    )
                for candidate_inventory_url in candidate_inventory_urls:
                    if candidate_inventory_url.rstrip("/") == base_url.rstrip("/"):
                        continue
                    await _emit(
                        sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "current_url": candidate_inventory_url,
                                "status": "scraping",
                                "info": (
                                    "Using a known inventory route."
                                    if platform_entry is not None and platform_entry.inventory_url_hint
                                    else "Trying a platform-specific inventory route."
                                ),
                            },
                        )
                    )
                    try:
                        prefetched_timeout = _phase_timeout(fetch_timeout, reserve_seconds=6.0)
                        if prefetched_timeout is None:
                            raise RuntimeError("dealer_time_budget_exhausted")
                        prefetched_html, prefetched_method = await asyncio.wait_for(
                            _fetch(
                                candidate_inventory_url,
                                "inventory",
                                prefer_render=bool(prefetched_route.requires_render),
                                platform_id=prefetched_route.platform_id,
                            ),
                            timeout=prefetched_timeout,
                        )
                        seed_inventory_url = candidate_inventory_url
                        logger.info(
                            "%sSkipped homepage for %s using cached inventory route %s",
                            cid_log,
                            d.name,
                            candidate_inventory_url,
                        )
                        break
                    except Exception as prefetched_error:
                        logger.debug(
                            "%sKnown inventory route failed for %s (%s); trying next candidate",
                            cid_log,
                            candidate_inventory_url,
                            prefetched_error,
                        )
                if prefetched_route and seed_inventory_url is None:
                    logger.debug(
                        "%sKnown inventory route candidates failed for %s; falling back to homepage discovery",
                        cid_log,
                        d.name,
                    )
                    prefetched_route = None
                    seed_inventory_url = None

            if seed_inventory_url is None:
                try:
                    homepage_timeout = _phase_timeout(
                        _cap_unknown_platform_fetch_timeout(
                            fetch_timeout,
                            page_kind="homepage",
                            platform_id=None,
                        )
                    )
                    if homepage_timeout is None:
                        await append_dealer_error(
                            "Timed out while processing this dealership. Skipping to keep search moving."
                        )
                        await _record_dealer_score()
                        return
                    homepage_html, homepage_method = await asyncio.wait_for(
                        _fetch(website, "homepage"),
                        timeout=homepage_timeout,
                    )

                    # If the homepage has a canonical link, it likely redirected to a different domain.
                    # Use the canonical URL as the new base website to ensure inventory links resolve correctly.
                    canonical_href = await asyncio.to_thread(_extract_canonical_homepage_url, homepage_html)
                    if canonical_href:
                        domain = normalize_dealer_domain(canonical_href)
                        base_url = canonical_href
                        platform_entry = platform_cache_entries.get(domain) or platform_entry
                except asyncio.TimeoutError:
                    logger.warning(f"{cid_log}Scrape timed out for %s", website)
                    homepage_timed_out_msg = f"Timed out while fetching pages after ~{int(fetch_timeout)}s."
                    guess_candidates = guess_franchise_inventory_srp_urls(base_url, vehicle_condition)
                    guess_candidates.extend(
                        speculative_inventory_urls_for_unknown_site(
                            base_url,
                            vehicle_condition,
                            make=make,
                            model=model,
                        )
                    )
                    homepage_norm = prefer_https_website_url(base_url).rstrip("/")
                    rescued_from_homepage_timeout = False
                    for guess_inv in guess_candidates:
                        if guess_inv.rstrip("/") == homepage_norm:
                            continue
                        await _emit(
                            sse_pack(
                                "dealership",
                                {
                                    "index": index,
                                    "total": len(dealers),
                                    "name": d.name,
                                    "website": website,
                                    "current_url": guess_inv,
                                    "status": "scraping",
                                },
                            )
                        )
                        try:
                            rescue_timeout = _phase_timeout(
                                _cap_unknown_platform_fetch_timeout(
                                    fetch_timeout,
                                    page_kind="inventory",
                                    platform_id=None,
                                ),
                                reserve_seconds=6.0,
                            )
                            if rescue_timeout is None:
                                raise RuntimeError("dealer_time_budget_exhausted")
                            homepage_html, homepage_method = await asyncio.wait_for(
                                _fetch(guess_inv, "inventory", prefer_render=True),
                                timeout=rescue_timeout,
                            )
                            seed_inventory_url = guess_inv
                            rescued_from_homepage_timeout = True
                            logger.info(
                                "Recovered dealership %s after homepage timeout using guessed SRP %s",
                                d.name,
                                guess_inv,
                            )
                            break
                        except Exception as rescue_error:
                            logger.warning(
                                "%sHomepage timeout rescue via guessed SRP failed for %s: %s",
                                cid_log,
                                guess_inv,
                                rescue_error,
                            )
                    if not rescued_from_homepage_timeout:
                        if domain:
                            record_provider_failure(domain)
                        await append_dealer_error(homepage_timed_out_msg)
                        await _record_dealer_score()
                        return
                except Exception as e:
                    logger.warning(f"{cid_log}Scrape failed for %s: %s", website, e)
                    guess_candidates = guess_franchise_inventory_srp_urls(base_url, vehicle_condition)
                    guess_candidates.extend(
                        speculative_inventory_urls_for_unknown_site(
                            base_url,
                            vehicle_condition,
                            make=make,
                            model=model,
                        )
                    )
                    homepage_norm = prefer_https_website_url(base_url).rstrip("/")
                    rescued_from_homepage_failure = False
                    for guess_inv in guess_candidates:
                        if guess_inv.rstrip("/") == homepage_norm:
                            continue
                        await _emit(
                            sse_pack(
                                "dealership",
                                {
                                    "index": index,
                                    "total": len(dealers),
                                    "name": d.name,
                                    "website": website,
                                    "current_url": guess_inv,
                                    "status": "scraping",
                                },
                            )
                        )
                        try:
                            rescue_timeout = _phase_timeout(
                                _cap_unknown_platform_fetch_timeout(
                                    fetch_timeout,
                                    page_kind="inventory",
                                    platform_id=None,
                                ),
                                reserve_seconds=6.0,
                            )
                            if rescue_timeout is None:
                                raise RuntimeError("dealer_time_budget_exhausted")
                            homepage_html, homepage_method = await asyncio.wait_for(
                                _fetch(guess_inv, "inventory", prefer_render=True),
                                timeout=rescue_timeout,
                            )
                            seed_inventory_url = guess_inv
                            rescued_from_homepage_failure = True
                            logger.info(
                                "Recovered dealership %s after homepage fetch failure using guessed SRP %s",
                                d.name,
                                guess_inv,
                            )
                            break
                        except Exception as rescue_error:
                            logger.warning(
                                "%sHomepage rescue via guessed SRP failed for %s: %s",
                                cid_log,
                                guess_inv,
                                rescue_error,
                            )
                    if not rescued_from_homepage_failure:
                        if domain:
                            record_provider_failure(domain)
                        await append_dealer_error(str(e))
                        await _record_dealer_score()
                        return

            route = prefetched_route
            inv_url = seed_inventory_url or base_url

            if homepage_html is not None:
                detection_url = seed_inventory_url or base_url
                route = detect_or_lookup_provider(domain=domain, website=detection_url, homepage_html=homepage_html)
                if route:
                    async with metrics_lock:
                        fetch_metrics[f"platform_{route.platform_id}"] += 1
                        fetch_metrics[f"platform_source_{route.cache_status}"] += 1
                if seed_inventory_url is None:
                    inv_url = resolve_inventory_url_for_provider(
                        homepage_html,
                        base_url,
                        route,
                        fallback_url=_find_inventory_url(
                            homepage_html,
                            base_url,
                            vehicle_condition=vehicle_condition,
                            market_region=market_region,
                        ),
                        make=make,
                        model=model,
                        vehicle_condition=vehicle_condition,
                    )
            if route is None and _looks_like_tesla_site_url(website):
                hinted_route = detect_or_lookup_provider(domain=domain, website=website, homepage_html="")
                if hinted_route is not None and hinted_route.platform_id == "tesla_inventory":
                    route = hinted_route
                    inv_url = website
            if inv_url == base_url and domain in inv_url_cache:
                cached = inv_url_cache[domain]
                if cached and cached.rstrip("/") != base_url.rstrip("/"):
                    inv_url = cached
            if route is None and inv_url and inv_url != base_url:
                route = detect_or_lookup_provider(domain=domain, website=inv_url, homepage_html="")
                if route:
                    async with metrics_lock:
                        fetch_metrics[f"platform_{route.platform_id}"] += 1
                        fetch_metrics[f"platform_source_{route.cache_status}"] += 1
                    if homepage_html is not None and seed_inventory_url is None:
                        inv_url = resolve_inventory_url_for_provider(
                            homepage_html,
                            base_url,
                            route,
                            fallback_url=inv_url,
                            make=make,
                            model=model,
                            vehicle_condition=vehicle_condition,
                        )
            if inv_url == base_url:
                try:
                    sm_timeout = httpx.Timeout(min(settings.scrape_timeout, 30.0))
                    candidates = await discover_sitemap_inventory_urls(base_url, sm_timeout)
                    for cand in candidates:
                        if cand.rstrip("/") != base_url.rstrip("/"):
                            inv_url = cand
                            logger.info(f"{cid_log}Using sitemap inventory candidate for {domain}: {inv_url}")
                            break
                except Exception as e:
                    logger.debug("Sitemap discovery skipped for %s: %s", base_url, e)

            current_html = prefetched_html or homepage_html or ""
            current_method = prefetched_method or homepage_method or "unknown"

            if (
                route is None
                and inv_url
                and prefer_https_website_url(inv_url).rstrip("/") == prefer_https_website_url(base_url).rstrip("/")
            ):
                for speculative_url in speculative_inventory_urls_for_unknown_site(
                    base_url,
                    vehicle_condition,
                    make=make,
                    model=model,
                ):
                    if speculative_url.rstrip("/") == prefer_https_website_url(base_url).rstrip("/"):
                        continue
                    await _emit(
                        sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "current_url": speculative_url,
                                "status": "scraping",
                                "info": "Trying a likely inventory path for a smaller dealer site.",
                            },
                        )
                    )
                    try:
                        speculative_timeout = _phase_timeout(fetch_timeout, reserve_seconds=6.0)
                        if speculative_timeout is None:
                            raise RuntimeError("dealer_time_budget_exhausted")
                        speculative_html, speculative_method = await asyncio.wait_for(
                            _fetch(speculative_url, "inventory", prefer_render=True),
                            timeout=speculative_timeout,
                        )
                        if _looks_like_block_page(speculative_html):
                            continue
                        current_html = speculative_html
                        current_method = speculative_method
                        inv_url = speculative_url
                        route = detect_or_lookup_provider(domain=domain, website=speculative_url, homepage_html=speculative_html)
                        break
                    except Exception as speculative_error:
                        logger.debug(
                            "Unknown-platform speculative inventory fetch skipped for %s via %s: %s",
                            d.name,
                            speculative_url,
                            speculative_error,
                        )

            if route and route.platform_id == "tesla_inventory":
                seed_tesla_urls = _tesla_inventory_urls(
                    inv_url or base_url,
                    vehicle_condition=vehicle_condition,
                    model=model,
                    fallback_zip=dealer_zip,
                    fallback_range_miles=radius_miles,
                )
                if seed_tesla_urls:
                    inv_url = seed_tesla_urls[0]

            # If inventory is on a different URL, fetch it before first parse.
            if seed_inventory_url is None and inv_url and inv_url != base_url:
                await _emit(
                    sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": d.name,
                            "website": website,
                            "current_url": inv_url,
                            "status": "scraping",
                        },
                    )
                )
                try:
                    inv_timeout = _phase_timeout(
                        _cap_unknown_platform_fetch_timeout(
                            fetch_timeout,
                            page_kind="inventory",
                            platform_id=route.platform_id if route else None,
                        )
                    )
                    if inv_timeout is None:
                        await append_dealer_error(
                            "Timed out while processing this dealership. Skipping to keep search moving.",
                            current_url=inv_url,
                        )
                        await _record_dealer_score()
                        return
                    current_html, current_method = await asyncio.wait_for(
                        _fetch(
                            inv_url,
                            "inventory",
                            prefer_render=bool(route and route.requires_render),
                            platform_id=route.platform_id if route else None,
                        ),
                        timeout=inv_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"{cid_log}Initial inventory scrape timed out for %s", inv_url)
                    recovered = await _try_oneaudi_initial_inventory_alternates(inv_url)
                    inventory_retry_url = guess_franchise_inventory_srp_url(base_url, vehicle_condition)
                    if not recovered and domain:
                        record_provider_failure(domain)
                    if (
                        not recovered
                        and inventory_retry_url
                        and inventory_retry_url.rstrip("/") != (inv_url or "").rstrip("/")
                    ):
                        await _emit(
                            sse_pack(
                                "dealership",
                                {
                                    "index": index,
                                    "total": len(dealers),
                                    "name": d.name,
                                    "website": website,
                                    "current_url": inventory_retry_url,
                                    "status": "scraping",
                                },
                            )
                        )
                        try:
                            retry_timeout = _phase_timeout(
                                _cap_unknown_platform_fetch_timeout(
                                    fetch_timeout,
                                    page_kind="inventory",
                                    platform_id=route.platform_id if route else None,
                                ),
                                reserve_seconds=6.0,
                            )
                            if retry_timeout is None:
                                raise RuntimeError("dealer_time_budget_exhausted")
                            current_html, current_method = await asyncio.wait_for(
                                _fetch(
                                    inventory_retry_url,
                                    "inventory",
                                    prefer_render=True,
                                    platform_id=route.platform_id if route else None,
                                ),
                                timeout=retry_timeout,
                            )
                            inv_url = inventory_retry_url
                        except Exception as e:
                            logger.warning(
                                "%sInventory timeout rescue via guessed SRP failed for %s: %s",
                                cid_log,
                                inv_url,
                                e,
                            )
                            await append_dealer_error(
                                f"Timed out while fetching inventory page after ~{int(fetch_timeout)}s.",
                                current_url=inv_url,
                            )
                            await _record_dealer_score()
                            return
                    elif not recovered:
                        await append_dealer_error(
                            f"Timed out while fetching inventory page after ~{int(fetch_timeout)}s.",
                            current_url=inv_url,
                        )
                        await _record_dealer_score()
                        return
                except Exception as e:
                    logger.warning(f"{cid_log}Initial inventory scrape failed for %s: %s", inv_url, e)
                    recovered = await _try_oneaudi_initial_inventory_alternates(inv_url)
                    if not recovered and ("403" in str(e) or "All fetch methods failed" in str(e)):
                        for retry_url in _inventory_url_recovery_candidates(
                            inv_url=inv_url,
                            base_url=base_url,
                            route=route,
                            make=make,
                            model=model,
                            vehicle_condition=vehicle_condition,
                            fallback_zip=dealer_zip,
                            fallback_range_miles=radius_miles,
                        ):
                            await _emit(
                                sse_pack(
                                    "dealership",
                                    {
                                        "index": index,
                                        "total": len(dealers),
                                        "name": d.name,
                                        "website": website,
                                        "current_url": retry_url,
                                        "status": "scraping",
                                    },
                                )
                            )
                            try:
                                retry_timeout = _phase_timeout(fetch_timeout, reserve_seconds=6.0)
                                if retry_timeout is None:
                                    raise RuntimeError("dealer_time_budget_exhausted")
                                current_html, current_method = await asyncio.wait_for(
                                    _fetch(
                                        retry_url,
                                        "inventory",
                                        prefer_render=bool(route and route.requires_render),
                                        platform_id=route.platform_id if route else None,
                                    ),
                                    timeout=retry_timeout,
                                )
                                inv_url = retry_url
                                if route:
                                    route.inventory_url_hint = retry_url
                                recovered = True
                                logger.info(
                                    "Recovered initial inventory URL for %s via fallback %s",
                                    d.name,
                                    retry_url,
                                )
                                break
                            except Exception as retry_error:
                                logger.debug(
                                    "Initial inventory retry failed for %s via %s: %s",
                                    d.name,
                                    retry_url,
                                    retry_error,
                                )
                    if not recovered:
                        if domain:
                            record_provider_failure(domain)
                        await append_dealer_error(str(e), current_url=inv_url)
                        await _record_dealer_score()
                        return
            elif route and route.requires_render:
                try:
                    render_timeout = _phase_timeout(fetch_timeout, reserve_seconds=6.0)
                    if render_timeout is None:
                        raise RuntimeError("dealer_time_budget_exhausted")
                    current_html, current_method = await asyncio.wait_for(
                        _fetch(
                            inv_url or base_url,
                            "inventory",
                            prefer_render=True,
                            platform_id=route.platform_id,
                        ),
                        timeout=render_timeout,
                    )
                except Exception as e:
                    logger.debug("Preferred rendered refetch skipped for %s: %s", inv_url or base_url, e)

            # Bot-challenge homepages often have no inventory <a> tags, so inv_url stays the homepage.
            # Try a common franchise SRP with JS rendering before giving up on platform detection.
            if (
                inv_url
                and prefer_https_website_url(inv_url).rstrip("/")
                == prefer_https_website_url(base_url).rstrip("/")
                and _looks_like_block_page(current_html)
            ):
                guess_inv = guess_franchise_inventory_srp_url(base_url, vehicle_condition)
                if guess_inv and guess_inv.rstrip("/") != prefer_https_website_url(base_url).rstrip(
                    "/"
                ):
                    await _emit(
                        sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "current_url": guess_inv,
                                "status": "scraping",
                            },
                        )
                    )
                    try:
                        rescue_timeout = _phase_timeout(fetch_timeout, reserve_seconds=6.0)
                        if rescue_timeout is None:
                            raise RuntimeError("dealer_time_budget_exhausted")
                        rescue_html, rescue_method = await asyncio.wait_for(
                            _fetch(guess_inv, "inventory", prefer_render=True),
                            timeout=rescue_timeout,
                        )
                        if not _looks_like_block_page(rescue_html):
                            current_html = rescue_html
                            current_method = rescue_method
                            inv_url = guess_inv
                            logger.info(
                                "Recovered inventory after challenge homepage using guessed SRP %s",
                                guess_inv,
                            )
                    except asyncio.TimeoutError:
                        logger.warning("Guessed SRP inventory fetch timed out for %s", guess_inv)
                    except Exception as e:
                        logger.warning("Guessed SRP inventory fetch failed for %s: %s", guess_inv, e)

            # Some Dealer.com-style homepages only expose inventory hints after an inventory/render fetch
            # against the homepage itself. Use that rendered HTML to detect the platform and derive a
            # canonical SRP when homepage anchor discovery failed.
            if (
                inv_url
                and prefer_https_website_url(inv_url).rstrip("/")
                == prefer_https_website_url(base_url).rstrip("/")
                and route is None
            ):
                try:
                    rendered_home_timeout = _phase_timeout(fetch_timeout, reserve_seconds=6.0)
                    if rendered_home_timeout is None:
                        raise RuntimeError("dealer_time_budget_exhausted")
                    rendered_home_html, rendered_home_method = await asyncio.wait_for(
                        _fetch(base_url, "inventory", prefer_render=True),
                        timeout=rendered_home_timeout,
                    )
                    rendered_profile = detect_platform_profile(rendered_home_html, page_url=base_url)
                    if rendered_profile:
                        route = ProviderRoute(
                            platform_id=rendered_profile.platform_id,
                            confidence=rendered_profile.confidence,
                            extraction_mode=rendered_profile.extraction_mode,
                            requires_render=rendered_profile.requires_render,
                            detection_source=rendered_profile.detection_source,
                            cache_status="detected",
                            inventory_path_hints=rendered_profile.inventory_path_hints,
                            inventory_url_hint=base_url,
                        )
                        rendered_inv_url = resolve_inventory_url_for_provider(
                            rendered_home_html,
                            base_url,
                            route,
                            fallback_url=_find_inventory_url(
                                rendered_home_html,
                                base_url,
                                vehicle_condition=vehicle_condition,
                                market_region=market_region,
                            ),
                            make=make,
                            model=model,
                            vehicle_condition=vehicle_condition,
                        )
                        if rendered_inv_url.rstrip("/") != prefer_https_website_url(base_url).rstrip("/"):
                            await _emit(
                                sse_pack(
                                    "dealership",
                                    {
                                        "index": index,
                                        "total": len(dealers),
                                        "name": d.name,
                                        "website": website,
                                        "current_url": rendered_inv_url,
                                        "status": "scraping",
                                    },
                                )
                            )
                            current_html, current_method = await asyncio.wait_for(
                                _fetch(
                                    rendered_inv_url,
                                    "inventory",
                                    prefer_render=route.requires_render,
                                    platform_id=route.platform_id,
                                ),
                                timeout=rendered_home_timeout,
                            )
                            inv_url = rendered_inv_url
                        else:
                            current_html = rendered_home_html
                            current_method = rendered_home_method
                except Exception as e:
                    logger.debug(
                        "Rendered homepage inventory discovery skipped for %s: %s",
                        base_url,
                        e,
                    )

            inventory_profile = detect_platform_profile(current_html, page_url=inv_url or base_url)
            if inventory_profile and (
                route is None
                or inventory_profile.confidence >= route.confidence
                or route.platform_id in {"team_velocity", "fusionzone", "purecars", "jazel"}
                or (
                    route.platform_id in {"dealer_on", "dealer_inspire", "dealer_dot_com"}
                    and inventory_profile.platform_id in _INVENTORY_FAMILY_PLATFORM_IDS
                )
            ):
                route = ProviderRoute(
                    platform_id=inventory_profile.platform_id,
                    confidence=inventory_profile.confidence,
                    extraction_mode=inventory_profile.extraction_mode,
                    requires_render=inventory_profile.requires_render,
                    detection_source=inventory_profile.detection_source,
                    cache_status="detected",
                    inventory_path_hints=inventory_profile.inventory_path_hints,
                    inventory_url_hint=inv_url or base_url,
                )
            if route and _route_supports_team_velocity_style_inventory_reroute(route):
                rerouted_inv_url = _team_velocity_inventory_url_from_model_hub(
                    inv_url,
                    vehicle_condition=vehicle_condition,
                )
                if rerouted_inv_url and rerouted_inv_url.rstrip("/") != (inv_url or "").rstrip("/"):
                    try:
                        reroute_timeout = _phase_timeout(fetch_timeout, reserve_seconds=6.0)
                        if reroute_timeout is None:
                            raise RuntimeError("dealer_time_budget_exhausted")
                        current_html, current_method = await asyncio.wait_for(
                            _fetch(
                                rerouted_inv_url,
                                "inventory",
                                prefer_render=route.requires_render,
                                platform_id=route.platform_id,
                            ),
                            timeout=reroute_timeout,
                        )
                        inv_url = rerouted_inv_url
                        route.inventory_url_hint = rerouted_inv_url
                    except Exception as e:
                        logger.debug(
                            "Team Velocity SRP reroute skipped for %s: %s",
                            rerouted_inv_url,
                            e,
                        )

            scoped_inventory_url = _inventory_url_uses_scoped_filters(inv_url, make=make, model=model)
            if scoped_inventory_url:
                async with metrics_lock:
                    fetch_metrics["inventory_url_scoped"] += 1

            # 2. Pagination loop
            current_url = inv_url
            pages_scraped = 0
            route_page_cap = _effective_max_pages_for_route(requested_pages, route)
            route_page_cap = min(
                route_page_cap,
                _dealer_budget_page_cap(
                    route_page_cap,
                    dealer_score=score_card.score,
                    failure_streak=score_card.failure_streak,
                ),
            )
            absolute_page_cap = _effective_absolute_page_cap(
                settings.search_max_pages_per_dealer_cap,
                make=make,
                route=route,
            )
            if absolute_page_cap > max(1, settings.search_max_pages_per_dealer_cap):
                async with metrics_lock:
                    fetch_metrics["harley_page_cap_extended"] += 1
            # Keep render-heavy route caps as the *initial* budget only; once the
            # site reports additional pages (or keeps yielding next-page URLs),
            # allow controlled expansion up to the global safety cap.
            page_budget = min(route_page_cap, absolute_page_cap)
            skip_info: str | None = None
            latest_pagination: PaginationInfo | None = None
            dealer_dot_com_make_retry_attempted = False
            queued_urls: set[str] = {current_url} if current_url else set()
            pending_urls: list[str] = []
            if route and route.platform_id == "dealer_on" and current_url:
                dealer_on_model_urls = _dealer_on_multi_model_inventory_urls(
                    current_url,
                    make=make,
                    model=model,
                )
                if dealer_on_model_urls:
                    current_url = dealer_on_model_urls[0]
                    queued_urls = {current_url}
                    pending_urls = [u for u in dealer_on_model_urls[1:] if u not in queued_urls]
                    if inv_url and inv_url not in queued_urls and inv_url not in pending_urls:
                        pending_urls.append(inv_url)
                    scoped_inventory_url = True
                    async with metrics_lock:
                        fetch_metrics["inventory_url_scoped"] += 1
            elif route and route.platform_id == "dealer_inspire" and current_url:
                dealer_inspire_model_urls = _dealer_inspire_multi_model_inventory_urls(
                    current_url,
                    vehicle_condition=vehicle_condition,
                    make=make,
                    model=model,
                )
                if dealer_inspire_model_urls:
                    current_url = dealer_inspire_model_urls[0]
                    queued_urls = {current_url}
                    pending_urls = [u for u in dealer_inspire_model_urls[1:] if u not in queued_urls]
                    if inv_url and inv_url not in queued_urls and inv_url not in pending_urls:
                        pending_urls.append(inv_url)
                    scoped_inventory_url = True
                    async with metrics_lock:
                        fetch_metrics["inventory_url_scoped"] += 1
            elif route and route.platform_id == "oneaudi_falcon" and vehicle_condition == "all" and current_url:
                # Only fan out new/used when we are already on OneAudi inventory routes.
                # Localized EU paths like /de/neuwagen can 404 when coerced into /inventory/new.
                if "/inventory/" in urlsplit(current_url).path.lower():
                    oneaudi_inventory_urls = _oneaudi_all_inventory_urls(current_url)
                    if oneaudi_inventory_urls:
                        current_url = oneaudi_inventory_urls[0]
                        queued_urls = {current_url}
                        pending_urls = [u for u in oneaudi_inventory_urls[1:] if u not in queued_urls]
            elif route and route.platform_id == "tesla_inventory" and current_url:
                tesla_urls = _tesla_inventory_urls(
                    current_url,
                    vehicle_condition=vehicle_condition,
                    model=model,
                    fallback_zip=dealer_zip,
                    fallback_range_miles=radius_miles,
                )
                if tesla_urls:
                    current_url = tesla_urls[0]
                    queued_urls = {current_url}
                    pending_urls = [u for u in tesla_urls[1:] if u not in queued_urls]
            emitted_listing_keys: set[str] = set()
            for cached_listing in stale_cache_seed_listings:
                try:
                    emitted_listing_keys.add(_listing_emit_key(VehicleListing.model_validate(cached_listing)))
                except Exception:
                    continue
            current_inventory_path = urlsplit(current_url).path.rstrip("/").lower() if current_url else ""
            current_inventory_condition = (
                "new"
                if current_inventory_path in {"/new-vehicles", "/inventory/new"}
                else "used"
                if current_inventory_path in {"/used-vehicles", "/inventory/used"}
                else ""
            )
            dealer_inspire_fallback_urls = (
                _dealer_inspire_model_inventory_urls(
                    current_html,
                    current_url or base_url,
                    vehicle_condition=current_inventory_condition,
                    model=model,
                )
                if route
                and route.platform_id == "dealer_inspire"
                and current_inventory_condition in {"new", "used"}
                and current_url
                and current_inventory_path in {"/new-vehicles", "/used-vehicles"}
                else []
            )
            inventory_model_fallback_urls = (
                _team_velocity_model_inventory_urls(
                    current_html,
                    current_url or base_url,
                    vehicle_condition=current_inventory_condition,
                    model=model,
                )
                if route
                and route.platform_id in {
                    "team_velocity",
                    "nissan_infiniti_inventory",
                    "dealer_inspire",
                    "honda_acura_inventory",
                }
                and current_inventory_condition in {"new", "used"}
                and current_url
                and current_inventory_path in {"/inventory/new", "/inventory/used"}
                else []
            )

            while current_url and pages_scraped < page_budget:
                current_url_scoped = _inventory_url_uses_scoped_filters(current_url, make=make, model=model)
                if current_url_scoped:
                    scoped_inventory_url = True
                if pages_scraped > 0:
                    await _emit(
                        sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "current_url": current_url,
                                "status": "scraping",
                            },
                        )
                    )
                    try:
                        page_timeout = _phase_timeout(fetch_timeout)
                        if page_timeout is None:
                            break
                        current_html, current_method = await asyncio.wait_for(
                            _fetch(
                                current_url,
                                "inventory",
                                prefer_render=bool(route and route.requires_render),
                                platform_id=route.platform_id if route else None,
                            ),
                            timeout=page_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Pagination scrape timed out for %s", current_url)
                        break
                    except Exception as e:
                        logger.warning("Pagination scrape failed for %s: %s", current_url, e)
                        break

                ext_result, extraction_mode = await asyncio.to_thread(
                    _extract_inventory_page_sync,
                    page_url=current_url,
                    html=current_html,
                    make_filter=make,
                    model_filter=model,
                    vehicle_category=vehicle_category,
                    platform_id=route.platform_id if route else None,
                )
                # Apply Team Velocity SRP payment enrichment (lease prices + authoritative
                # cash price) when the structured path succeeds.  This is the hot path for
                # Team Velocity dealers; extract_vehicles_from_html handles the LLM fallback.
                if ext_result is not None and ext_result.vehicles:
                    enriched_tv = await enrich_team_velocity_srp_pricing(
                        current_html, current_url, ext_result.vehicles
                    )
                    if enriched_tv is not ext_result.vehicles:
                        ext_result = ext_result.model_copy(update={"vehicles": enriched_tv})
                if extraction_mode and extraction_mode.startswith("provider:"):
                    async with metrics_lock:
                        extraction_metrics["pages_provider"] += 1
                elif extraction_mode == "provider":
                    async with metrics_lock:
                        extraction_metrics["pages_provider"] += 1
                elif extraction_mode == "structured":
                    async with metrics_lock:
                        extraction_metrics["pages_structured"] += 1

                if ext_result is None:
                    is_family_inventory_route = bool(
                        route
                        and route.platform_id
                        in {
                            "ford_family_inventory",
                            "gm_family_inventory",
                            "honda_acura_inventory",
                            "nissan_infiniti_inventory",
                            "oneaudi_falcon",
                            "tesla_inventory",
                            "toyota_lexus_oem_inventory",
                        }
                    )
                    inv_path = urlsplit(current_url or "").path.rstrip("/").lower()
                    cond = (vehicle_condition or "all").strip().lower()
                    is_tv_style_broad_inventory = bool(
                        route
                        and route.platform_id in {"team_velocity", "dealer_inspire", "nissan_infiniti_inventory"}
                        and cond in {"new", "used"}
                        and inv_path == f"/inventory/{cond}"
                    )
                    make_signal = bool(
                        make.strip()
                        and (
                            html_mentions_make(current_html, make)
                            or html_mentions_make(d.name, make)
                            or html_mentions_make(current_url or "", make)
                            or html_mentions_make(website, make)
                        )
                    )
                    if make.strip() and not make_signal and not is_family_inventory_route:
                        logger.info(
                            "Skipping extraction for %s: no make mention (%r) in HTML",
                            current_url,
                            make.strip(),
                        )
                        skip_info = (
                            f'No "{make.strip()}" mention found on this page; skipped extraction.'
                        )
                        break

                    if (
                        model.strip()
                        and not html_mentions_model(current_html, model)
                        and not is_family_inventory_route
                        and not is_tv_style_broad_inventory
                    ):
                        logger.info(
                            "Skipping extraction for %s: no model mention (%r) in HTML",
                            current_url,
                            model.strip(),
                        )
                        skip_info = (
                            f'No "{model.strip()}" found on this page; skipped extraction.'
                        )
                        break

                if route and route.platform_id in {"dealer_on", "harley_digital_showroom"} and current_method == "direct":
                    # H-D Room58 / digital-showroom SRPs are fully SSR on direct HTTP; forcing managed
                    # JS render on paginated ?page=N fetches often returns thinner DOM and breaks next-page
                    # detection — keep subsequent pages on cheap direct fetch when it already worked.
                    route.requires_render = False

                await _emit(
                    sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": d.name,
                            "website": website,
                            "current_url": current_url,
                            "status": "parsing",
                            "fetch_method": current_method,
                            "platform_id": route.platform_id if route else None,
                            "platform_source": route.cache_status if route else "none",
                            "strategy_used": route.extraction_mode if route else "generic",
                            "extraction": extraction_mode or "llm",
                        },
                    )
                )
                if ext_result is None:
                    if _dealer_budget_relief_active(score_card):
                        skip_info = (
                            "Skipped AI extraction for a low-priority dealership after search reached budget targets."
                        )
                        break
                    try:
                        llm_timeout = _phase_timeout(parse_timeout)
                        if llm_timeout is None:
                            if pages_scraped == 0:
                                await _emit(
                                    sse_pack(
                                        "dealership",
                                        {
                                            "index": index,
                                            "total": len(dealers),
                                            "name": d.name,
                                            "website": website,
                                            "current_url": current_url,
                                            "status": "error",
                                            "error": "Timed out while processing this dealership. Skipping to keep search moving.",
                                        },
                                    )
                                )
                            break
                        ext_result = await asyncio.wait_for(
                            extract_vehicles_from_html(
                                page_url=current_url,
                                html=current_html,
                                make_filter=make,
                                model_filter=model,
                                vehicle_category=vehicle_category,
                            ),
                            timeout=llm_timeout,
                        )
                        async with metrics_lock:
                            extraction_metrics["pages_llm"] += 1
                    except asyncio.TimeoutError:
                        msg = f"Timed out during AI extraction after ~{int(parse_timeout)}s."
                        logger.warning("Parse timed out for %s", current_url)
                        async with metrics_lock:
                            extraction_metrics["pages_llm_failed"] += 1
                        if pages_scraped == 0:
                            await append_dealer_error(
                                msg,
                                current_url=current_url,
                                phase="parse",
                                platform_id=route.platform_id if route else None,
                                fetch_method=current_method,
                            )
                        break
                    except Exception as e:
                        logger.warning("Parse failed for %s: %s", current_url, e)
                        async with metrics_lock:
                            extraction_metrics["pages_llm_failed"] += 1
                        if pages_scraped == 0:
                            await append_dealer_error(
                                str(e),
                                current_url=current_url,
                                phase="parse",
                                platform_id=route.platform_id if route else None,
                                fetch_method=current_method,
                            )
                        break

                page_vehicle_condition = infer_vehicle_condition_from_page(current_url, current_html)
                normalized_vehicles: list[VehicleListing] = []
                for v in ext_result.vehicles:
                    w = (
                        v.model_copy(update={"vehicle_condition": page_vehicle_condition})
                        if v.vehicle_condition is None and page_vehicle_condition is not None
                        else v
                    )
                    w = apply_page_make_scope(w, current_url, make)
                    w = apply_eu_make_default_from_dealer_context(
                        w,
                        requested_make=make,
                        dealer_domain=domain or "",
                        dealer_name=d.name,
                        market_region=market_region,
                    )
                    normalized_vehicles.append(w)
                if ext_result.pagination is not None:
                    latest_pagination = ext_result.pagination
                filtered = [
                    v
                    for v in normalized_vehicles
                    if listing_matches_filters(v, make, model)
                    and listing_matches_vehicle_condition(v, vehicle_condition)
                    and listing_matches_inventory_scope(v, inventory_scope)
                ]
                if (
                    route
                    and route.platform_id == "dealer_on"
                    and (
                        _needs_vdp_enrichment(filtered)
                        or (
                            len(filtered) <= 18
                            and _needs_vdp_attribute_enrichment(filtered)
                        )
                    )
                ):
                    seconds_remaining = dealer_timeout - (time.perf_counter() - dealer_started_at)
                    enrich_limit = min(10, len(filtered))
                    if seconds_remaining < 45.0:
                        enrich_limit = 0
                    elif seconds_remaining < 70.0:
                        enrich_limit = min(enrich_limit, 5)
                    elif seconds_remaining < 95.0:
                        enrich_limit = min(enrich_limit, 8)
                    if enrich_limit == 0:
                        logger.info(
                            "Skipping DealerOn VDP enrichment for %s due to low remaining budget (%.1fs)",
                            d.name,
                            seconds_remaining,
                        )
                    else:
                        enriched_prefix = await asyncio.gather(
                            *[_enrich_vehicle_from_vdp(v) for v in filtered[:enrich_limit]]
                        )
                        filtered = list(enriched_prefix) + filtered[enrich_limit:]
                if (
                    route
                    and route.platform_id == "dealer_dot_com"
                    and vehicle_condition in {"used", "all"}
                    and _needs_vdp_usage_enrichment(filtered)
                ):
                    seconds_remaining = dealer_timeout - (time.perf_counter() - dealer_started_at)
                    candidate_indexes = [
                        i
                        for i, listing in enumerate(filtered)
                        if listing.listing_url
                        and listing.usage_value is None
                        and listing.mileage is None
                        and (
                            not listing.vehicle_condition
                            or listing.vehicle_condition == "used"
                        )
                    ]
                    enrich_limit = min(6, len(candidate_indexes))
                    if seconds_remaining < 40.0:
                        enrich_limit = 0
                    elif seconds_remaining < 60.0:
                        enrich_limit = min(enrich_limit, 3)
                    if enrich_limit == 0:
                        logger.info(
                            "Skipping Dealer.com usage VDP enrichment for %s due to low remaining budget (%.1fs)",
                            d.name,
                            seconds_remaining,
                        )
                    else:
                        target_indexes = candidate_indexes[:enrich_limit]
                        enriched_listings = await asyncio.gather(
                            *[_enrich_vehicle_from_vdp(filtered[idx]) for idx in target_indexes]
                        )
                        for idx, enriched_listing in zip(target_indexes, enriched_listings, strict=False):
                            filtered[idx] = enriched_listing
                page_progress_payload = _pagination_progress_payload(
                    latest_pagination,
                    pages_scraped=pages_scraped + 1,
                )
                deduped_filtered = []
                for v in filtered:
                    key = _listing_emit_key(v)
                    if key in emitted_listing_keys:
                        continue
                    emitted_listing_keys.add(key)
                    deduped_filtered.append(v)
                if (
                    route
                    and route.platform_id in {"shift_digital", "harley_digital_showroom"}
                    and _is_harley_search(make, route)
                    and _needs_harley_vdp_enrichment(deduped_filtered)
                ):
                    seconds_remaining = dealer_timeout - (time.perf_counter() - dealer_started_at)
                    candidate_indexes = [
                        i
                        for i, listing in enumerate(deduped_filtered)
                        if listing.listing_url
                        and (
                            listing.price is None
                            or (not listing.vin)
                            or (not listing.exterior_color)
                            or (not listing.availability_status)
                        )
                    ]
                    enrich_limit = min(4, len(candidate_indexes))
                    if seconds_remaining < 75.0:
                        enrich_limit = 0
                    elif seconds_remaining < 110.0:
                        enrich_limit = min(enrich_limit, 2)
                    if enrich_limit == 0:
                        logger.info(
                            "Skipping Harley VDP enrichment for %s due to low remaining budget (%.1fs)",
                            d.name,
                            seconds_remaining,
                        )
                    else:
                        target_indexes = candidate_indexes[:enrich_limit]
                        enriched_listings = await asyncio.gather(
                            *[
                                _enrich_vehicle_from_vdp(
                                    deduped_filtered[idx],
                                    prefer_detail_overlay=True,
                                )
                                for idx in target_indexes
                            ]
                        )
                        for idx, enriched_listing in zip(target_indexes, enriched_listings, strict=False):
                            deduped_filtered[idx] = enriched_listing
                if deduped_filtered:
                    deduped_filtered = await enrich_vehicle_listings_with_vin_data(deduped_filtered)
                if deduped_filtered and recorder is not None and recorder.user_id is not None:
                    try:
                        history_map = recorder.store.get_inventory_history_map(recorder.user_id, deduped_filtered)
                    except Exception:
                        history_map = {}
                    if history_map:
                        enriched_for_history: list[VehicleListing] = []
                        for listing in deduped_filtered:
                            history = history_map.get(inventory_history_key(listing))
                            if history is None:
                                enriched_for_history.append(listing)
                                continue
                            enriched_for_history.append(
                                listing.model_copy(
                                    update=build_listing_history_fields(
                                        history,
                                        current_price=listing.price,
                                        observed_at=time.time(),
                                    )
                                )
                            )
                        deduped_filtered = enriched_for_history
                if deduped_filtered:
                    historical_pool = _load_historical_snapshot_pool()
                    if historical_pool:
                        enriched_for_market_history: list[VehicleListing] = []
                        for listing in deduped_filtered:
                            if not market_valuation_enabled_for_listing(listing):
                                enriched_for_market_history.append(listing)
                                continue
                            historical_points = historical_market_points_for_listing(listing, historical_pool)
                            if len(historical_points) < 3:
                                enriched_for_market_history.append(listing)
                                continue
                            historical_prices = [float(point["price"]) for point in historical_points if point.get("price")]
                            historical_median = _mv_median(historical_prices)
                            enriched_for_market_history.append(
                                listing.model_copy(
                                    update={
                                        "historical_market_prices": historical_prices,
                                        "historical_market_price_points": historical_points,
                                        "historical_market_sample_count": len(historical_prices),
                                        "historical_market_median": historical_median,
                                    }
                                )
                            )
                        deduped_filtered = enriched_for_market_history
                vdicts = [v.model_dump(exclude_none=True) for v in deduped_filtered]
                logger.info(
                    "scrape_inventory_page dealer=%r domain=%s platform=%s url=%s page=%s/%s "
                    "raw=%s filtered=%s emitted=%s next_page=%s extract=%s fetch=%s",
                    d.name,
                    domain or "",
                    route.platform_id if route else "",
                    current_url or "",
                    pages_scraped,
                    page_budget,
                    len(normalized_vehicles),
                    len(filtered),
                    len(deduped_filtered),
                    ext_result.next_page_url,
                    extraction_mode or "",
                    current_method,
                )
                if page_progress_payload:
                    await _emit(
                        sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "current_url": current_url,
                                "status": "parsing",
                                "listings_found": total_vehicles + len(deduped_filtered),
                                **page_progress_payload,
                            },
                        )
                    )
                suspicious_dealer_dot_com_pagination = bool(
                    route
                    and route.platform_id == "dealer_dot_com"
                    and current_url
                    and current_url_scoped
                    and pages_scraped == 0
                    and normalized_vehicles
                    and latest_pagination is not None
                    and latest_pagination.source == "inventory_api"
                    and latest_pagination.total_results is not None
                    and latest_pagination.total_results < len(normalized_vehicles)
                )
                if (
                    route
                    and route.platform_id == "dealer_dot_com"
                    and make.strip()
                    and not model.strip()
                    and (not normalized_vehicles or suspicious_dealer_dot_com_pagination)
                    and not dealer_dot_com_make_retry_attempted
                    and current_url
                ):
                    dealer_dot_com_make_retry_attempted = True
                    # If the current URL already has a query-param make filter, retry without it
                    # (the site may not support that filter directly).
                    retry_url = _drop_query_keys(
                        current_url,
                        {"make", "model", "search", "gvbodystyle"},
                    )
                    if retry_url.rstrip("/") != current_url.rstrip("/") and retry_url not in queued_urls:
                        queued_urls.add(retry_url)
                        pending_urls.insert(0, retry_url)
                        logger.info(
                            "Retrying Dealer.com scoped search without query filter for %s: %s -> %s",
                            d.name,
                            current_url,
                            retry_url,
                        )
                    else:
                        # Current URL has no removable query filter (e.g. path-based /new-buick/…).
                        # For suspicious under-counted scoped pages, fan back out to the broad SRP and
                        # rely on downstream make filtering. For true zero-result scoped pages, keep the
                        # make query param so the Dealer.com POST-body injection can recover inventory.
                        try:
                            if suspicious_dealer_dot_com_pagination:
                                canonical = resolve_inventory_url_for_provider(
                                    "",
                                    website,
                                    route,
                                    vehicle_condition=vehicle_condition,
                                    make="",
                                    model="",
                                    fallback_url=base_url,
                                )
                            else:
                                parts = urlsplit(current_url)
                                canonical = urlunsplit((
                                    parts.scheme,
                                    parts.netloc,
                                    "/new-inventory/index.htm" if vehicle_condition != "used" else "/used-inventory/index.htm",
                                    urlencode({"make": make}),
                                    "",
                                ))
                            if canonical not in queued_urls:
                                queued_urls.add(canonical)
                                pending_urls.insert(0, canonical)
                                logger.info(
                                    "DDC scoped page looked unreliable for %s; falling back to canonical SRP: %s",
                                    d.name,
                                    canonical,
                                )
                        except Exception:
                            pass
                ford_scoped_zero_results = bool(
                    route
                    and route.platform_id == "ford_family_inventory"
                    and scoped_inventory_url
                    and current_url
                    and not vdicts
                    and _looks_like_zero_inventory_results_page(current_html, current_url)
                )
                dealer_on_scoped_empty_results = bool(
                    route
                    and route.platform_id == "dealer_on"
                    and current_url
                    and not vdicts
                    and current_url_scoped
                )
                tesla_zero_results = bool(
                    route
                    and route.platform_id == "tesla_inventory"
                    and current_url
                    and not vdicts
                    and _looks_like_zero_inventory_results_page(current_html, current_url)
                )
                tesla_unscoped_retry = bool(
                    route
                    and route.platform_id == "tesla_inventory"
                    and current_url
                    and not vdicts
                    and not current_url_scoped
                )
                if (
                    ford_scoped_zero_results
                    or dealer_on_scoped_empty_results
                    or tesla_zero_results
                    or tesla_unscoped_retry
                ):
                    recovery_candidates = _inventory_url_recovery_candidates(
                        inv_url=current_url,
                        base_url=base_url,
                        route=route,
                        make=make,
                        model=model,
                        vehicle_condition=vehicle_condition,
                        fallback_zip=dealer_zip,
                        fallback_range_miles=radius_miles,
                    )
                    for retry_url in recovery_candidates:
                        if retry_url.rstrip("/") == current_url.rstrip("/") or retry_url in queued_urls:
                            continue
                        queued_urls.add(retry_url)
                        pending_urls.append(retry_url)
                        if route and route.platform_id == "ford_family_inventory":
                            ford_recovery_urls.append(retry_url)
                    next_url = None
                if (
                    route
                    and route.platform_id in {"dealer_inspire", "team_velocity", "nissan_infiniti_inventory", "honda_acura_inventory"}
                    and not model.strip()
                    and _looks_like_model_index_batch(vdicts, current_url)
                ):
                    fallback_urls = (
                        dealer_inspire_fallback_urls
                        if route.platform_id == "dealer_inspire"
                        else inventory_model_fallback_urls
                    )
                    for extra_url in fallback_urls:
                        if extra_url not in queued_urls:
                            queued_urls.add(extra_url)
                            pending_urls.append(extra_url)
                    vdicts = []
                if vdicts:
                    if domain and pages_scraped == 0:
                        inv_url_cache[domain] = current_url
                    if domain and route and pages_scraped == 0:
                        remember_provider_success(
                            domain=domain,
                            route=route,
                            inventory_url_hint=current_url,
                            requires_render=("rendered" in current_method) or route.requires_render,
                        )
                    total_vehicles += len(vdicts)
                    listings_for_cache.extend(vdicts)
                    for listing_chunk in _chunk_listings(vdicts):
                        if recorder is not None:
                            recorder.note_vehicle_batch(
                                batch_size=len(listing_chunk),
                                platform_id=route.platform_id if route else None,
                                fetch_method=current_method,
                            )
                            recorder.capture_listing_batch(
                                dealership=d.name, website=website, listings=listing_chunk
                            )
                        await _emit(
                            sse_pack(
                                "vehicles",
                                {
                                    "dealership": d.name,
                                    "website": website,
                                    "current_url": current_url,
                                    "count": len(listing_chunk),
                                    "listings": listing_chunk,
                                },
                            )
                        )

                next_url = ext_result.next_page_url
                if (
                    route
                    and route.platform_id == "dealer_inspire"
                    and not model.strip()
                    and vehicle_condition == "new"
                    and "?_p=" in current_url
                    and not vdicts
                ):
                    for extra_url in dealer_inspire_fallback_urls:
                        if extra_url not in queued_urls:
                            queued_urls.add(extra_url)
                            pending_urls.append(extra_url)
                # Broad /inventory/{condition} SRPs often SSR only a slice of vehicles; discovered
                # model links (e.g. /inventory/new/acura/integra) must be queued even when the user
                # already filtered by model — otherwise make+model searches can see zero rows while
                # the generic page never mentions that model in the first HTML chunk.
                if (
                    route
                    and route.platform_id in {
                        "team_velocity",
                        "nissan_infiniti_inventory",
                        "dealer_inspire",
                        "honda_acura_inventory",
                    }
                    and current_url
                    and urlsplit(current_url).path.rstrip("/").lower() in {"/inventory/new", "/inventory/used"}
                ):
                    appended_tv_model_fallback = False
                    for extra_url in inventory_model_fallback_urls:
                        if extra_url not in queued_urls:
                            queued_urls.add(extra_url)
                            pending_urls.append(extra_url)
                            appended_tv_model_fallback = True
                    if appended_tv_model_fallback:
                        next_url = None
                if next_url and next_url not in queued_urls:
                    queued_urls.add(next_url)
                    pending_urls.append(next_url)
                if not _dealer_budget_relief_active(score_card):
                    page_budget = _expand_page_budget(
                        page_budget,
                        pagination=ext_result.pagination,
                        has_pending_urls=bool(pending_urls),
                        absolute_cap=absolute_page_cap,
                    )

                current_url = pending_urls.pop(0) if pending_urls else None
                pages_scraped += 1

                if not vdicts and current_url is None:
                    break  # Stop pagination if no vehicles found
            if current_url and pages_scraped >= page_budget and page_budget >= absolute_page_cap and not skip_info:
                skip_info = (
                    f"Stopped after {absolute_page_cap} pages at the pagination safety cap; "
                    "additional inventory pages may remain."
                )

            done_payload: dict[str, Any] = {
                "index": index,
                "total": len(dealers),
                "name": d.name,
                "website": website,
                "status": "done",
                "listings_found": total_vehicles,
                "scoped_inventory_url": scoped_inventory_url,
                "fetch_methods": fetch_methods_used,
                "platform_id": route.platform_id if 'route' in locals() and route else None,
                "platform_source": route.cache_status if 'route' in locals() and route else None,
                "strategy_used": route.extraction_mode if 'route' in locals() and route else None,
                **_pagination_progress_payload(latest_pagination, pages_scraped=pages_scraped),
            }
            active_route = route if 'route' in locals() else None
            if ford_recovery_urls:
                done_payload["ford_recovery_urls"] = ford_recovery_urls
            suspicious_zero_results = bool(
                active_route
                and active_route.platform_id == "ford_family_inventory"
                and total_vehicles == 0
                and scoped_inventory_url
            )
            if suspicious_zero_results:
                done_payload["zero_results_warning"] = "ford_family_scoped_url_empty"
                if domain:
                    record_provider_failure(domain)
            if skip_info:
                done_payload["info"] = skip_info
            if (
                settings.inventory_cache_enabled
                and listings_for_cache
                and total_vehicles > 0
                and not skip_info
            ):
                await asyncio.to_thread(
                    set_cached_inventory_listings,
                    inv_cache_key,
                    {
                        "listings": listings_for_cache,
                        "platform_id": route.platform_id if route else None,
                    },
                )
            await _emit(sse_pack("dealership", done_payload))
            async with metrics_lock:
                completed_dealer_count += 1
                if total_vehicles > 0:
                    successful_dealer_count += 1
                    streamed_vehicle_count += total_vehicles
            await _record_dealer_score()
            if recorder is not None:
                recorder.note_dealer_done(listings_found=total_vehicles)
                recorder.event(
                    event_type="dealer_done",
                    phase="scrape",
                    level="warning" if suspicious_zero_results else "info",
                    message=f"Finished dealership scrape for {d.name}.",
                    dealership_name=d.name,
                    dealership_website=website,
                    payload=done_payload,
                )
        await _record_dealer_score()
        return

    sse_stream_queue: asyncio.Queue[str | object] = asyncio.Queue()

    async def dealer_worker(index: int, d: DealershipFound) -> None:
        try:
            async with sem:
                try:
                    website = prefer_https_website_url((d.website or "").strip())
                    domain = normalize_dealer_domain(website)
                    score_card = _score_card_for_domain(domain)
                    worker_timeout = _effective_dealer_timeout(
                        requested_pages,
                        dealer_score=score_card.score,
                        failure_streak=score_card.failure_streak,
                    )
                    await asyncio.wait_for(
                        process_one(index, d, sse_stream_queue),
                        timeout=worker_timeout + 15.0,
                    )
                except asyncio.TimeoutError:
                    website = d.website or ""
                    domain = normalize_dealer_domain(website)
                    platform_entry = platform_cache_entries.get(domain)
                    logger.warning(f"{cid_log}Dealership worker timed out for %s", website)
                    if recorder is not None:
                        recorder.note_dealer_failed()
                        recorder.note_dealer_issue(
                            issue_type="timeout",
                            platform_id=platform_entry.platform_id if platform_entry is not None else None,
                            fetch_method=dealer_last_fetch_method.get(domain),
                        )
                        recorder.event(
                            event_type="dealer_timeout",
                            phase="worker",
                            level="warning",
                            message="Timed out while processing this dealership. Skipping to keep search moving.",
                            dealership_name=d.name,
                            dealership_website=website,
                            payload={
                                "index": index,
                                "platform_id": platform_entry.platform_id if platform_entry is not None else None,
                                "fetch_method": dealer_last_fetch_method.get(domain),
                                "error_code": "dealer.timeout",
                            },
                        )
                    await sse_stream_queue.put(
                        sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "address": d.address,
                                "status": "error",
                                "error": (
                                    "Timed out while processing this dealership. "
                                    "Skipping to keep search moving."
                                ),
                            },
                        )
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception(f"{cid_log}Worker failed for dealership {d.name}")
                    error = SearchErrorInfo(
                        code="worker.unhandled_exception",
                        message=str(e),
                        phase="worker",
                        retryable=True,
                    )
                    if recorder is not None:
                        recorder.event(
                            event_type="search_error",
                            phase="worker",
                            level="error",
                            message=error.message,
                            payload={"error": error.to_summary()},
                        )
                    await sse_stream_queue.put(
                        sse_pack("search_error", error.with_correlation_id(correlation_id).to_payload())
                    )
        except asyncio.CancelledError:
            raise
        finally:
            await sse_stream_queue.put(_SSE_STREAM_WORKER_DONE)

    tasks: list[asyncio.Task[None]] = []
    queued_dealer_count = 0
    launched_domains: set[str] = set()

    async def _log_discovery_result() -> None:
        nonlocal final_discovery_logged
        if final_discovery_logged or recorder is None:
            return
        if raw_dealer_count > 0:
            recorder.note_dealer_discovered()
        recorder.event(
            event_type="dealers_discovered",
            phase="places",
            level="info",
            message=f"Discovered {deduped_dealer_count} dealerships with websites.",
            payload={
                "dealer_discovery_count": raw_dealer_count,
                "dealer_deduped_count": deduped_dealer_count,
                "places_metrics": places_metrics.as_dict(),
            },
        )
        final_discovery_logged = True

    def _dealer_needs_render(dealer: DealershipFound) -> bool:
        domain = normalize_dealer_domain((dealer.website or "").strip())
        entry = platform_cache_entries.get(domain)
        if entry is None:
            return True
        return bool(entry.requires_render)

    async def _launch_dealers(batch: list[DealershipFound]) -> int:
        nonlocal queued_dealer_count
        launched_now = 0
        for dealer in batch:
            dealer_domain = normalize_dealer_domain((dealer.website or "").strip())
            if dealer_domain and dealer_domain in launched_domains:
                continue
            if dealer_domain:
                launched_domains.add(dealer_domain)
            queued_dealer_count += 1
            index = queued_dealer_count
            if _dealer_budget_relief_active(_score_card_for_domain(dealer_domain)):
                await sse_stream_queue.put(
                    sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": dealer.name,
                            "website": prefer_https_website_url((dealer.website or "").strip()),
                            "address": dealer.address,
                            "status": "done",
                            "listings_found": 0,
                            "info": "Skipped low-priority dealership after search reached budget targets.",
                        },
                    )
                )
                continue
            await sse_stream_queue.put(sse_pack("dealership", _dealership_queue_payload(index, len(dealers), dealer)))
            tasks.append(asyncio.create_task(dealer_worker(index, dealer)))
            launched_now += 1
        return launched_now

    _PRIORITY_BATCH_SIZE = 2
    deferred_dealers: list[DealershipFound] = []

    try:
        if not progressive_discovery_enabled:
            await _log_discovery_result()
        all_render_heavy = len(dealers) > _PRIORITY_BATCH_SIZE and all(
            _dealer_needs_render(d) for d in dealers
        )
        if all_render_heavy:
            priority_batch = dealers[:_PRIORITY_BATCH_SIZE]
            deferred_dealers = dealers[_PRIORITY_BATCH_SIZE:]
            workers_remaining = await _launch_dealers(priority_batch)
        else:
            workers_remaining = await _launch_dealers(dealers)
        if progressive_discovery_enabled and full_discovery_task is not None and workers_remaining > 0:
            yield sse_pack(
                "status",
                {
                    "message": "Started scraping the first dealerships while discovery continues…",
                    "phase": "scrape",
                    "dealerships_queued": workers_remaining,
                },
            )

        while workers_remaining > 0 or full_discovery_task is not None:
            waiters: list[asyncio.Task[Any] | asyncio.Task[list[DealershipFound]]] = []
            queue_waiter: asyncio.Task[Any] | None = None
            if workers_remaining > 0:
                queue_waiter = asyncio.create_task(sse_stream_queue.get())
                waiters.append(queue_waiter)
            if full_discovery_task is not None:
                waiters.append(full_discovery_task)

            done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            if full_discovery_task is not None and full_discovery_task in done:
                try:
                    discovered_dealers = full_discovery_task.result()
                    raw_dealer_count = len(discovered_dealers)
                    deduped_dealer_count = len(dedupe_dealers_by_domain(discovered_dealers))
                    dealers = (await _rank_dealers(discovered_dealers))[:requested_dealerships]
                    await _log_discovery_result()
                    launched_now = await _launch_dealers(dealers)
                    if launched_now > 0:
                        yield sse_pack(
                            "status",
                            {
                                "message": f"Queued {launched_now} additional dealerships as discovery finished.",
                                "phase": "scrape",
                                "dealerships_queued": len(dealers),
                            },
                        )
                        workers_remaining += launched_now
                except Exception as e:
                    logger.exception(f"{cid_log}Background dealership discovery failed")
                    error = SearchErrorInfo(
                        code="places.background_discovery_failed",
                        message=str(e),
                        phase="places",
                        retryable=True,
                    )
                    if recorder is not None:
                        recorder.event(
                            event_type="places_failed",
                            phase="places",
                            level="warning",
                            message=error.message,
                            payload={"error": error.to_summary(), "places_metrics": places_metrics.as_dict()},
                        )
                    if workers_remaining == 0:
                        yield sse_pack("search_error", error.with_correlation_id(correlation_id).to_payload())
                        yield sse_pack("done", finalize_done(search_failure_payload(error), ok=False))
                        return
                finally:
                    full_discovery_task = None

            if queue_waiter is not None and queue_waiter in done:
                item = queue_waiter.result()
                if item is _SSE_STREAM_WORKER_DONE:
                    workers_remaining -= 1
                    if deferred_dealers:
                        remaining_deferred = deferred_dealers[:]
                        deferred_dealers.clear()
                        launched_deferred = await _launch_dealers(remaining_deferred)
                        workers_remaining += launched_deferred
                else:
                    yield item

            for pending_task in pending:
                if pending_task is not full_discovery_task:
                    pending_task.cancel()

        yield sse_pack(
            "done",
            finalize_done(
                {
                    "ok": True,
                    "dealerships": len(dealers),
                    "dealer_discovery_count": raw_dealer_count,
                    "dealer_deduped_count": deduped_dealer_count,
                    "radius_miles": radius_miles,
                    "vehicle_condition": vehicle_condition,
                    "inventory_scope": inventory_scope,
                    "max_dealerships": requested_dealerships,
                    "max_pages_per_dealer": requested_pages,
                    "effective_search_concurrency": effective_concurrency,
                    "fetch_metrics": dict(fetch_metrics),
                    "extraction_metrics": dict(extraction_metrics),
                },
                ok=True,
            ),
        )
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        if full_discovery_task is not None:
            full_discovery_task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if full_discovery_task is not None:
            await asyncio.gather(full_discovery_task, return_exceptions=True)
        if recorder is not None and not recorder.finalized:
            recorder.event(
                event_type="search_canceled",
                phase="search",
                level="warning",
                message="Search canceled by user.",
                payload={"correlation_id": correlation_id},
            )
            finalize_done(
                {
                    "ok": False,
                    "status": "canceled",
                    "error_message": "Search canceled by user.",
                    "dealerships": len(dealers),
                    "radius_miles": radius_miles,
                    "vehicle_condition": vehicle_condition,
                    "inventory_scope": inventory_scope,
                    "max_dealerships": requested_dealerships,
                    "max_pages_per_dealer": requested_pages,
                    "fetch_metrics": dict(fetch_metrics),
                    "extraction_metrics": dict(extraction_metrics),
                },
                ok=False,
                status="canceled",
            )
        logger.info("%sSearch canceled.", cid_log)
        raise
