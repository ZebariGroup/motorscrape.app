from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit

from app.config import settings
from app.schemas import DealershipFound, PaginationInfo
from app.services.inventory_filters import model_filter_variants
from app.services.platform_store import normalize_dealer_domain
from app.services.provider_router import ProviderRoute

_domain_fetch_limiters: dict[str, asyncio.Semaphore] = {}


def domain_fetch_limiter(host_key: str) -> asyncio.Semaphore:
    if host_key not in _domain_fetch_limiters:
        _domain_fetch_limiters[host_key] = asyncio.Semaphore(max(1, settings.domain_fetch_concurrency))
    return _domain_fetch_limiters[host_key]


def effective_search_concurrency() -> int:
    configured = max(1, settings.search_concurrency)
    if not (settings.zenrows_api_key or settings.scrapingbee_api_key):
        return configured

    provider_slots: list[int] = []
    if settings.zenrows_api_key:
        provider_slots.append(max(1, settings.zenrows_max_concurrency))
    if settings.scrapingbee_api_key:
        provider_slots.append(max(1, settings.scrapingbee_max_concurrency))

    managed_slots = max(1, settings.managed_scraper_max_concurrency)
    if provider_slots:
        managed_slots = min(managed_slots, sum(provider_slots))

    workers_per_slot = max(1, settings.search_workers_per_managed_slot)
    adaptive_cap = managed_slots * workers_per_slot
    return max(1, min(configured, adaptive_cap))


def dedupe_dealers_by_domain(dealers: list[DealershipFound]) -> list[DealershipFound]:
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


def html_mentions_model(html: str, model: str) -> bool:
    if not model.strip():
        return True
    hay = html.lower()
    models = [m.strip() for m in model.split(",") if m.strip()]
    for m in models:
        if any(v in hay for v in model_filter_variants(m)):
            return True
    return False


def html_mentions_make(html: str, make: str) -> bool:
    mk = make.strip().lower()
    if not mk:
        return True
    return mk in html.lower()


def prefer_https_website_url(url: str) -> str:
    u = (url or "").strip()
    if u.lower().startswith("http://"):
        return f"https://{u[7:]}"
    return u


def guess_franchise_inventory_srp_url(website: str, vehicle_condition: str) -> str | None:
    """
    When homepage HTML is a bot shell (no usable <a> inventory links), many OEM-style
    dealers still serve SRPs at /inventory/new or /inventory/used on https://www.
    """
    try:
        parts = urlsplit((website or "").strip())
        if not parts.scheme or not parts.netloc:
            return None
        host = parts.netloc.lower().split("@")[-1].split(":")[0]
        if not host:
            return None
        www_host = host if host.startswith("www.") else f"www.{host}"
        cond = (vehicle_condition or "all").strip().lower()
        if cond == "used":
            path = "/inventory/used"
        else:
            path = "/inventory/new"
        return urlunsplit(("https", www_host, path, "", ""))
    except Exception:
        return None


def effective_max_pages_for_route(requested_pages: int, route: ProviderRoute | None) -> int:
    if route and route.max_pages is not None:
        return min(requested_pages, route.max_pages)
    return requested_pages


def pagination_progress_payload(
    pagination: PaginationInfo | None,
    *,
    pages_scraped: int,
) -> dict[str, int]:
    if not pagination:
        return {"pages_scraped": pages_scraped}
    payload = {"pages_scraped": pages_scraped}
    if pagination.total_pages is not None:
        payload["total_pages"] = pagination.total_pages
    if pagination.total_vehicles is not None:
        payload["total_vehicles"] = pagination.total_vehicles
    return payload
