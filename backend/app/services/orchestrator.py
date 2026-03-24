"""Coordinates Places → scrape → LLM parse with async iteration for SSE."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from collections import defaultdict
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.schemas import DealershipFound
from app.services.inventory_discovery import discover_sitemap_inventory_urls
from app.services.inventory_filters import (
    infer_vehicle_condition_from_page,
    listing_matches_filters,
    listing_matches_inventory_scope,
    listing_matches_vehicle_condition,
    model_filter_variants,
)
from app.services.dealer_platforms import detect_platform_profile
from app.services.parser import extract_vehicles_from_html, try_extract_vehicles_without_llm
from app.services.places import find_car_dealerships
from app.services.platform_store import normalize_dealer_domain
from app.services.provider_router import (
    ProviderRoute,
    detect_or_lookup_provider,
    record_provider_failure,
    remember_provider_success,
    resolve_inventory_url_for_provider,
)
from app.services.providers import extract_with_provider
from app.services.scraper import PageKind, fetch_page_html

logger = logging.getLogger(__name__)


def _dedupe_dealers_by_domain(dealers: list[DealershipFound]) -> list[DealershipFound]:
    seen: set[str] = set()
    out: list[DealershipFound] = []
    for d in dealers:
        w = d.website or ""
        dom = normalize_dealer_domain(w)
        if not dom or dom in seen:
            continue
        seen.add(dom)
        out.append(d)
    return out


def _html_mentions_model(html: str, model: str) -> bool:
    if not model.strip():
        return True
    hay = html.lower()
    return any(v in hay for v in model_filter_variants(model))


def _html_mentions_make(html: str, make: str) -> bool:
    mk = make.strip().lower()
    if not mk:
        return True
    return mk in html.lower()


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
            href = a['href'].lower()
            text = a.get_text(strip=True).lower()
            score = 0

            if "inventory" in href or "inventory" in text:
                score += 20
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
                if "inventory" in href and "new" not in href and "used" not in href:
                    score += 15
                if "new-inventory" in href or "used-inventory" in href:
                    score += 5

            # Penalize non-inventory links
            if any(x in href for x in ["service", "parts", "finance", "contact", "about", "specials", "privacy"]):
                score -= 20

            if score > best_score and score > 0:
                best_score = score
                best_url = urljoin(base_url, a['href'])

        return best_url
    except Exception as e:
        logger.warning("Failed to parse inventory URL: %s", e)
        return base_url


def _sse_pack(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


async def stream_search(
    location: str,
    make: str,
    model: str,
    *,
    vehicle_condition: str = "all",
    radius_miles: int = 50,
    inventory_scope: str = "all",
    max_dealerships: int | None = None,
    max_pages_per_dealer: int | None = None,
) -> AsyncIterator[str]:
    """
    Yield SSE-formatted strings: status, dealership, vehicles, error, done.
    """
    yield _sse_pack("status", {"message": "Finding local dealerships…", "phase": "places"})
    requested_dealerships = max(1, min(max_dealerships or settings.max_dealerships, 30))
    requested_pages = max(1, min(max_pages_per_dealer or settings.max_pages_per_dealer, 5))

    try:
        dealers = await find_car_dealerships(
            location,
            make=make,
            model=model,
            limit=min(requested_dealerships * 3, 30),
            radius_miles=radius_miles,
        )
    except Exception as e:
        logger.exception("Places search failed")
        yield _sse_pack("search_error", {"message": str(e), "phase": "places"})
        yield _sse_pack("done", {"ok": False})
        return

    raw_dealer_count = len(dealers)
    dealers = _dedupe_dealers_by_domain(dealers)
    deduped_dealer_count = len(dealers)
    dealers = dealers[: requested_dealerships]
    if not dealers:
        yield _sse_pack("status", {"message": "No dealerships with websites found.", "phase": "places"})
        yield _sse_pack("done", {"ok": True, "dealerships": 0})
        return

    yield _sse_pack(
        "status",
        {
            "message": (
                f"Found {len(dealers)} dealerships. Scraping inventory… "
                f"(requested {requested_dealerships}, radius {radius_miles} mi, "
                f"condition {vehicle_condition})"
            ),
            "phase": "scrape",
        },
    )

    sem = asyncio.Semaphore(max(1, settings.search_concurrency))
    fetch_timeout = settings.scrape_timeout * 3 + 5.0
    parse_timeout = settings.openai_timeout + 5.0
    fetch_metrics: dict[str, int] = defaultdict(int)
    metrics_lock = asyncio.Lock()
    inv_url_cache: dict[str, str] = {}

    async def process_one(index: int, d: DealershipFound) -> list[str]:
        chunks: list[str] = []
        website = d.website or ""
        domain = normalize_dealer_domain(website)
        fetch_methods_used: list[str] = []

        async def _fetch(
            url: str,
            page_kind: PageKind,
            *,
            prefer_render: bool = False,
        ) -> tuple[str, str]:
            html, method = await fetch_page_html(
                url,
                page_kind=page_kind,
                prefer_render=prefer_render,
                metrics=None,
            )
            fetch_methods_used.append(method)
            async with metrics_lock:
                key = f"fetch_{method}"
                fetch_metrics[key] += 1
            return html, method

        chunks.append(
            _sse_pack(
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
            # 1. Fetch homepage to find inventory link
            try:
                html, method = await asyncio.wait_for(
                    _fetch(website, "homepage"),
                    timeout=fetch_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Scrape timed out for %s", website)
                chunks.append(
                    _sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": d.name,
                            "website": website,
                            "status": "error",
                            "error": (
                                f"Timed out while fetching pages after ~{int(fetch_timeout)}s."
                            ),
                        },
                    )
                )
                return chunks
            except Exception as e:
                logger.warning("Scrape failed for %s: %s", website, e)
                if domain:
                    record_provider_failure(domain)
                chunks.append(
                    _sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": d.name,
                            "website": website,
                            "status": "error",
                            "error": str(e),
                        },
                    )
                )
                return chunks

            route = detect_or_lookup_provider(domain=domain, website=website, homepage_html=html)
            if route:
                async with metrics_lock:
                    fetch_metrics[f"platform_{route.platform_id}"] += 1
                    fetch_metrics[f"platform_source_{route.cache_status}"] += 1
            inv_url = resolve_inventory_url_for_provider(
                html,
                website,
                route,
                fallback_url=_find_inventory_url(
                    html,
                    website,
                    vehicle_condition=vehicle_condition,
                ),
                make=make,
                model=model,
                vehicle_condition=vehicle_condition,
            )
            if inv_url == website and domain in inv_url_cache:
                cached = inv_url_cache[domain]
                if cached and cached.rstrip("/") != website.rstrip("/"):
                    inv_url = cached
            if inv_url == website:
                try:
                    sm_timeout = httpx.Timeout(min(settings.scrape_timeout, 30.0))
                    candidates = await discover_sitemap_inventory_urls(website, sm_timeout)
                    for cand in candidates:
                        if cand.rstrip("/") != website.rstrip("/"):
                            inv_url = cand
                            logger.info("Using sitemap inventory candidate for %s: %s", domain, inv_url)
                            break
                except Exception as e:
                    logger.debug("Sitemap discovery skipped for %s: %s", website, e)

            current_html = html
            current_method = method

            # If inventory is on a different URL, fetch it before first parse.
            if inv_url and inv_url != website:
                chunks.append(
                    _sse_pack(
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
                    current_html, current_method = await asyncio.wait_for(
                        _fetch(inv_url, "inventory", prefer_render=bool(route and route.requires_render)),
                        timeout=fetch_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Initial inventory scrape timed out for %s", inv_url)
                    if domain:
                        record_provider_failure(domain)
                    chunks.append(
                        _sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "current_url": inv_url,
                                "status": "error",
                                "error": (
                                    f"Timed out while fetching inventory page after ~{int(fetch_timeout)}s."
                                ),
                            },
                        )
                    )
                    return chunks
                except Exception as e:
                    logger.warning("Initial inventory scrape failed for %s: %s", inv_url, e)
                    if domain:
                        record_provider_failure(domain)
                    chunks.append(
                        _sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": website,
                                "current_url": inv_url,
                                "status": "error",
                                "error": str(e),
                            },
                        )
                    )
                    return chunks
            elif route and route.requires_render:
                try:
                    current_html, current_method = await asyncio.wait_for(
                        _fetch(inv_url or website, "inventory", prefer_render=True),
                        timeout=fetch_timeout,
                    )
                except Exception as e:
                    logger.debug("Preferred rendered refetch skipped for %s: %s", inv_url or website, e)

            inventory_profile = detect_platform_profile(current_html, page_url=inv_url or website)
            if inventory_profile and (
                route is None
                or inventory_profile.confidence >= route.confidence
                or route.platform_id in {"team_velocity", "fusionzone", "purecars", "jazel"}
            ):
                route = ProviderRoute(
                    platform_id=inventory_profile.platform_id,
                    confidence=inventory_profile.confidence,
                    extraction_mode=inventory_profile.extraction_mode,
                    requires_render=inventory_profile.requires_render,
                    detection_source=inventory_profile.detection_source,
                    cache_status="detected",
                    inventory_path_hints=inventory_profile.inventory_path_hints,
                    inventory_url_hint=inv_url or website,
                )
            
            # 2. Pagination loop
            current_url = inv_url
            pages_scraped = 0
            max_pages = (
                max(requested_pages, 4)
                if route and route.platform_id in {"nissan_infiniti_inventory", "honda_acura_inventory"}
                else requested_pages
            )
            total_vehicles = 0
            skip_info: str | None = None

            while current_url and pages_scraped < max_pages:
                if pages_scraped > 0:
                    chunks.append(
                        _sse_pack(
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
                        current_html, current_method = await asyncio.wait_for(
                            _fetch(
                                current_url,
                                "inventory",
                                prefer_render=bool(route and route.requires_render),
                            ),
                            timeout=fetch_timeout,
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
                else:
                    ext_result = try_extract_vehicles_without_llm(
                        page_url=current_url,
                        html=current_html,
                        make_filter=make,
                        model_filter=model,
                    )
                    extraction_mode = "structured" if ext_result is not None else None

                if ext_result is None:
                    if make.strip() and not _html_mentions_make(current_html, make):
                        logger.info(
                            "Skipping extraction for %s: no make mention (%r) in HTML",
                            current_url,
                            make.strip(),
                        )
                        skip_info = (
                            f'No "{make.strip()}" mention found on this page; skipped extraction.'
                        )
                        break

                    if model.strip() and not _html_mentions_model(current_html, model):
                        logger.info(
                            "Skipping extraction for %s: no model mention (%r) in HTML",
                            current_url,
                            model.strip(),
                        )
                        skip_info = (
                            f'No "{model.strip()}" found on this page; skipped extraction.'
                        )
                        break

                chunks.append(
                    _sse_pack(
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
                        ext_result = await asyncio.wait_for(
                            extract_vehicles_from_html(
                                page_url=current_url,
                                html=current_html,
                                make_filter=make,
                                model_filter=model,
                            ),
                            timeout=parse_timeout,
                        )
                    except asyncio.TimeoutError:
                        msg = f"Timed out during AI extraction after ~{int(parse_timeout)}s."
                        logger.warning("Parse timed out for %s", current_url)
                        if pages_scraped == 0:
                            chunks.append(
                                _sse_pack(
                                    "dealership",
                                    {
                                        "index": index,
                                        "total": len(dealers),
                                        "name": d.name,
                                        "website": website,
                                        "current_url": current_url,
                                        "status": "error",
                                        "error": msg,
                                    },
                                )
                            )
                        break
                    except Exception as e:
                        logger.warning("Parse failed for %s: %s", current_url, e)
                        if pages_scraped == 0:
                            chunks.append(
                                _sse_pack(
                                    "dealership",
                                    {
                                        "index": index,
                                        "total": len(dealers),
                                        "name": d.name,
                                        "website": website,
                                        "current_url": current_url,
                                        "status": "error",
                                        "error": str(e),
                                    },
                                )
                            )
                        break

                page_vehicle_condition = infer_vehicle_condition_from_page(current_url, current_html)
                normalized_vehicles = [
                    (
                        v.model_copy(update={"vehicle_condition": page_vehicle_condition})
                        if v.vehicle_condition is None and page_vehicle_condition is not None
                        else v
                    )
                    for v in ext_result.vehicles
                ]
                filtered = [
                    v
                    for v in normalized_vehicles
                    if listing_matches_filters(v, make, model)
                    and listing_matches_vehicle_condition(v, vehicle_condition)
                    and listing_matches_inventory_scope(v, inventory_scope)
                ]
                vdicts = [v.model_dump(exclude_none=True) for v in filtered]
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
                    chunks.append(
                        _sse_pack(
                            "vehicles",
                            {
                                "dealership": d.name,
                                "website": website,
                                "current_url": current_url,
                                "count": len(vdicts),
                                "listings": vdicts,
                            },
                        )
                    )

                current_url = ext_result.next_page_url
                pages_scraped += 1

                if not vdicts:
                    break  # Stop pagination if no vehicles found

            done_payload: dict[str, Any] = {
                "index": index,
                "total": len(dealers),
                "name": d.name,
                "website": website,
                "status": "done",
                "listings_found": total_vehicles,
                "fetch_methods": fetch_methods_used,
                "platform_id": route.platform_id if 'route' in locals() and route else None,
                "platform_source": route.cache_status if 'route' in locals() and route else None,
                "strategy_used": route.extraction_mode if 'route' in locals() and route else None,
            }
            if skip_info:
                done_payload["info"] = skip_info
            chunks.append(_sse_pack("dealership", done_payload))
        return chunks

    async def process_one_with_timeout(index: int, d: DealershipFound) -> list[str]:
        try:
            return await asyncio.wait_for(
                process_one(index, d),
                timeout=settings.dealership_timeout,
            )
        except asyncio.TimeoutError:
            website = d.website or ""
            logger.warning("Dealership worker timed out for %s", website)
            return [
                _sse_pack(
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
            logger.exception("Worker failed")
            yield _sse_pack("search_error", {"message": str(e), "phase": "worker"})

    yield _sse_pack(
        "done",
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
            "fetch_metrics": dict(fetch_metrics),
        },
    )
