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
from app.services.inventory_filters import make_filter_normalized_variants, normalize_model_text
from app.services.platform_store import PlatformCacheEntry, platform_store

logger = logging.getLogger(__name__)

_KNOWN_BRAND_TOKENS: frozenset[str] = frozenset(
    {
        # Cars / trucks / motorcycles
        "acura",
        "alfaromeo",
        "audi",
        "bmw",
        "bmwmotorrad",
        "buick",
        "cadillac",
        "canam",
        "chevrolet",
        "chevy",
        "chrysler",
        "dodge",
        "ducati",
        "fiat",
        "ford",
        "gmc",
        "harleydavidson",
        "honda",
        "hyundai",
        "indian",
        "indianmotorcycle",
        "infiniti",
        "jeep",
        "kawasaki",
        "kia",
        "ktm",
        "lexus",
        "lincoln",
        "mazda",
        "mini",
        "mitsubishi",
        "nissan",
        "polaris",
        "ram",
        "royalenfield",
        "subaru",
        "suzuki",
        "toyota",
        "triumph",
        "volkswagen",
        "volvo",
        "vw",
        "yamaha",
        # Boats — SkipperBud's brand list (authoritative US marine retail reference)
        "alumacraft",
        "atx",
        "atxsurfboats",
        "aviara",
        "axopar",
        "azimut",
        "azure",
        "axis",
        "baja",
        "barletta",
        "bayliner",
        "beneteau",
        "bennington",
        "bentley",
        "blackfin",
        "bostonwhaler",
        "bryant",
        "burger",
        "carolinaclassic",
        "carver",
        "carveryachts",
        "catalina",
        "centurion",
        "chaparral",
        "chriscraft",
        "cobalt",
        "correctcraft",
        "crest",
        "crestliner",
        "crownline",
        "cruisersyachts",
        "cutwater",
        "doral",
        "fairline",
        "formula",
        "fourwinns",
        "galeon",
        "glastron",
        "godfrey",
        "harris",
        "hatteras",
        "heyday",
        "hurricane",
        "jcmfg",
        "keywestboats",
        "larson",
        "lund",
        "malibu",
        "manitou",
        "maritimo",
        "mastercraft",
        "maxum",
        "mbsports",
        "mirrocraft",
        "mistyharbor",
        "monterey",
        "moomba",
        "navan",
        "nautique",
        "neptune",
        "palmbeach",
        "playbuoy",
        "premier",
        "prestige",
        "princecraft",
        "pursuit",
        "regal",
        "rinker",
        "riviera",
        "robalo",
        "sailfish",
        "sanpan",
        "saxdor",
        "scarab",
        "scout",
        "seadoo",
        "seafox",
        "searay",
        "shamrock",
        "silverton",
        "southbay",
        "starcraft",
        "stingray",
        "sunchaser",
        "suncatcher",
        "supra",
        "sylvan",
        "tahoe",
        "tiarayachts",
        "tige",
        "tracker",
        "trophy",
        "viking",
        "willardboatworks",
        "worldcat",
        "yamahaboats",
        "rangerboats",
        "manitou",
        "fairline",
        "maritimo",
    }
)


def _effective_requires_render(platform_id: str, requires_render: bool) -> bool:
    # DealerOn SRPs are commonly server-rendered and should stay on the cheap direct path first.
    if platform_id == "dealer_on":
        return False
    return requires_render


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


def _mentioned_brand_tokens(text: str) -> set[str]:
    text_norm = _norm(text)
    if not text_norm:
        return set()
    return {token for token in _KNOWN_BRAND_TOKENS if token in text_norm}


def _looks_like_inventory_detail_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    if "detail" in path:
        return True
    return bool(re.search(r"/(?:19|20)\d{2}[-/]", path))


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
    if parts.fragment:
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
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
    if host.startswith("buy."):
        base = host.removeprefix("buy.")
        if base and not base.startswith("buy."):
            netloc = parts.netloc.replace(host, f"www.{base}", 1)
        else:
            netloc = parts.netloc
    elif host.startswith("express."):
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
        # DealerOn inventory pages typically use dedicated new/used SRPs only.
        # Fall back to the new-inventory SRP for mixed searches to avoid 404s
        # from non-existent `/searchall.aspx` endpoints.
        path = "/searchnew.aspx"
    return urlunsplit((parts.scheme, netloc, path, "", ""))


