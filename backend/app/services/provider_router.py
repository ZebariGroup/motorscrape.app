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


def _normalize_inventory_candidate_url(url: str) -> str:
    if ".htm&" in url and "?" not in url:
        url = url.replace(".htm&", ".htm?", 1)
    
    # Ensure OneAudi Falcon /inventory/new URLs have a trailing slash, 
    # otherwise some of their CDN edge nodes return 404 instead of 301
    parts = urlsplit(url)
    path_lower = parts.path.lower()
    if path_lower.endswith("/inventory/new") or path_lower.endswith("/inventory/used"):
        url = urlunsplit((parts.scheme, parts.netloc, parts.path + "/", parts.query, parts.fragment))
        
    return url


def _drop_query_keys(url: str, keys: set[str]) -> str:
    parts = urlsplit(url)
    params = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in keys
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _slugify_model_path(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower())
    return slug.strip("-")


def _build_family_inventory_path(base_url: str, make: str, model: str) -> str:
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if path.endswith("/inventory/new") or path.endswith("/inventory/used"):
        model_slug = _slugify_model_path(model)
        make_slug = _slugify_model_path(make)
        if model_slug and make_slug:
            path = f"{path}/{make_slug}/{model_slug}"
            return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
    return base_url


def _looks_like_exact_bmw_inventory_path(url: str, model: str) -> bool:
    path = urlsplit(url).path.lower()
    model_norm = _norm(model)
    if not model_norm:
        return False
    return (
        path.endswith(f"/{model_norm}.htm")
        or path.endswith(f"/bmw-{model_norm}.htm")
        or f"/new-inventory/{model_norm}.htm" in path
        or f"/inventory/new/bmw-{model_norm}.htm" in path
    )


