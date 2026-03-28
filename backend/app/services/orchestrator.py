"""Coordinates Places → scrape → LLM parse with async iteration for SSE."""

from __future__ import annotations

import asyncio
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
from app.schemas import DealershipFound, PaginationInfo, VehicleListing
from app.services.dealer_platforms import detect_platform_profile
from app.services.economics import build_search_economics, log_economics_line
from app.services.inventory_discovery import discover_sitemap_inventory_urls
from app.services.inventory_filters import (
    apply_page_make_scope,
    infer_vehicle_condition_from_page,
    listing_matches_filters,
    listing_matches_inventory_scope,
    listing_matches_vehicle_condition,
)
from app.services.inventory_result_cache import (
    get_cached_inventory_listings,
    inventory_listings_cache_key,
    set_cached_inventory_listings,
)
from app.services.orchestrator_utils import (
    dedupe_dealers_by_domain,
    domain_fetch_limiter,
    effective_search_concurrency,
    guess_franchise_inventory_srp_url,
    html_mentions_make,
    html_mentions_model,
    prefer_https_website_url,
)
from app.services.parser import extract_vehicles_from_html, try_extract_vehicles_without_llm
from app.services.places import find_car_dealerships, find_dealerships
from app.services.platform_store import normalize_dealer_domain
from app.services.provider_router import (
    ProviderRoute,
    detect_or_lookup_provider,
    record_provider_failure,
    remember_provider_success,
    resolve_inventory_url_for_provider,
)
from app.services.providers import extract_with_provider
from app.services.scrape_logging import ScrapeRunRecorder
from app.services.scraper import PageKind, _looks_like_block_page, fetch_page_html
from app.sse import sse_pack

logger = logging.getLogger(__name__)
_STREAM_LISTING_BATCH_SIZE = 8

# Inventory-page family stacks that should override generic website platforms (DealerOn / Inspire / DDC).
_INVENTORY_FAMILY_PLATFORM_IDS = frozenset(
    {
        "ford_family_inventory",
        "gm_family_inventory",
        "toyota_lexus_oem_inventory",
    }
)


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


def _scope_filter_tokens(raw: str) -> set[str]:
    tokens: set[str] = set()
    for part in (raw or "").split(","):
        value = part.strip().lower()
        if not value:
            continue
        tokens.add(re.sub(r"[^a-z0-9]", "", value))
    return {token for token in tokens if token}


def _inventory_url_uses_scoped_filters(url: str | None, *, make: str, model: str) -> bool:
    if not url:
        return False
    parts = urlsplit(url)
    query = {k.lower(): v.lower() for k, v in parse_qsl(parts.query, keep_blank_values=True)}
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




def _find_inventory_url(
    html: str,
    base_url: str,
    *,
    vehicle_condition: str = "all",
) -> str:
    """Heuristic to find the best 'inventory' link on a dealership homepage."""
    try:
        soup = BeautifulSoup(html, "lxml")
        best_url = base_url
        best_score = -1
        condition = (vehicle_condition or "all").strip().lower()

        for a in soup.find_all("a", href=True):
            href_raw = str(a["href"])
            href = href_raw.lower()
            text = a.get_text(strip=True).lower()
            href_parts = urlsplit(href_raw)
            href_fragment = href_parts.fragment.lower()
            score = 0

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

            # Penalize non-inventory links
            if any(x in href for x in ["service", "parts", "finance", "contact", "about", "specials", "privacy"]):
                score -= 20

            # Heavily penalize external links that aren't subdomains
            from urllib.parse import urlparse
            try:
                parsed_href = urlparse(a['href'])
                if parsed_href.netloc:
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
                    ):
                        score -= 50
            except Exception:
                pass

            if score > best_score and score > 0:
                best_score = score
                absolute_url = urljoin(base_url, href_raw)
                absolute_parts = urlsplit(absolute_url)
                best_url = urlunsplit(
                    (absolute_parts.scheme, absolute_parts.netloc, absolute_parts.path, absolute_parts.query, "")
                )

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
        abs_url = urljoin(base_url, str(a["href"]))
        path = urlsplit(abs_url).path.rstrip("/").lower()
        query = {k.lower(): v.lower() for k, v in parse_qsl(urlsplit(abs_url).query, keep_blank_values=True)}
        if not (path.startswith(target_root + "/") or (path == "/--inventory" and model_tokens)):
            continue
        if model_tokens:
            combined = re.sub(r"[^a-z0-9]", "", f"{path} {a.get_text(strip=True).lower()} {urlsplit(abs_url).query.lower()}")
            query_match = any(key in query for key in ("make", "model"))
            if not query_match and not any(token in combined for token in model_tokens):
                continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        out.append(abs_url)
    return out


