"""Provider-aware routing for platform detection, caching, and inventory URL hints."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.services.dealer_platforms import (
    PlatformProfile,
    detect_platform_profile,
    inventory_hints_for_platform,
)
from app.services.platform_store import PlatformCacheEntry, platform_store

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProviderRoute:
    platform_id: str
    confidence: float
    extraction_mode: str
    requires_render: bool
    detection_source: str
    cache_status: str
    inventory_path_hints: tuple[str, ...]
    inventory_url_hint: str | None = None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _with_query_params(url: str, updates: dict[str, str]) -> str:
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update({k: v for k, v in updates.items() if v})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _looks_like_dealer_on_srp(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith("/searchnew.aspx") or path.endswith("/searchused.aspx")


def _model_href_match_score(href: str, text: str, model_norm: str) -> int:
    if not model_norm:
        return 0
    href_parts = urlsplit(href)
    href_lower = href.lower()
    text_lower = text.lower()
    href_segments = [seg for seg in href_parts.path.lower().split("/") if seg]
    text_segments = [seg for seg in re.split(r"\W+", text_lower) if seg]
    norm_href_segments = [_norm(seg) for seg in href_segments]
    norm_text_segments = [_norm(seg) for seg in text_segments]

    score = 0
    if model_norm in _norm(f"{text_lower} {href_lower}"):
        score += 120

    if any(seg == model_norm for seg in norm_href_segments):
        score += 180
    elif any(seg.startswith(model_norm) and seg != model_norm for seg in norm_href_segments):
        score += 40

    if any(seg == model_norm for seg in norm_text_segments):
        score += 80
    elif any(seg.startswith(model_norm) and seg != model_norm for seg in norm_text_segments):
        score += 20

    return score


def _route_from_profile(
    profile: PlatformProfile,
    *,
    cache_status: str,
    inventory_url_hint: str | None = None,
) -> ProviderRoute:
    return ProviderRoute(
        platform_id=profile.platform_id,
        confidence=profile.confidence,
        extraction_mode=profile.extraction_mode,
        requires_render=profile.requires_render,
        detection_source=profile.detection_source,
        cache_status=cache_status,
        inventory_path_hints=profile.inventory_path_hints,
        inventory_url_hint=inventory_url_hint,
    )


def _route_from_cache(entry: PlatformCacheEntry, *, cache_status: str) -> ProviderRoute:
    return ProviderRoute(
        platform_id=entry.platform_id,
        confidence=entry.confidence,
        extraction_mode=entry.extraction_mode,
        requires_render=entry.requires_render,
        detection_source=entry.detection_source,
        cache_status=cache_status,
        inventory_path_hints=inventory_hints_for_platform(entry.platform_id),
        inventory_url_hint=entry.inventory_url_hint,
    )


def detect_or_lookup_provider(
    *,
    domain: str,
    website: str,
    homepage_html: str,
) -> ProviderRoute | None:
    cached = platform_store.get(domain)
    if cached and cached.is_usable:
        return _route_from_cache(cached, cache_status="hit")

    profile = detect_platform_profile(homepage_html, page_url=website)
    if not profile:
        if cached:
            return _route_from_cache(cached, cache_status="stale")
        return None

    platform_store.upsert(
        domain=domain,
        platform_id=profile.platform_id,
        confidence=profile.confidence,
        extraction_mode=profile.extraction_mode,
        requires_render=profile.requires_render,
        detection_source=profile.detection_source,
        inventory_url_hint=cached.inventory_url_hint if cached else None,
        metadata={"website": website},
    )
    return _route_from_profile(
        profile,
        cache_status="refresh" if cached else "detected",
        inventory_url_hint=cached.inventory_url_hint if cached else None,
    )


def remember_provider_success(
    *,
    domain: str,
    route: ProviderRoute,
    inventory_url_hint: str | None,
    requires_render: bool,
) -> None:
    platform_store.upsert(
        domain=domain,
        platform_id=route.platform_id,
        confidence=route.confidence,
        extraction_mode=route.extraction_mode,
        requires_render=requires_render,
        detection_source=route.detection_source,
        inventory_url_hint=inventory_url_hint,
        metadata={"cache_status": route.cache_status},
    )


def record_provider_failure(domain: str) -> None:
    platform_store.record_failure(domain)


def resolve_inventory_url_for_provider(
    html: str,
    base_url: str,
    route: ProviderRoute | None,
    *,
    fallback_url: str,
    make: str = "",
    model: str = "",
    vehicle_condition: str = "all",
) -> str:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        if route and route.inventory_url_hint:
            return route.inventory_url_hint
        return fallback_url

    best_url = route.inventory_url_hint or fallback_url
    best_score = -1
    hints = tuple(h.lower() for h in (route.inventory_path_hints if route else ()))
    make_norm = _norm(make)
    model_norm = _norm(model)
    condition = (vehicle_condition or "all").strip().lower()

    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        href_lower = href.lower()
        text = a.get_text(strip=True).lower()
        combined_norm = _norm(f"{text} {href_lower}")
        score = 0

        for hint in hints:
            if hint and hint in href_lower:
                score += 50

        if make_norm and make_norm in combined_norm:
            score += 30
        score += _model_href_match_score(href_lower, text, model_norm)

        if "for-sale" in href_lower:
            score += 35
        if "inventory" in href_lower or "inventory" in text:
            score += 20
        if condition == "new":
            if "new-inventory" in href_lower:
                score += 40
            if "searchnew" in href_lower:
                score += 35
            if "inventory" in href_lower and "new" in href_lower and model_norm:
                score += 30
            if "inventory" in href_lower and "new" in href_lower:
                score += 30
            if "new" in href_lower or "new" in text:
                score += 10
            if "used-inventory" in href_lower or "used-vehicles" in href_lower:
                score -= 10
            if "used" in href_lower or "pre-owned" in text or "used" in text:
                score -= 15
        elif condition == "used":
            if "used-inventory" in href_lower or "used-vehicles" in href_lower:
                score += 40
            if "searchused" in href_lower:
                score += 35
            if "pre-owned" in href_lower or "pre-owned" in text:
                score += 25
            if "used" in href_lower or "used" in text:
                score += 20
            if "new-inventory" in href_lower:
                score -= 15
            if "searchnew" in href_lower or ("new" in href_lower or "new" in text):
                score -= 10
        else:
            if "inventory" in href_lower and "new" not in href_lower and "used" not in href_lower:
                score += 15
            if "new-inventory" in href_lower or "used-inventory" in href_lower:
                score += 5
        if any(x in href_lower for x in ["service", "parts", "finance", "contact", "about", "specials", "privacy"]):
            score -= 20
        if any(x in href_lower for x in ["research", "compare", "reviews", "schedule"]):
            score -= 25

        if score > best_score and score > 0:
            best_score = score
            best_url = urljoin(base_url, href)

    if model_norm and route:
        generic_base = route.inventory_url_hint or fallback_url
        if route.platform_id == "dealer_dot_com" and generic_base:
            best_url = _with_query_params(generic_base, {"model": model})
        elif route.platform_id == "dealer_on" and best_score < 100 and generic_base:
            updates = {"Make": make, "Model": model}
            if _looks_like_dealer_on_srp(generic_base):
                updates["ModelAndTrim"] = model
            best_url = _with_query_params(generic_base, updates)

    return best_url