def _canonical_dealer_inspire_inventory_url(url: str, condition: str) -> str:
    parts = urlsplit(url)
    if condition == "used":
        path = "/used-vehicles/"
    else:
        path = "/new-vehicles/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _canonical_dealer_inspire_filtered_inventory_url(
    base_url: str,
    *,
    condition: str,
    make: str,
    model: str,
) -> str:
    cond = (condition or "all").strip().lower()
    if cond == "all":
        base = _normalize_inventory_candidate_url(base_url)
        parts = urlsplit(base)
        path = parts.path or "/new-vehicles/"
        if not path.endswith("/"):
            path += "/"
        base = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    else:
        base = _canonical_dealer_inspire_inventory_url(base_url, cond)
    updates: dict[str, str] = {}
    if cond == "new":
        updates["_dFR[type][0]"] = "New"
    elif cond == "used":
        updates["_dFR[type][0]"] = "Used"
    if make.strip():
        updates["_dFR[make][0]"] = make.strip()
    if model.strip():
        updates["_dFR[model][0]"] = model.strip()
    return _with_query_params(base, updates)


def _canonical_family_inventory_url(url: str, condition: str) -> str:
    parts = urlsplit(url)
    if condition == "used":
        path = "/inventory/used"
    else:
        path = "/inventory/new"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _looks_like_dealer_on_srp(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith("/searchnew.aspx") or path.endswith("/searchused.aspx")


def _dealer_dot_com_host_brand_tokens(url: str) -> set[str]:
    host = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host.removeprefix("www.")
    host_norm = _norm(host)
    return {token for token in _KNOWN_BRAND_TOKENS if token in host_norm}


def _dealer_dot_com_host_is_multi_brand(url: str, make_norm: str) -> bool:
    if not make_norm:
        return False
    host_tokens = _dealer_dot_com_host_brand_tokens(url)
    if make_norm not in host_tokens:
        return False
    return any(token != make_norm for token in host_tokens)


def _dealer_dot_com_host_is_single_brand(url: str, make_norm: str) -> bool:
    if not make_norm:
        return False
    host_tokens = _dealer_dot_com_host_brand_tokens(url)
    return bool(host_tokens) and host_tokens == {make_norm}


def _canonical_dealer_dot_com_inventory_url(url: str, condition: str) -> str:
    parts = urlsplit(url)
    if condition == "new":
        path = "/new-inventory/index.htm"
    elif condition == "used":
        path = "/used-inventory/index.htm"
    else:
        path = "/all-inventory/index.htm"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _looks_like_dealer_dot_com_srp(url: str, condition: str) -> bool:
    path = urlsplit(url).path.lower().rstrip("/")
    if condition == "new":
        return path.endswith("/new-inventory/index.htm")
    if condition == "used":
        return path.endswith("/used-inventory/index.htm")
    return path.endswith("/all-inventory/index.htm")


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


def _looks_like_make_specific_dealer_dot_com_inventory_path(url: str, make: str, condition: str) -> bool:
    make_slug = _slugify_model_path(make)
    if not make_slug:
        return False
    path = urlsplit(url).path.lower().rstrip("/")
    if f"/new-{make_slug}/" in path or f"/used-{make_slug}/" in path:
        return True
    if "/inventory/" in path and make_slug in path:
        return True
    if condition == "new" and f"make={make_slug}" in url.lower():
        return True
    if condition == "used" and f"make={make_slug}" in url.lower():
        return True
    return False


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


def _looks_like_team_velocity_inventory_stack(html: str, url: str = "") -> bool:
    target = f"{html} {url}".lower()
    return any(
        marker in target
        for marker in (
            "teamvelocitymarketing.com",
            "teamvelocity",
            "team velocity",
            "inventory_listing",
            "unlockctadiscountdata",
            "si-vehicle-box",
            "/viewdetails/",
        )
    )


def _team_velocity_inventory_path_score(url: str, condition: str) -> int:
    parts = urlsplit(url)
    path = parts.path.lower().rstrip("/")
    query = {k.lower(): v.lower() for k, v in parse_qsl(parts.query, keep_blank_values=True)}
    score = 0
    if path == "/--inventory":
        query_condition = query.get("condition", "").strip().lower()
        if condition == "new":
            if query_condition == "new":
                score += 125
            elif query_condition in {"used", "pre-owned", "preowned"}:
                score -= 70
            elif not query_condition:
                score += 20
        elif condition == "used":
            if query_condition in {"used", "pre-owned", "preowned"}:
                score += 125
            elif query_condition == "new":
                score -= 70
            elif not query_condition:
                score += 20
        else:
            if not query:
                score += 130
            elif query_condition:
                score -= 80

        scoped_query_keys = {"make", "model", "category", "subcategory", "customsearch", "year", "pg", "page"}
        scoped_key_count = len(scoped_query_keys.intersection(query))
        if scoped_key_count:
            score -= 70 + (10 * scoped_key_count)

    if path == "/inventory/v1":
        if condition == "all":
            score += 60
        else:
            score += 15
    if condition == "new":
        if path.endswith("/inventory/new"):
            score += 90
        if "/inventory/new/" in path:
            score -= 40
    if condition == "used":
        if path.endswith("/inventory/used"):
            score += 90
        if "/inventory/used/" in path:
            score -= 40
    return score


def _dealer_spike_inventory_path_score(url: str, condition: str) -> int:
    parts = urlsplit(url)
    path = parts.path.lower().rstrip("/")
    query = parts.query.lower()
    score = 0

    if "manufacturer-models" in path or "model-list" in path:
        return -120

    if path.endswith("/inventory/all-inventory-in-stock") or "page=xallinventory" in query:
        score += 130 if condition == "all" else 35
    if path.endswith("/inventory/new-inventory-in-stock") or "page=xnewinventory" in query:
        score += 130 if condition == "new" else (-40 if condition == "used" else 80)
    if path.endswith("/inventory/used-inventory") or path.endswith("/inventory/used-inventory-in-stock") or "page=xpreownedinventory" in query:
        score += 130 if condition == "used" else (-80 if condition == "new" else -20)
    if "in-stock" in path:
        score += 25

    return score


def _dealer_spike_prefer_legacy_asp_inventory_url(
    url: str,
    base_url: str,
    *,
    vehicle_condition: str,
    make: str,
) -> str:
    """
    Dealer Spike React routes under /inventory/v1/... are often empty shells in raw HTML (no
    embedded /imglib/.../NVehInv.js). Legacy default.asp inventory pages include the cached
    vehicle script and are what our scraper can enrich.
    """
    try:
        parts = urlsplit(url)
    except Exception:
        return url
    if "/inventory/v1/" not in parts.path.lower():
        return url
    try:
        base_parts = urlsplit(base_url)
    except Exception:
        return url
    host = base_parts.netloc or parts.netloc
    if not host:
        return url
    scheme = base_parts.scheme or parts.scheme or "https"
    cond = (vehicle_condition or "all").strip().lower()
    if cond == "new":
        page = "xnewinventory"
    elif cond == "used":
        page = "xpreownedinventory"
    else:
        page = "xallinventory"
    params: list[tuple[str, str]] = [("page", page)]
    mk = (make or "").strip()
    if mk:
        slug = _slugify_model_path(mk)
        if slug:
            params.append(("make", slug))
    query = urlencode(params)
    return urlunsplit((scheme, host, "/default.asp", query, ""))


def _d2c_media_inventory_path_score(url: str, condition: str) -> int:
    path = urlsplit(url).path.lower().rstrip("/")
    if condition == "new":
        if path == "/new/inventory/search.html":
            return 110
        if path.startswith("/new/inventory/") and path.endswith(".html"):
            return -40
        if path == "/new/new.html":
            return 25
    if condition == "used":
        if path == "/used/search.html":
            return 110
        if path.startswith("/used/") and path.endswith(".html") and path != "/used/search.html":
            return -40
    return 0


def _canonical_team_velocity_inventory_url(base_url: str, condition: str) -> str:
    parts = urlsplit(base_url)
    cond = (condition or "all").strip().lower()
    if cond == "new":
        query = urlencode({"condition": "new"})
    elif cond == "used":
        query = urlencode({"condition": "pre-owned"})
    else:
        query = ""
    return urlunsplit((parts.scheme, parts.netloc, "/--inventory", query, ""))


def _canonical_team_velocity_filtered_inventory_url(
    base_url: str,
    *,
    condition: str,
    make: str,
    model: str,
) -> str:
    base = _canonical_team_velocity_inventory_url(base_url, condition)
    updates: dict[str, str] = {}
    if make.strip():
        updates["make"] = make.strip()
    if model.strip():
        updates["model"] = model.strip()
    return _with_query_params(base, updates)


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


def _find_model_scoped_inventory_link(
    soup: BeautifulSoup,
    base_url: str,
    *,
    model_norm: str,
    path_prefixes: tuple[str, ...],
) -> str | None:
    prefixes = tuple(prefix.rstrip("/").lower() for prefix in path_prefixes if prefix)
    best_url: str | None = None
    best_score = 0
    for a in soup.find_all("a", href=True):
        href = _normalize_inventory_candidate_url(urljoin(base_url, str(a["href"])))
        path = urlsplit(href).path.lower().rstrip("/")
        if prefixes and not any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes):
            continue
        if _looks_like_inventory_detail_url(href):
            continue
        text = a.get_text(strip=True).lower()
        score = _model_href_match_score(href.lower(), text, model_norm)
        if score <= 0:
            continue
        if any(token in href.lower() for token in ("service", "parts", "finance", "contact", "specials")):
            continue
        if score > best_score:
            best_score = score
            best_url = href
    return best_url


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
        requires_render=_effective_requires_render(profile.platform_id, profile.requires_render),
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
        requires_render=_effective_requires_render(entry.platform_id, entry.requires_render),
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
        requires_render=_effective_requires_render(route.platform_id, requires_render),
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
                            path = "/all-inventory/index.htm"
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
            return _normalize_inventory_candidate_url(route.inventory_url_hint)
        return _normalize_inventory_candidate_url(fallback_url)

    best_url = _normalize_inventory_candidate_url((route.inventory_url_hint if route else None) or fallback_url)
    best_score = -1
    hints = tuple(h.lower() for h in (route.inventory_path_hints if route else ()))
    make_norm = normalize_model_text(make)
    make_norms = make_filter_normalized_variants(make)
    model = (model or "").strip()
    multi_model_filter = "," in model
    if multi_model_filter:
        model = ""
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
        href_path = urlsplit(href).path.lower().rstrip("/")
        text = a.get_text(strip=True).lower()
        combined_norm = _norm(f"{text} {href_lower}")
        score = 0

        for hint in hints:
            score += _hint_score(hint, href_lower, condition)

        mentioned_brand_tokens = _mentioned_brand_tokens(f"{text} {href_lower}")
        if make_norms and any(variant in combined_norm for variant in make_norms):
            score += 30
        if make_norms and mentioned_brand_tokens.intersection(make_norms):
            score += 40
        elif make_norms and mentioned_brand_tokens:
            score -= 140
        if make_norm and not model_norm and _looks_like_inventory_detail_url(href):
            score -= 120
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
            if _dealer_dot_com_host_is_single_brand(base_url, make_norm):
                # On single-brand hosts like suburbanford..., /new-ford/... links are
                # usually marketing/model landings; canonical inventory/index pages are safer.
                score -= 110
        if (
            route
            and route.platform_id in {"gm_family_inventory", "ford_family_inventory", "toyota_lexus_oem_inventory"}
            and not model_norm
            and _looks_like_specific_dealer_dot_com_landing(href)
            and "vehicles" not in href_lower
        ):
            score -= 120
        if route and route.platform_id in {"gm_family_inventory", "ford_family_inventory", "toyota_lexus_oem_inventory"}:
            if condition == "new" and href_path.endswith("/new-inventory/index.htm"):
                score += 120
            elif condition == "used" and href_path.endswith("/used-inventory/index.htm"):
                score += 120
            elif condition == "all" and href_path.endswith("/all-inventory/index.htm"):
                score += 120
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
        if route and route.platform_id == "dealer_spike":
            if not model_norm:
                score += _dealer_spike_inventory_path_score(href, condition)
            # React /inventory/v1/... SRPs usually omit NVehInv.js; legacy default.asp pages embed it.
            if "/inventory/v1/" in href_lower:
                score -= 130
        if route and route.platform_id == "d2c_media" and not model_norm:
            score += _d2c_media_inventory_path_score(href, condition)
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
                    if cond not in {"new", "used"}:
                        path = "/all-inventory/index.htm"
                    hint = urlunsplit((parts.scheme, www_host, path, "", ""))
        except Exception:
            pass

        generic_base = _normalize_inventory_candidate_url(hint)
        if generic_base:
            path = urlsplit(generic_base).path.lower().rstrip("/")
            make_query_needed = bool(make_norm) and (
                _dealer_dot_com_host_is_multi_brand(generic_base, make_norm) or multi_model_filter
            )
            host_is_single_brand = bool(make_norm) and _dealer_dot_com_host_is_single_brand(
                generic_base,
                make_norm,
            )
            is_canonical_srp = any(
                token in path
                for token in (
                    "/new-inventory/index.htm",
                    "/used-inventory/index.htm",
                    "/all-inventory/index.htm",
                    "/searchnew.aspx",
                    "/searchused.aspx",
                )
            )
            make_specific_path = bool(make_norm) and _looks_like_make_specific_dealer_dot_com_inventory_path(
                generic_base,
                make,
                condition,
            )
            specific_model_landing = _looks_like_specific_dealer_dot_com_landing(generic_base) and "vehicles" not in path
            if path in {"", "/"} or specific_model_landing or (not is_canonical_srp and not make_specific_path):
                generic_base = _canonical_dealer_dot_com_inventory_url(generic_base, condition)
                generic_base = _drop_query_keys(generic_base, {"gvBodyStyle", "make", "model", "search"})
                if make_query_needed:
                    generic_base = _with_query_params(generic_base, {"make": make})
            elif host_is_single_brand and make_specific_path:
                generic_base = _canonical_dealer_dot_com_inventory_url(generic_base, condition)
                generic_base = _drop_query_keys(generic_base, {"gvBodyStyle", "make", "model", "search"})
            elif is_canonical_srp:
                generic_base = _drop_query_keys(generic_base, {"gvBodyStyle", "model", "search"})
                if make_query_needed:
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

    if route and not model_norm and route.platform_id == "dealer_inspire":
        generic_base = _normalize_inventory_candidate_url(
            (route.inventory_url_hint if route else None) or fallback_url
        )
        if generic_base:
            if _looks_like_team_velocity_inventory_stack(html, generic_base):
                generic_base = _canonical_family_inventory_url(generic_base, condition)
            else:
                generic_base = _canonical_dealer_inspire_inventory_url(generic_base, condition)
            best_url = generic_base

    if route and not model_norm and not make_norm and route.platform_id == "team_velocity":
        generic_base = _normalize_inventory_candidate_url(
            best_url if best_score > 0 else (route.inventory_url_hint if route else None) or fallback_url
        )
        if generic_base:
            path = urlsplit(generic_base).path.lower().rstrip("/")
            if path in {"", "/", "/inventory/v1"}:
                best_url = _canonical_team_velocity_inventory_url(generic_base, condition)

    if not route and make_norm and not model_norm:
        fallback_norm = _normalize_inventory_candidate_url(fallback_url)
        best_norm = _normalize_inventory_candidate_url(best_url)
        if best_norm and best_norm.rstrip("/") != fallback_norm.rstrip("/"):
            best_combined_norm = _norm(best_norm)
            if make_norm not in best_combined_norm:
                best_url = fallback_norm

    if model_norm and route:
        generic_base = _normalize_inventory_candidate_url(
            (route.inventory_url_hint if route else None) or fallback_url
        )
        if route.platform_id == "dealer_dot_com" and generic_base:
            base = _normalize_inventory_candidate_url(best_url if best_score > 0 else generic_base)
            base_path = urlsplit(base).path.lower().rstrip("/")
            is_canonical_srp = any(
                token in base_path
                for token in (
                    "/new-inventory/index.htm",
                    "/used-inventory/index.htm",
                    "/all-inventory/index.htm",
                )
            )
            if not is_canonical_srp:
                base = _canonical_dealer_dot_com_inventory_url(base, condition)
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
        elif route.platform_id == "dealer_inspire" and generic_base:
            # Prefer query-filtered SRP URLs over deep model-landing paths. A number of
            # Dealer Inspire stores bot-challenge /new-vehicles/<model>/ links while the
            # filtered SRP endpoint remains reachable and paginates reliably.
            best_url = _canonical_dealer_inspire_filtered_inventory_url(
                generic_base,
                condition=condition,
                make=make,
                model=model,
            )
        elif route.platform_id == "team_velocity" and generic_base:
            condition_path = "/inventory/used" if condition == "used" else "/inventory/new"
            scoped_link = _find_model_scoped_inventory_link(
                soup,
                base_url,
                model_norm=model_norm,
                path_prefixes=(condition_path, "/--inventory"),
            )
            if scoped_link:
                best_url = scoped_link
            else:
                best_url = _canonical_team_velocity_filtered_inventory_url(
                    generic_base,
                    condition=condition,
                    make=make,
                    model=model,
                )

    if route and route.platform_id == "dealer_spike":
        best_url = _dealer_spike_prefer_legacy_asp_inventory_url(
            best_url,
            base_url,
            vehicle_condition=vehicle_condition,
            make=make,
        )

    return best_url