def _canonical_dealer_on_inventory_url(url: str, condition: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("express."):
        base = host.removeprefix("express.")
        if base and not base.startswith("express."):
            netloc = parts.netloc.replace(host, f"www.{base}", 1)
        else:
            netloc = parts.netloc
    else:
        netloc = parts.netloc
    if condition == "new":
        path = "/searchnew.aspx"
    elif condition == "used":
        path = "/searchused.aspx"
    else:
        path = "/searchall.aspx"
    return urlunsplit((parts.scheme, netloc, path, "", ""))


def _looks_like_dealer_on_srp(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith("/searchnew.aspx") or path.endswith("/searchused.aspx")


def _host_contains_token(url: str, token_norm: str) -> bool:
    if not token_norm:
        return False
    host = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host.removeprefix("www.")
    return token_norm in _norm(host)


def _canonical_dealer_dot_com_inventory_url(url: str, condition: str) -> str:
    parts = urlsplit(url)
    if condition == "new":
        path = "/new-inventory/index.htm"
    elif condition == "used":
        path = "/used-inventory/index.htm"
    else:
        path = "/inventory/index.htm"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _looks_like_dealer_dot_com_srp(url: str, condition: str) -> bool:
    path = urlsplit(url).path.lower().rstrip("/")
    if condition == "new":
        return path.endswith("/new-inventory/index.htm")
    if condition == "used":
        return path.endswith("/used-inventory/index.htm")
    return path.endswith("/inventory/index.htm")


def _url_path_contains_token(url: str, token_norm: str) -> bool:
    if not token_norm:
        return False
    path = urlsplit(url).path
    return token_norm in _norm(path)


def _looks_like_specific_dealer_dot_com_landing(url: str) -> bool:
    path = urlsplit(url).path.lower().rstrip("/")
    if not path.endswith(".htm") or path.endswith("/index.htm"):
        return False
    return (
        path.startswith("/new-inventory/")
        or path.startswith("/used-inventory/")
        or path.startswith("/inventory/")
    )


def _dealer_on_condition_matches(url: str, condition: str) -> bool:
    path = urlsplit(url).path.lower()
    if condition == "new":
        return path.endswith("/searchnew.aspx")
    if condition == "used":
        return path.endswith("/searchused.aspx")
    return _looks_like_dealer_on_srp(url)


def _dealer_on_path_score(url: str, condition: str) -> int:
    parts = urlsplit(url)
    path = parts.path.lower()
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if condition == "new":
        if path.endswith("/searchnew.aspx") and not query:
            return 120
        if path.endswith("/searchnew.aspx") and query.get("make") and "model" not in query and "modelandtrim" not in query:
            return 90
        if any(key in query for key in ("model", "modelandtrim", "bodytype", "year")):
            return -80
    if condition == "used":
        if path.endswith("/searchused.aspx") and not query:
            return 120
        if path.endswith("/searchused.aspx") and query.get("make") and "model" not in query and "modelandtrim" not in query:
            return 90
        if any(key in query for key in ("model", "modelandtrim", "bodytype", "year")):
            return -80
    return 0


def _dealer_inspire_path_score(url: str, condition: str) -> int:
    path = urlsplit(url).path.lower().rstrip("/")
    if not path:
        return 0
    if condition == "new":
        if path.endswith("/new-vehicles"):
            return 90
        if "/new-vehicles/" in path:
            return -40
    if condition == "used":
        if path.endswith("/used-vehicles"):
            return 90
        if "/used-vehicles/" in path:
            return -40
    return 0


def _family_inventory_path_score(url: str, condition: str) -> int:
    path = urlsplit(url).path.lower().rstrip("/")
    if condition == "new":
        if path.endswith("/inventory/new"):
            return 90
        if "/inventory/new/" in path:
            return -40
        if "/inventory/new-" in path:
            return -40
    if condition == "used":
        if path.endswith("/inventory/used"):
            return 90
        if "/inventory/used/" in path:
            return -40
        if "/inventory/used-" in path:
            return -40
    return 0


def _team_velocity_inventory_path_score(url: str, condition: str) -> int:
    path = urlsplit(url).path.lower().rstrip("/")
    if condition == "new":
        if path.endswith("/inventory/new"):
            return 90
        if "/inventory/new/" in path:
            return -40
    if condition == "used":
        if path.endswith("/inventory/used"):
            return 90
        if "/inventory/used/" in path:
            return -40
    return 0


def _hyundai_inventory_path_score(url: str, condition: str) -> int:
    parts = urlsplit(url)
    path = parts.path.lower().rstrip("/")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if condition == "new":
        if path == "/cars/new":
            return 100
        if path == "/cars" and query.get("condition", "").lower() == "new" and "make" not in query:
            return 90
        if query.get("condition", "").lower() == "new" and query.get("make"):
            return -40
    if condition == "used":
        if path == "/cars/used":
            return 100
        if path == "/cars" and query.get("condition", "").lower() == "used" and "make" not in query:
            return 90
        if query.get("condition", "").lower() == "used" and query.get("make"):
            return -40
    return 0


def _hint_score(hint: str, href_lower: str, condition: str) -> int:
    if not hint or hint not in href_lower:
        return 0
    hint_lower = hint.lower()
    if condition == "new" and ("used" in hint_lower or "pre-owned" in hint_lower):
        return -20
    if condition == "used" and ("searchnew" in hint_lower or "new-inventory" in hint_lower):
        return -20
    return 50


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
    condition = (vehicle_condition or "all").strip().lower()

    if route and route.platform_id == "dealer_dot_com":
        # express.* retail URLs often 403 on bare GETs and 404 when blindly swapped to www.*.
        # Force them to a known good www.* path based on condition before routing.
        def _fix_ddc_express(u: str | None) -> str | None:
            if not u:
                return u
            try:
                parts = urlsplit(u)
                host = parts.netloc.lower().split("@")[-1].split(":")[0]
                if host.startswith("express."):
                    base_host = host.removeprefix("express.")
                    if base_host and not base_host.startswith("express."):
                        www_host = f"www.{base_host}"
                        if condition == "new":
                            path = "/new-inventory/index.htm"
                        elif condition == "used":
                            path = "/used-inventory/index.htm"
                        else:
                            path = "/inventory/index.htm"
                        return urlunsplit((parts.scheme, www_host, path, "", ""))
            except Exception:
                pass
            return u

        base_url = _fix_ddc_express(base_url) or base_url
        fallback_url = _fix_ddc_express(fallback_url) or fallback_url
        if route.inventory_url_hint:
            route = ProviderRoute(
                platform_id=route.platform_id,
                confidence=route.confidence,
                extraction_mode=route.extraction_mode,
                requires_render=route.requires_render,
                detection_source=route.detection_source,
                cache_status=route.cache_status,
                inventory_path_hints=route.inventory_path_hints,
                inventory_url_hint=_fix_ddc_express(route.inventory_url_hint),
            )

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        if route and route.inventory_url_hint:
            return route.inventory_url_hint
        return fallback_url

    best_url = (route.inventory_url_hint if route else None) or fallback_url
    best_score = -1
    best_url_make_signal = False
    hints = tuple(h.lower() for h in (route.inventory_path_hints if route else ()))
    make_norm = _norm(make)
    model_norm = _norm(model)
    current_url = _normalize_inventory_candidate_url(base_url)

    if route and route.platform_id == "dealer_on" and _dealer_on_condition_matches(current_url, condition):
        best_url = current_url
        best_score = 90
    if route and route.platform_id == "dealer_dot_com" and _looks_like_dealer_dot_com_srp(current_url, condition):
        best_url = _drop_query_keys(current_url, {"gvBodyStyle", "make", "model", "search"})
        # With make-only searches, leave room for make-specific SRP links
        # such as /new-gmc/vehicles-*.htm to outrank the generic index URL.
        best_score = 25 if (make_norm and not model_norm) else 120

    for a in soup.find_all("a", href=True):
        href = _normalize_inventory_candidate_url(str(a["href"]))
        href_lower = href.lower()
        text = a.get_text(strip=True).lower()
        combined_norm = _norm(f"{text} {href_lower}")
        score = 0

        for hint in hints:
            score += _hint_score(hint, href_lower, condition)

        if make_norm and make_norm in combined_norm:
            score += 30
        if (
            route
            and route.platform_id == "dealer_dot_com"
            and not model_norm
            and _looks_like_specific_dealer_dot_com_landing(href)
            and "vehicles" not in href_lower
        ):
            # Make-only searches should avoid model landing pages like
            # /new-inventory/gmc-yukon.htm and prefer generic make SRPs.
            score -= 120
        if (
            route
            and route.platform_id == "dealer_dot_com"
            and not model_norm
            and make_norm
            and f"/new-{_slugify_model_path(make)}/" in href_lower
        ):
            score += 70
        if (
            route
            and route.platform_id == "dealer_dot_com"
            and not model_norm
            and make_norm
            and _url_path_contains_token(href, make_norm)
            and "inventory" not in href_lower
            and "vehicles" not in href_lower
            and f"/new-{_slugify_model_path(make)}/" not in href_lower
            and f"/used-{_slugify_model_path(make)}/" not in href_lower
            and "make=" not in href_lower
        ):
            score -= 90
        if (
            route
            and route.platform_id == "dealer_dot_com"
            and not model_norm
            and make_norm
            and _url_path_contains_token(href, make_norm)
        ):
            # Prefer make-family SRPs like /new-gmc/vehicles-*.htm over generic index pages.
            score += 90
        score += _model_href_match_score(href_lower, text, model_norm)

        if "for-sale" in href_lower:
            score += 35
        if "inventory" in href_lower or "inventory" in text:
            score += 20
        if route and route.platform_id == "dealer_on" and not model_norm:
            score += _dealer_on_path_score(href, condition)
            if _dealer_on_condition_matches(href, condition):
                score += 80
            if "?q=" in href_lower:
                score -= 60
            if any(token in href_lower for token in ("model=", "modelandtrim=", "year=")):
                score -= 100
            if make_norm in {
                _norm("Chevrolet"),
                _norm("GMC"),
                _norm("Buick"),
                _norm("Cadillac"),
                _norm("Ford"),
                _norm("Lincoln"),
            } and any(token in href_lower for token in ("bodytype=", "bodystyle=")):
                score -= 85
        if route and route.platform_id == "dealer_inspire" and not model_norm:
            score += _dealer_inspire_path_score(href, condition)
        if route and route.platform_id == "honda_acura_inventory" and not model_norm:
            score += _family_inventory_path_score(href, condition)
        if route and route.platform_id in {
            "ford_family_inventory",
            "gm_family_inventory",
            "toyota_lexus_oem_inventory",
        } and not model_norm:
            score += _family_inventory_path_score(href, condition)
        if route and route.platform_id == "team_velocity" and not model_norm:
            score += _team_velocity_inventory_path_score(href, condition)
        if route and route.platform_id == "hyundai_inventory_search" and not model_norm:
            score += _hyundai_inventory_path_score(href, condition)
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

        # Heavily penalize external links that aren't subdomains
        try:
            parsed_href = urlsplit(href)
            if parsed_href.netloc:
                base_netloc = urlsplit(base_url).netloc
                if not parsed_href.netloc.endswith(base_netloc.replace("www.", "")):
                    score -= 50
        except Exception:
            pass

        if score > best_score and score > 0:
            best_score = score
            best_url = urljoin(base_url, href)
            best_url_make_signal = bool(make_norm and make_norm in combined_norm)

    if route and not model_norm and route.platform_id in {"nissan_infiniti_inventory", "hyundai_inventory_search"}:
        generic_base = _normalize_inventory_candidate_url(
            (route.inventory_url_hint if route else None) or fallback_url
        )
        if generic_base:
            best_url = generic_base

    if route and not model_norm and route.platform_id == "dealer_dot_com":
        hint = best_url if best_score > 0 else (route.inventory_url_hint if route else None) or fallback_url
        if make_norm:
            make_slug = _slugify_model_path(make)
            make_hint_url: str | None = None
            make_hint_score = -1
            for a in soup.find_all("a", href=True):
                href = _normalize_inventory_candidate_url(str(a["href"]))
                href_lower = href.lower()
                text = a.get_text(strip=True).lower()
                if not _url_path_contains_token(href, make_norm):
                    continue
                if (
                    "inventory" not in href_lower
                    and "vehicles" not in href_lower
                    and f"/new-{make_slug}/" not in href_lower
                    and f"/used-{make_slug}/" not in href_lower
                    and "make=" not in href_lower
                ):
                    continue
                if condition == "new" and ("used" in href_lower or "pre-owned" in text or "used" in text):
                    continue
                if condition == "used" and "used" not in href_lower and "pre-owned" not in href_lower and "used" not in text:
                    continue
                score = 30
                if any(token in href_lower for token in ("research", "compare", "reviews", "schedule")):
                    score -= 60
                if _looks_like_specific_dealer_dot_com_landing(href) and "vehicles" not in href_lower:
                    score -= 80
                if condition == "new" and f"/new-{make_slug}/" in href_lower:
                    score += 70
                if condition == "used" and f"/used-{make_slug}/" in href_lower:
                    score += 70
                if "inventory" in href_lower:
                    score += 20
                if "vehicles" in href_lower:
                    score += 10
                if condition == "new" and ("new" in href_lower or "new" in text):
                    score += 15
                if condition == "used" and ("used" in href_lower or "pre-owned" in href_lower):
                    score += 15
                if any(token in href_lower for token in ("model=", "gvbodystyle=", "bodystyle=")):
                    score -= 45
                if score > make_hint_score:
                    make_hint_score = score
                    make_hint_url = urljoin(base_url, href)
            if make_hint_url:
                hint = make_hint_url
        # If the hint is an express.* retail URL, it will likely 403 or 404 when swapped to www.
        # Force it to a known good www.* path based on condition.
        try:
            parts = urlsplit(hint)
            host = parts.netloc.lower().split("@")[-1].split(":")[0]
            if host.startswith("express."):
                base = host.removeprefix("express.")
                if base and not base.startswith("express."):
                    www_host = f"www.{base}"
                    cond = (vehicle_condition or "all").strip().lower()
                    path = "/new-inventory/index.htm" if cond == "new" else "/used-inventory/index.htm" if cond == "used" else "/inventory/index.htm"
                    hint = urlunsplit((parts.scheme, www_host, path, "", ""))
        except Exception:
            pass

        generic_base = _normalize_inventory_candidate_url(hint)
        if generic_base:
            path = urlsplit(generic_base).path.lower().rstrip("/")
            is_canonical_srp = any(
                token in path
                for token in (
                    "/new-inventory/index.htm",
                    "/used-inventory/index.htm",
                    "/inventory/index.htm",
                    "/searchnew.aspx",
                    "/searchused.aspx",
                )
            )
            make_specific_path = bool(make_norm) and _url_path_contains_token(generic_base, make_norm)
            specific_model_landing = _looks_like_specific_dealer_dot_com_landing(generic_base) and "vehicles" not in path
            if path in {"", "/"} or specific_model_landing or (not is_canonical_srp and not make_specific_path):
                generic_base = _canonical_dealer_dot_com_inventory_url(generic_base, condition)
                generic_base = _drop_query_keys(generic_base, {"gvBodyStyle", "make", "model", "search"})
                if (
                    make_norm
                    and not best_url_make_signal
                    and not (make_norm == "bmw" and _host_contains_token(generic_base, make_norm))
                ):
                    generic_base = _with_query_params(generic_base, {"make": make})
            else:
                generic_base = _drop_query_keys(generic_base, {"gvBodyStyle", "model", "search"})
            best_url = generic_base

    if route and not model_norm and route.platform_id == "dealer_on":
        generic_base = _normalize_inventory_candidate_url(
            (route.inventory_url_hint if route else None) or fallback_url
        )
        if generic_base:
            if not _looks_like_dealer_on_srp(generic_base):
                generic_base = _canonical_dealer_on_inventory_url(generic_base, condition)
            generic_base = _drop_query_keys(generic_base, {"Make", "make", "Model", "model", "ModelAndTrim", "modelandtrim", "search", "q"})
            best_url = _with_query_params(generic_base, {"Make": make}) if make_norm else generic_base

    if model_norm and route:
        generic_base = _normalize_inventory_candidate_url(
            (route.inventory_url_hint if route else None) or fallback_url
        )
        if route.platform_id == "dealer_dot_com" and generic_base:
            base = _normalize_inventory_candidate_url(best_url if best_score > 0 else generic_base)
            if make_norm == "bmw" and _looks_like_exact_bmw_inventory_path(base, model):
                best_url = base
            else:
                base = _drop_query_keys(base, {"gvBodyStyle", "make", "search"})
                best_url = _with_query_params(base, {"model": model})
        elif route.platform_id == "honda_acura_inventory":
            base = _normalize_inventory_candidate_url(best_url if best_score > 0 else generic_base)
            best_url = _build_family_inventory_path(base, make, model)
        elif route.platform_id in {"ford_family_inventory", "gm_family_inventory"}:
            base = _normalize_inventory_candidate_url(best_url if best_score > 0 else generic_base)
            best_url = _build_family_inventory_path(base, make, model)
        elif route.platform_id == "toyota_lexus_oem_inventory":
            base = _normalize_inventory_candidate_url(best_url if best_score > 0 else generic_base)
            best_url = _build_family_inventory_path(base, make, model)
            best_url = _drop_query_keys(best_url, {"gvBodyStyle", "make", "search"})
            best_url = _with_query_params(best_url, {"model": model})
        elif route.platform_id == "dealer_on" and best_score < 100 and generic_base:
            updates = {"Make": make, "Model": model}
            if _looks_like_dealer_on_srp(generic_base):
                updates["ModelAndTrim"] = model
            best_url = _with_query_params(generic_base, updates)

    return best_url