def _listing_emit_key(v: Any) -> str:
    return "|".join(
        [
            str(getattr(v, "vehicle_identifier", "") or "").strip().lower(),
            str(getattr(v, "vin", "") or "").strip().lower(),
            str(getattr(v, "listing_url", "") or "").strip().lower(),
            str(getattr(v, "raw_title", "") or "").strip().lower(),
        ]
    )


def _looks_like_model_index_batch(vdicts: list[dict[str, Any]], current_url: str) -> bool:
    path = urlsplit(current_url).path.rstrip("/").lower()
    if path != "/new-vehicles" or not vdicts:
        return False
    strong = False
    for row in vdicts:
        listing_url = str(row.get("listing_url") or "").strip().lower()
        if row.get("vin") or row.get("price") not in (None, ""):
            strong = True
            break
        if "/inventory/" in listing_url or "/vehicle/" in listing_url or "/detail/" in listing_url:
            strong = True
            break
    return not strong


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
    if route is not None and route.platform_id in {"dealer_on", "dealer_inspire"}:
        # These SRPs are often render-heavy in production. Let them go a little
        # deeper than page 1, but cap them well below user-requested deep crawls
        # so a handful of slow dealers do not consume the full worker budget.
        return min(requested_pages, 3)
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
    elif has_pending_urls and budget < absolute_cap:
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


async def _enrich_vehicle_from_vdp(v: VehicleListing) -> VehicleListing:
    if not v.listing_url:
        return v
    try:
        html, _ = await fetch_page_html(v.listing_url, page_kind="inventory", prefer_render=False)
        ext = try_extract_vehicles_without_llm(
            page_url=v.listing_url,
            html=html,
            make_filter=v.make or "",
            model_filter="",
            vehicle_category=v.vehicle_category or "car",
        )
    except Exception:
        return v
    if not ext:
        return v
    candidates = ext.vehicles
    if v.vehicle_identifier:
        for candidate in candidates:
            if (
                candidate.vehicle_identifier
                and candidate.vehicle_identifier.upper() == v.vehicle_identifier.upper()
            ):
                return _merge_vehicle_detail(v, candidate)
    if v.vin:
        for candidate in candidates:
            if candidate.vin and candidate.vin.upper() == v.vin.upper():
                return _merge_vehicle_detail(v, candidate)
    if v.listing_url:
        for candidate in candidates:
            if candidate.listing_url and candidate.listing_url.rstrip("/") == v.listing_url.rstrip("/"):
                return _merge_vehicle_detail(v, candidate)
    if candidates:
        return _merge_vehicle_detail(v, candidates[0])
    return v


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
    max_dealerships: int | None = None,
    max_pages_per_dealer: int | None = None,
    outcome_holder: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    recorder: ScrapeRunRecorder | None = None,
) -> AsyncIterator[str]:
    """
    Yield SSE-formatted strings: status, dealership, vehicles, error, done.
    """
    cid_log = f"[{correlation_id}] " if correlation_id else ""
    logger.info(
        f"{cid_log}Starting search: location={location}, category={vehicle_category}, make={make}, model={model}"
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
                "radius_miles": radius_miles,
            },
        )
    yield sse_pack("status", {"message": "Finding local dealerships…", "phase": "places"})
    requested_dealerships = max(1, min(max_dealerships or settings.max_dealerships, 30))
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

    def finalize_done(base: dict[str, Any], *, ok: bool) -> dict[str, Any]:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        md = int(base.get("max_dealerships", requested_dealerships))
        mp = int(base.get("max_pages_per_dealer", requested_pages))
        rm = int(base.get("radius_miles", radius_miles))
        vc = str(base.get("vehicle_condition", vehicle_condition))
        invs = str(base.get("inventory_scope", inventory_scope))
        economics = build_search_economics(
            fetch_metrics=dict(fetch_metrics),
            extraction_metrics=dict(extraction_metrics),
            requested_dealerships=md,
            requested_pages=mp,
            radius_miles=rm,
            duration_ms=duration_ms,
            vehicle_condition=vc,
            inventory_scope=invs,
            ok=ok,
        )
        payload = {**base, "duration_ms": duration_ms, "economics": economics, "correlation_id": correlation_id}
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
            )
        return payload

    try:
        if (vehicle_category or "car").strip().lower() == "car":
            dealers = await find_car_dealerships(
                location,
                make=make,
                model=model,
                limit=min(requested_dealerships * 3, 30),
                radius_miles=radius_miles,
            )
        else:
            dealers = await find_dealerships(
                location,
                make=make,
                model=model,
                vehicle_category=vehicle_category,
                limit=min(requested_dealerships * 3, 30),
                radius_miles=radius_miles,
            )
    except Exception as e:
        logger.exception(f"{cid_log}Places search failed")
        if recorder is not None:
            recorder.event(
                event_type="places_failed",
                phase="places",
                level="error",
                message=str(e),
                payload={"error": str(e)},
            )
        yield sse_pack("search_error", {"message": str(e), "phase": "places"})
        yield sse_pack("done", finalize_done({"ok": False, "error_message": str(e)}, ok=False))
        return

    raw_dealer_count = len(dealers)
    dealers = dedupe_dealers_by_domain(dealers)
    deduped_dealer_count = len(dealers)
    dealers = dealers[: requested_dealerships]
    if not dealers:
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
    yield sse_pack(
        "status",
        {
            "message": (
                f"Found {len(dealers)} dealerships. Scraping inventory… "
                f"(requested {requested_dealerships}, radius {radius_miles} mi, "
                f"condition {vehicle_condition}, category {vehicle_category}, workers {effective_concurrency})"
            ),
            "phase": "scrape",
        },
    )

    sem = asyncio.Semaphore(effective_concurrency)
    dealer_timeout = max(30.0, settings.dealership_timeout)
    # Keep per-phase timeouts inside the overall dealer worker budget.
    fetch_timeout = min(settings.scrape_timeout * 3 + 5.0, max(20.0, dealer_timeout * 0.5))
    parse_timeout = min(settings.openai_timeout + 5.0, max(20.0, dealer_timeout * 0.35))
    metrics_lock = asyncio.Lock()
    inv_url_cache: dict[str, str] = {}

    async def process_one(index: int, d: DealershipFound) -> list[str]:
        chunks: list[str] = []
        dealer_started_at = time.perf_counter()
        website = prefer_https_website_url((d.website or "").strip())
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
        fetch_methods_used: list[str] = []
        inv_cache_key = inventory_listings_cache_key(
            website=website,
            domain=domain,
            make=make,
            model=model,
            vehicle_condition=vehicle_condition,
            inventory_scope=inventory_scope,
            max_pages=requested_pages,
        )
        listings_for_cache: list[dict] = []

        async def _fetch(
            url: str,
            page_kind: PageKind,
            *,
            prefer_render: bool = False,
            platform_id: str | None = None,
        ) -> tuple[str, str]:
            host_key = normalize_dealer_domain(url) or domain or "unknown"
            local_fetch_metrics: dict[str, int] = {}
            async with domain_fetch_limiter(host_key):
                html, method = await fetch_page_html(
                    url,
                    page_kind=page_kind,
                    prefer_render=prefer_render,
                    metrics=local_fetch_metrics,
                    platform_id=platform_id,
                )
            fetch_methods_used.append(method)
            async with metrics_lock:
                key = f"fetch_{method}"
                fetch_metrics[key] += 1
                for metric_key, metric_value in local_fetch_metrics.items():
                    if metric_value:
                        fetch_metrics[metric_key] += metric_value
            return html, method

        def _phase_timeout(
            base_timeout: float,
            *,
            reserve_seconds: float = 8.0,
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

        def append_dealer_error(message: str, *, current_url: str | None = None, phase: str = "scrape") -> None:
            if recorder is not None:
                recorder.note_dealer_failed()
                recorder.event(
                    event_type="dealer_error",
                    phase=phase,
                    level="warning",
                    message=message,
                    dealership_name=d.name,
                    dealership_website=website,
                    payload={"index": index, "current_url": current_url},
                )
            chunks.append(
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

        chunks.append(
            sse_pack(
                "dealership",
                {
                    "index": index,
                    "total": len(dealers),
                    "name": d.name,
                    "website": website,
                    "address": d.address,
                    "status": "scraping",
                },
            )
        )
        async with sem:
            cached_inv = await asyncio.to_thread(get_cached_inventory_listings, inv_cache_key)
            if cached_inv and cached_inv.get("listings"):
                fetch_methods_used.append("inventory_cache")
                cached_listings = cached_inv["listings"]
                total_cached = 0
                for listing_chunk in _chunk_listings(cached_listings):
                    total_cached += len(listing_chunk)
                    chunks.append(
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
                chunks.append(
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
                        },
                    )
                )
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
                return chunks

            # 1. Fetch homepage to find inventory link
            base_url = website
            homepage_html: str | None = None
            homepage_method: str | None = None
            seed_inventory_url: str | None = None
            try:
                homepage_timeout = _phase_timeout(fetch_timeout)
                if homepage_timeout is None:
                    append_dealer_error(
                        "Timed out while processing this dealership. Skipping to keep search moving."
                    )
                    return chunks
                homepage_html, homepage_method = await asyncio.wait_for(
                    _fetch(website, "homepage"),
                    timeout=homepage_timeout,
                )

                # If the homepage has a canonical link, it likely redirected to a different domain.
                # Use the canonical URL as the new base website to ensure inventory links resolve correctly.
                try:
                    soup = BeautifulSoup(homepage_html, "lxml")
                    canonical = soup.find("link", rel="canonical")
                    if canonical and canonical.get("href"):
                        canonical_href = canonical["href"].strip()
                        if canonical_href.startswith("http"):
                            domain = normalize_dealer_domain(canonical_href)
                            base_url = canonical_href
                except Exception:
                    pass
            except asyncio.TimeoutError:
                logger.warning(f"{cid_log}Scrape timed out for %s", website)
                homepage_timed_out_msg = f"Timed out while fetching pages after ~{int(fetch_timeout)}s."
                guess_inv = guess_franchise_inventory_srp_url(base_url, vehicle_condition)
                if guess_inv and guess_inv.rstrip("/") != prefer_https_website_url(base_url).rstrip("/"):
                    chunks.append(
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
                        homepage_html, homepage_method = await asyncio.wait_for(
                            _fetch(guess_inv, "inventory", prefer_render=True),
                            timeout=rescue_timeout,
                        )
                        seed_inventory_url = guess_inv
                        logger.info(
                            "Recovered dealership %s after homepage timeout using guessed SRP %s",
                            d.name,
                            guess_inv,
                        )
                    except Exception as rescue_error:
                        logger.warning(
                            "%sHomepage timeout rescue via guessed SRP failed for %s: %s",
                            cid_log,
                            website,
                            rescue_error,
                        )
                        if domain:
                            record_provider_failure(domain)
                        append_dealer_error(homepage_timed_out_msg)
                        return chunks
                else:
                    if domain:
                        record_provider_failure(domain)
                    append_dealer_error(homepage_timed_out_msg)
                    return chunks
            except Exception as e:
                logger.warning(f"{cid_log}Scrape failed for %s: %s", website, e)
                guess_inv = guess_franchise_inventory_srp_url(base_url, vehicle_condition)
                if guess_inv and guess_inv.rstrip("/") != prefer_https_website_url(base_url).rstrip("/"):
                    chunks.append(
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
                        homepage_html, homepage_method = await asyncio.wait_for(
                            _fetch(guess_inv, "inventory", prefer_render=True),
                            timeout=rescue_timeout,
                        )
                        seed_inventory_url = guess_inv
                        logger.info(
                            "Recovered dealership %s after homepage fetch failure using guessed SRP %s",
                            d.name,
                            guess_inv,
                        )
                    except Exception as rescue_error:
                        logger.warning(
                            "%sHomepage rescue via guessed SRP failed for %s: %s",
                            cid_log,
                            guess_inv,
                            rescue_error,
                        )
                        if domain:
                            record_provider_failure(domain)
                        append_dealer_error(str(e))
                        return chunks
                else:
                    if domain:
                        record_provider_failure(domain)
                    append_dealer_error(str(e))
                    return chunks

            route = None
            inv_url = seed_inventory_url or base_url

            if homepage_html is not None and seed_inventory_url is None:
                route = detect_or_lookup_provider(domain=domain, website=base_url, homepage_html=homepage_html)
                if route:
                    async with metrics_lock:
                        fetch_metrics[f"platform_{route.platform_id}"] += 1
                        fetch_metrics[f"platform_source_{route.cache_status}"] += 1
                inv_url = resolve_inventory_url_for_provider(
                    homepage_html,
                    base_url,
                    route,
                    fallback_url=_find_inventory_url(
                        homepage_html,
                        base_url,
                        vehicle_condition=vehicle_condition,
                    ),
                    make=make,
                    model=model,
                    vehicle_condition=vehicle_condition,
                )
            if inv_url == base_url and domain in inv_url_cache:
                cached = inv_url_cache[domain]
                if cached and cached.rstrip("/") != base_url.rstrip("/"):
                    inv_url = cached
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

            current_html = homepage_html or ""
            current_method = homepage_method or "unknown"

            # If inventory is on a different URL, fetch it before first parse.
            if seed_inventory_url is None and inv_url and inv_url != base_url:
                chunks.append(
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
                    inv_timeout = _phase_timeout(fetch_timeout)
                    if inv_timeout is None:
                        append_dealer_error(
                            "Timed out while processing this dealership. Skipping to keep search moving.",
                            current_url=inv_url,
                        )
                        return chunks
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
                    if domain:
                        record_provider_failure(domain)
                    inventory_retry_url = guess_franchise_inventory_srp_url(base_url, vehicle_condition)
                    if inventory_retry_url and inventory_retry_url.rstrip("/") != (inv_url or "").rstrip("/"):
                        chunks.append(
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
                            retry_timeout = _phase_timeout(fetch_timeout, reserve_seconds=6.0)
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
                            append_dealer_error(
                                f"Timed out while fetching inventory page after ~{int(fetch_timeout)}s.",
                                current_url=inv_url,
                            )
                            return chunks
                    else:
                        append_dealer_error(
                            f"Timed out while fetching inventory page after ~{int(fetch_timeout)}s.",
                            current_url=inv_url,
                        )
                        return chunks
                except Exception as e:
                    logger.warning(f"{cid_log}Initial inventory scrape failed for %s: %s", inv_url, e)
                    if domain:
                        record_provider_failure(domain)
                    append_dealer_error(str(e), current_url=inv_url)
                    return chunks
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
                    chunks.append(
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
                            ),
                            make=make,
                            model=model,
                            vehicle_condition=vehicle_condition,
                        )
                        if rendered_inv_url.rstrip("/") != prefer_https_website_url(base_url).rstrip("/"):
                            chunks.append(
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
            if route and route.platform_id == "team_velocity":
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
            absolute_page_cap = max(1, settings.search_max_pages_per_dealer_cap)
            if route_page_cap < requested_pages:
                absolute_page_cap = min(absolute_page_cap, route_page_cap)
            page_budget = min(route_page_cap, absolute_page_cap)
            total_vehicles = 0
            skip_info: str | None = None
            latest_pagination: PaginationInfo | None = None
            dealer_dot_com_make_retry_attempted = False
            queued_urls: set[str] = {current_url} if current_url else set()
            pending_urls: list[str] = []
            emitted_listing_keys: set[str] = set()
            dealer_inspire_fallback_urls = (
                _dealer_inspire_model_inventory_urls(
                    current_html,
                    current_url or base_url,
                    vehicle_condition=vehicle_condition,
                    model=model,
                )
                if route
                and route.platform_id == "dealer_inspire"
                and vehicle_condition in {"new", "used"}
                and current_url
                and urlsplit(current_url).path.rstrip("/").lower() in {"/new-vehicles", "/used-vehicles"}
                else []
            )
            team_velocity_fallback_urls = (
                _team_velocity_model_inventory_urls(
                    current_html,
                    current_url or base_url,
                    vehicle_condition=vehicle_condition,
                    model=model,
                )
                if route
                and route.platform_id in {"team_velocity", "nissan_infiniti_inventory"}
                and vehicle_condition in {"new", "used"}
                and current_url
                and urlsplit(current_url).path.rstrip("/").lower()
                == f"/inventory/{vehicle_condition}"
                else []
            )

            while current_url and pages_scraped < page_budget:
                if pages_scraped > 0:
                    chunks.append(
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

                ext_result = extract_with_provider(
                    route.platform_id if route else None,
                    page_url=current_url,
                    html=current_html,
                    make_filter=make,
                    model_filter=model,
                )
                if ext_result is not None:
                    extraction_mode = f"provider:{route.platform_id}" if route else "provider"
                    async with metrics_lock:
                        extraction_metrics["pages_provider"] += 1
                else:
                    ext_result = try_extract_vehicles_without_llm(
                        page_url=current_url,
                        html=current_html,
                        make_filter=make,
                        model_filter=model,
                        vehicle_category=vehicle_category,
                        platform_id=route.platform_id if route else None,
                    )
                    extraction_mode = "structured" if ext_result is not None else None
                    if ext_result is not None:
                        async with metrics_lock:
                            extraction_metrics["pages_structured"] += 1

                if ext_result is None:
                    if make.strip() and not html_mentions_make(current_html, make):
                        logger.info(
                            "Skipping extraction for %s: no make mention (%r) in HTML",
                            current_url,
                            make.strip(),
                        )
                        skip_info = (
                            f'No "{make.strip()}" mention found on this page; skipped extraction.'
                        )
                        break

                    if model.strip() and not html_mentions_model(current_html, model):
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

                chunks.append(
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
                    try:
                        llm_timeout = _phase_timeout(parse_timeout)
                        if llm_timeout is None:
                            if pages_scraped == 0:
                                chunks.append(
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
                            append_dealer_error(msg, current_url=current_url, phase="parse")
                        break
                    except Exception as e:
                        logger.warning("Parse failed for %s: %s", current_url, e)
                        async with metrics_lock:
                            extraction_metrics["pages_llm_failed"] += 1
                        if pages_scraped == 0:
                            append_dealer_error(str(e), current_url=current_url, phase="parse")
                        break

                page_vehicle_condition = infer_vehicle_condition_from_page(current_url, current_html)
                normalized_vehicles = [
                    (
                        apply_page_make_scope(
                            (
                                v.model_copy(update={"vehicle_condition": page_vehicle_condition})
                                if v.vehicle_condition is None and page_vehicle_condition is not None
                                else v
                            ),
                            current_url,
                            make,
                        )
                    )
                    for v in ext_result.vehicles
                ]
                if ext_result.pagination is not None:
                    latest_pagination = ext_result.pagination
                filtered = [
                    v
                    for v in normalized_vehicles
                    if listing_matches_filters(v, make, model)
                    and listing_matches_vehicle_condition(v, vehicle_condition)
                    and listing_matches_inventory_scope(v, inventory_scope)
                ]
                if route and route.platform_id == "dealer_on" and _needs_vdp_enrichment(filtered):
                    enriched_prefix = await asyncio.gather(
                        *[_enrich_vehicle_from_vdp(v) for v in filtered[:12]]
                    )
                    filtered = list(enriched_prefix) + filtered[12:]
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
                    chunks.append(
                        sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "current_url": current_url,
                                "status": "parsing",
                                **page_progress_payload,
                            },
                        )
                    )
                if (
                    route
                    and route.platform_id == "dealer_dot_com"
                    and make.strip()
                    and not model.strip()
                    and not normalized_vehicles
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
                            "Retrying Dealer.com make search without query filter for %s: %s -> %s",
                            d.name,
                            current_url,
                            retry_url,
                        )
                    else:
                        # Current URL has no removable query filter (e.g. path-based /new-buick/…).
                        # Fall back to the canonical SRP with ?make=X so the POST body injection kicks in.
                        try:
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
                                    "DDC path-based make page returned zero; falling back to canonical SRP for %s: %s",
                                    d.name,
                                    canonical,
                                )
                        except Exception:
                            pass
                if (
                    route
                    and route.platform_id == "dealer_inspire"
                    and not model.strip()
                    and vehicle_condition == "new"
                    and _looks_like_model_index_batch(vdicts, current_url)
                ):
                    for extra_url in dealer_inspire_fallback_urls:
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
                        chunks.append(
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
                if (
                    route
                    and route.platform_id in {"team_velocity", "nissan_infiniti_inventory"}
                    and not model.strip()
                    and current_url
                    and urlsplit(current_url).path.rstrip("/").lower()
                    == f"/inventory/{vehicle_condition}"
                ):
                    for extra_url in team_velocity_fallback_urls:
                        if extra_url not in queued_urls:
                            queued_urls.add(extra_url)
                            pending_urls.append(extra_url)
                    next_url = None
                if next_url and next_url not in queued_urls:
                    queued_urls.add(next_url)
                    pending_urls.append(next_url)
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
            chunks.append(sse_pack("dealership", done_payload))
            if recorder is not None:
                recorder.note_dealer_done(listings_found=total_vehicles)
                recorder.event(
                    event_type="dealer_done",
                    phase="scrape",
                    level="info",
                    message=f"Finished dealership scrape for {d.name}.",
                    dealership_name=d.name,
                    dealership_website=website,
                    payload=done_payload,
                )
        return chunks

    async def process_one_with_timeout(index: int, d: DealershipFound) -> list[str]:
        try:
            return await asyncio.wait_for(
                process_one(index, d),
                timeout=dealer_timeout,
            )
        except asyncio.TimeoutError:
            website = d.website or ""
            logger.warning(f"{cid_log}Dealership worker timed out for %s", website)
            if recorder is not None:
                recorder.note_dealer_failed()
                recorder.event(
                    event_type="dealer_timeout",
                    phase="worker",
                    level="warning",
                    message="Timed out while processing this dealership. Skipping to keep search moving.",
                    dealership_name=d.name,
                    dealership_website=website,
                    payload={"index": index},
                )
            return [
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
            ]

    tasks = [
        asyncio.create_task(process_one_with_timeout(i, d))
        for i, d in enumerate(dealers, start=1)
    ]
    for t in asyncio.as_completed(tasks):
        try:
            parts = await t
            for part in parts:
                yield part
        except Exception as e:
            logger.exception(f"{cid_log}Worker failed")
            if recorder is not None:
                recorder.event(
                    event_type="search_error",
                    phase="worker",
                    level="error",
                    message=str(e),
                    payload={"error": str(e)},
                )
            yield sse_pack("search_error", {"message": str(e), "phase": "worker"})

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
