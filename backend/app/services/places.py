"""Google Places API (New): Text Search + Place Details for dealership websites."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.config import settings
from app.schemas import DealershipFound
from app.services.inventory_filters import normalize_model_text, text_mentions_make

# When the UI category is still "car" but the user searches an OEM that only sells through
# motorcycle/powersports dealers, Google Places' car_dealer type filter returns nothing useful.
# Use the same Text Search profile as motorcycle (no strict car_dealer type).
_POWERSPORTS_MAKE_PLACES_NORMS: frozenset[str] = frozenset(
    {
        "canam",
        "skidoo",
        "seadoo",
        "lynx",
        "arcticcat",
        "cfmoto",
        "polaris",
        "hisun",
        "massimo",
        "kymco",
        "harleydavidson",
        "indianmotorcycle",
        "ktm",
        "ducati",
        "triumph",
        "royalenfield",
    }
)


def _generic_category_fallback_cap(category: str) -> int:
    return {
        "motorcycle": 3,
        "boat": 4,
        "other": 4,
    }.get(category, 4)


def _effective_places_search_category(vehicle_category: str, make: str) -> str:
    category = _normalize_vehicle_category(vehicle_category)
    if category != "car":
        return category
    make_norm = normalize_model_text((make or "").strip())
    if make_norm and make_norm in _POWERSPORTS_MAKE_PLACES_NORMS:
        return "motorcycle"
    return "car"

logger = logging.getLogger(__name__)

SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
# GET https://places.googleapis.com/v1/places/{placeId} — {name} is "places/ChIJ…"
PLACES_BASE = "https://places.googleapis.com/v1"
METERS_PER_MILE = 1609.34
MAX_LOCATION_BIAS_RADIUS_METERS = 50_000
MAX_LOCATION_BIAS_RADIUS_MILES = int(MAX_LOCATION_BIAS_RADIUS_METERS // METERS_PER_MILE)

# Text Search (New) field mask — websiteUri uses Enterprise SKU; omit if you need to trim billing.
SEARCH_FIELD_MASK = (
    "places.id,places.name,places.displayName,places.formattedAddress,places.websiteUri"
)
DETAILS_FIELD_MASK = "websiteUri"
LOCATION_FIELD_MASK = "places.location"
SUPPORTED_VEHICLE_CATEGORIES = {"car", "motorcycle", "boat", "other"}
_CATEGORY_CONTEXT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "car": ("auto", "automotive", "motors", "car", "cars", "truck", "trucks"),
    "motorcycle": (
        "motorcycle",
        "motorcycles",
        "powersports",
        "power sports",
        "motorsports",
        "moto",
        "bike",
        "bikes",
        "atv",
        "utv",
        "side-by-side",
        "side x side",
        "can-am",
        "sea-doo",
    ),
    "boat": (
        "boat",
        "boats",
        "boating",
        "marine",
        "marina",
        "yacht",
        "yachts",
        "pontoon",
        "wake",
        "fishing",
        "outboard",
    ),
    "other": ("powersports", "motorsports", "marine", "boat", "motorcycle"),
}
_CATEGORY_NEGATIVE_CONTEXT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "boat": (
        "marine supply",
        "marine gear",
        "boat supply",
        "hardware",
        "marine service",
        "boat service",
        "boat repair",
        "marine repair",
        "parts",
        "accessories",
        "west marine",
    ),
}
_CATEGORY_POSITIVE_DEALER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "boat": (
        "dealer",
        "dealership",
        "inventory",
        "boats for sale",
        "boat sales",
        "yacht sales",
        "sales",
        "showroom",
        "marina",
        "boating center",
    ),
}
_TRUSTED_NATIONAL_RETAILER_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "boat": (
        "marinemax.com",
        "skipperbuds.com",
        "onewatermarine.com",
        "onewaterinventory.com",
        "bassproboatingcenters.com",
        "basspro.com",
        "cabelas.com",
    ),
}
_TRUSTED_NATIONAL_RETAILER_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "boat": (
        "marinemax",
        "skipperbud",
        "onewater",
        "boating center",
        "bass pro shops boating center",
        "cabela's boating center",
        "cabelas boating center",
    ),
}
_CAR_BRAND_CONFLICT_TOKENS: frozenset[str] = frozenset(
    {
        "acura",
        "alfa romeo",
        "audi",
        "bmw",
        "buick",
        "cadillac",
        "chevrolet",
        "chevy",
        "chrysler",
        "dodge",
        "fiat",
        "ford",
        "gmc",
        "honda",
        "hyundai",
        "infiniti",
        "jeep",
        "kia",
        "lexus",
        "lincoln",
        "mazda",
        "mercedes",
        "mini",
        "mitsubishi",
        "nissan",
        "ram",
        "subaru",
        "toyota",
        "volkswagen",
        "volvo",
    }
)
_CATEGORY_SEARCH_CONFIG: dict[str, dict[str, Any]] = {
    "car": {
        "included_type": "car_dealer",
        "strict_type_filtering": True,
        "dealer_terms": ("car dealership", "dealer"),
        "fallback_terms": ("showroom", "inventory"),
    },
    "motorcycle": {
        "included_type": None,
        "strict_type_filtering": False,
        "dealer_terms": ("motorcycle dealer", "powersports dealer"),
        "fallback_terms": ("showroom", "inventory"),
    },
    "boat": {
        "included_type": None,
        "strict_type_filtering": False,
        "dealer_terms": ("boat dealer", "marine dealer"),
        "fallback_terms": ("showroom", "inventory"),
    },
    "other": {
        "included_type": None,
        "strict_type_filtering": False,
        "dealer_terms": ("motor vehicle dealer", "powersports dealer"),
        "fallback_terms": ("showroom", "inventory"),
    },
}


def _api_error_message(payload: Any) -> str:
    if isinstance(payload, dict) and "error" in payload:
        err = payload["error"]
        if isinstance(err, dict):
            return str(err.get("message") or err.get("status") or payload)
    return str(payload)[:500]


def _display_name(place: dict[str, Any]) -> str:
    dn = place.get("displayName")
    if isinstance(dn, dict) and dn.get("text"):
        return str(dn["text"])
    return "Unknown"


def _name_matches_make(dealer_name: str, make: str) -> bool:
    """Loose brand match on dealership name to avoid unrelated franchises."""
    if not make.strip():
        return True
    return text_mentions_make(dealer_name, make)


def _dealer_matches_category_context(
    dealer_name: str,
    website: str,
    *,
    vehicle_category: str,
) -> bool:
    category = _normalize_vehicle_category(vehicle_category)
    if category == "car":
        return True
    hay = " ".join(filter(None, [dealer_name, website])).strip().lower()
    if not hay:
        return False
    return any(keyword in hay for keyword in _CATEGORY_CONTEXT_KEYWORDS.get(category, ()))


def _looks_like_false_positive_category_match(
    dealer_name: str,
    website: str,
    *,
    vehicle_category: str,
) -> bool:
    category = _normalize_vehicle_category(vehicle_category)
    hay = " ".join(filter(None, [dealer_name, website])).strip().lower()
    if not hay:
        return False
    negative_keywords = _CATEGORY_NEGATIVE_CONTEXT_KEYWORDS.get(category, ())
    if not negative_keywords:
        return False
    if not any(keyword in hay for keyword in negative_keywords):
        return False
    positive_keywords = _CATEGORY_POSITIVE_DEALER_KEYWORDS.get(category, ())
    return not any(keyword in hay for keyword in positive_keywords)


def _is_trusted_national_retailer_match(
    dealer_name: str,
    website: str,
    *,
    vehicle_category: str,
) -> bool:
    category = _normalize_vehicle_category(vehicle_category)
    hay = " ".join(filter(None, [dealer_name, website])).strip().lower()
    if not hay:
        return False
    if any(token in hay for token in _TRUSTED_NATIONAL_RETAILER_DOMAIN_HINTS.get(category, ())):
        return True
    if any(token in hay for token in _TRUSTED_NATIONAL_RETAILER_NAME_HINTS.get(category, ())):
        return True
    return False


def _looks_like_false_positive_make_match(
    dealer_name: str,
    website: str,
    *,
    make: str,
    vehicle_category: str,
) -> bool:
    if _normalize_vehicle_category(vehicle_category) != "car":
        return False
    make_norm = (make or "").strip().lower()
    hay = " ".join(filter(None, [dealer_name, website])).strip().lower()
    if not hay or not make_norm:
        return False
    if make_norm != "genesis":
        return False

    parts = urlsplit(website or "")
    host = (parts.netloc or "").lower().split("@")[-1].split(":")[0]
    path = (parts.path or "").lower()

    # Actual Genesis franchises usually present as "Genesis of <city>" or use a
    # Genesis-specific host. Businesses that merely contain the word Genesis while
    # clearly advertising another OEM should not qualify for Genesis brand searches.
    has_genesis_dealer_pattern = (
        "genesis of " in hay
        or host.startswith("genesisof")
        or ".genesisof" in host
        or "/genesis/" in path
    )
    has_conflicting_brand = any(token in hay for token in _CAR_BRAND_CONFLICT_TOKENS)
    if has_conflicting_brand:
        return True
    if "automotive group" in hay and not has_genesis_dealer_pattern:
        return True
    return False


async def _search_places_text(
    client: httpx.AsyncClient,
    key: str,
    *,
    text_query: str,
    limit: int,
    location_bias: dict[str, Any] | None = None,
    included_type: str | None = None,
    strict_type_filtering: bool = False,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "textQuery": text_query,
        "pageSize": min(limit, 20),
        "languageCode": "en",
    }
    if included_type:
        body["includedType"] = included_type
        body["strictTypeFiltering"] = strict_type_filtering
    if location_bias:
        body["locationBias"] = location_bias
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": SEARCH_FIELD_MASK,
    }
    r = await client.post(SEARCH_TEXT_URL, json=body, headers=headers)
    if r.status_code != 200:
        logger.warning("Places searchText HTTP %s for %r: %s", r.status_code, text_query, r.text[:500])
        raise RuntimeError(
            f"Google Places Text Search (New) failed: HTTP {r.status_code}. {_api_error_message(r.json() if r.content else {})}"
        )
    payload = r.json()
    places = payload.get("places") or []
    return [p for p in places if isinstance(p, dict)]


async def _resolve_location_bias(
    client: httpx.AsyncClient,
    key: str,
    *,
    location: str,
    radius_miles: int,
) -> dict[str, Any] | None:
    body: dict[str, Any] = {
        "textQuery": location,
        "pageSize": 1,
        "languageCode": "en",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": LOCATION_FIELD_MASK,
    }
    try:
        r = await client.post(SEARCH_TEXT_URL, json=body, headers=headers)
        r.raise_for_status()
    except Exception as e:
        logger.debug("Location bias lookup failed for %r: %s", location, e)
        return None

    places = (r.json() or {}).get("places") or []
    if not places or not isinstance(places[0], dict):
        return None
    point = places[0].get("location") or {}
    lat = point.get("latitude")
    lng = point.get("longitude")
    if lat is None or lng is None:
        return None

    radius_meters = int(radius_miles * METERS_PER_MILE)
    if radius_meters <= MAX_LOCATION_BIAS_RADIUS_METERS:
        return {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_meters,
            }
        }
    else:
        # Use a rectangle for radiuses larger than the 50km circle limit
        earth_radius_miles = 3958.8
        lat_delta_deg = math.degrees(radius_miles / earth_radius_miles)
        # Avoid division by zero at the poles
        cos_lat = max(0.0001, math.cos(math.radians(lat)))
        lng_delta_deg = math.degrees(radius_miles / (earth_radius_miles * cos_lat))

        # Clamp to valid lat/lng ranges
        low_lat = max(-90.0, lat - lat_delta_deg)
        high_lat = min(90.0, lat + lat_delta_deg)

        # For simplicity, clamp longitude (assuming mostly continental searches).
        # A true global solution would handle crossing the 180th meridian.
        low_lng = max(-180.0, lng - lng_delta_deg)
        high_lng = min(180.0, lng + lng_delta_deg)

        return {
            "rectangle": {
                "low": {"latitude": low_lat, "longitude": low_lng},
                "high": {"latitude": high_lat, "longitude": high_lng},
            }
        }


def _normalize_dealer_website_url(website: str) -> str:
    """
    Strip common marketing/tracking params from dealership website URLs returned by
    Google Places. Several dealer sites rate-limit or block the tracked URL while the
    clean canonical homepage works.
    """
    raw = (website or "").strip()
    if not raw:
        return ""

    # Reject non-HTTP pseudo-URLs from Places data (e.g. javascript:void(0))
    if not raw.startswith("http://") and not raw.startswith("https://"):
        return ""

    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw

    host = parts.netloc.lower().split("@")[-1].split(":")[0]

    # DealerOn / OEM "buy" subdomains often point at thin shopping shells that generate
    # broken inventory URLs (e.g. buy.dealer.com/searchall.aspx) instead of the real site.
    # Normalize those back to the dealer homepage before discovery.
    if host.startswith("buy."):
        base_host = host.removeprefix("buy.")
        if base_host:
            canonical_host = base_host if base_host.startswith("www.") else f"www.{base_host}"
            return urlunsplit((parts.scheme, canonical_host, "/", "", ""))

    # Reject well-known aggregator/marketplace profile URLs — these are not dealer websites.
    # e.g. boats.com/sites/<dealer>, cars.com/dealers/<id>, autotrader.com/dealers/...
    # Trying to scrape inventory from these fails because the aggregator blocks bots
    # and the page is a marketplace listing, not the dealer's own inventory system.
    _AGGREGATOR_HOSTS = {
        "www.boats.com",
        "boats.com",
        "www.cars.com",
        "cars.com",
        "www.autotrader.com",
        "autotrader.com",
        "www.truecar.com",
        "truecar.com",
        "www.cargurus.com",
        "cargurus.com",
        "www.carmax.com",
        "carmax.com",
        "www.rvtrader.com",
        "rvtrader.com",
        "www.cycletrader.com",
        "cycletrader.com",
        "www.boattrader.com",
        "boattrader.com",
        "www.yacht.com",
        "yacht.com",
        "www.yachtworld.com",
        "yachtworld.com",
    }
    if host in _AGGREGATOR_HOSTS:
        return ""

    tracking_prefixes = ("utm_",)
    tracking_keys = {
        "gclid",
        "gbraid",
        "wbraid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
    }
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in tracking_keys and not k.lower().startswith(tracking_prefixes)
    ]
    clean_query = urlencode(kept, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, clean_query, ""))


def _normalize_vehicle_category(vehicle_category: str) -> str:
    normalized = (vehicle_category or "car").strip().lower()
    return normalized if normalized in SUPPORTED_VEHICLE_CATEGORIES else "other"


def _build_text_queries(
    *,
    vehicle_category: str,
    location: str,
    make: str,
    model: str,
    market_region: str = "us",
) -> list[str]:
    config = _CATEGORY_SEARCH_CONFIG[_normalize_vehicle_category(vehicle_category)]
    make_q = make.strip()
    model_q = model.strip()
    dealer_terms = tuple(config["dealer_terms"])
    fallback_terms = tuple(config["fallback_terms"])
    eu = (market_region or "").strip().lower() == "eu"

    text_queries: list[str] = []
    primary_term = dealer_terms[0]
    if make_q:
        text_queries.append(f"{make_q} {primary_term} near {location}")
        if model_q:
            text_queries.append(f"{make_q} {model_q} {primary_term} near {location}")
    elif model_q:
        text_queries.append(f"{model_q} {primary_term} near {location}")
    else:
        text_queries.append(f"{primary_term} near {location}")

    if make_q:
        for dealer_term in dealer_terms:
            text_queries.append(f"{make_q} {dealer_term} near {location}")
        for fallback_term in fallback_terms:
            text_queries.append(f"{make_q} {fallback_term} near {location}")
    elif model_q:
        for dealer_term in dealer_terms[1:]:
            text_queries.append(f"{model_q} {dealer_term} near {location}")

    if eu and _normalize_vehicle_category(vehicle_category) == "car" and make_q:
        # UK + EU English dealership discovery (Places text search is English-first).
        text_queries.extend(
            [
                f"{make_q} garage near {location}",
                f"{make_q} motors near {location}",
                f"{make_q} car sales near {location}",
                f"{make_q} approved used near {location}",
            ]
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for text_query in text_queries:
        if text_query not in seen:
            deduped.append(text_query)
            seen.add(text_query)
    return deduped


def _places_query_stop_target(*, limit: int, make: str, model: str) -> int:
    """Stop once we have enough likely candidates for dedupe/filtering."""
    limit = max(1, int(limit or 1))
    if not (make.strip() or model.strip()):
        return limit
    return min(limit, max(8, int(limit * 0.6)))


async def find_dealerships(
    location: str,
    *,
    make: str = "",
    model: str = "",
    vehicle_category: str = "car",
    limit: int = 20,
    radius_miles: int = 50,
    market_region: str = "us",
) -> list[DealershipFound]:
    """
    Find car dealerships near the given location using Places API (New) Text Search,
    then fetch Place Details when websiteUri is missing.
    """
    key = settings.google_places_api_key
    if not key:
        raise ValueError(
            "Google Places API key is not set. Use env var GOOGLE_PLACES_API_KEY "
            "(or GOOGLE_MAPS_API_KEY). On Vercel, add it in Project → Settings → "
            "Environment Variables for Production and Preview; a local .env file is not deployed."
        )

    make_q = make.strip()
    model_q = model.strip()
    requested_radius = max(5, min(int(radius_miles or 25), 250))

    async with httpx.AsyncClient(timeout=30.0) as client:
        location_bias = await _resolve_location_bias(
            client,
            key,
            location=location,
            radius_miles=requested_radius,
        )
        category = _normalize_vehicle_category(vehicle_category)
        places_category = _effective_places_search_category(vehicle_category, make_q)
        config = _CATEGORY_SEARCH_CONFIG[places_category]
        text_queries = _build_text_queries(
            vehicle_category=places_category,
            location=location,
            make=make_q,
            model=model_q,
            market_region=market_region,
        )
        query_stop_target = _places_query_stop_target(limit=limit, make=make_q, model=model_q)

        places: list[dict[str, Any]] = []
        seen_place_resources: set[str] = set()
        for idx, text_query in enumerate(text_queries):
            try:
                found = await _search_places_text(
                    client,
                    key,
                    text_query=text_query,
                    limit=limit,
                    location_bias=location_bias,
                    included_type=config.get("included_type"),
                    strict_type_filtering=bool(config.get("strict_type_filtering")),
                )
            except Exception:
                if not places:
                    raise
                continue
            for place in found:
                place_resource = str(place.get("name") or "")
                pid = str(place.get("id") or "")
                dedupe_key = place_resource or pid
                if not dedupe_key or dedupe_key in seen_place_resources:
                    continue
                seen_place_resources.add(dedupe_key)
                places.append(place)
            if len(places) >= limit:
                break
            if idx >= 1 and len(places) >= query_stop_target:
                break

        if not places and _CATEGORY_SEARCH_CONFIG[category].get("included_type"):
            for text_query in text_queries:
                try:
                    found = await _search_places_text(
                        client,
                        key,
                        text_query=text_query,
                        limit=limit,
                        location_bias=location_bias,
                    )
                except Exception:
                    continue
                for place in found:
                    place_resource = str(place.get("name") or "")
                    pid = str(place.get("id") or "")
                    dedupe_key = place_resource or pid
                    if not dedupe_key or dedupe_key in seen_place_resources:
                        continue
                    seen_place_resources.add(dedupe_key)
                    places.append(place)
                if len(places) >= limit:
                    break

        results: list[DealershipFound] = []

        candidates: list[dict[str, Any]] = []
        for place in places[:limit]:
            if not isinstance(place, dict):
                continue
            place_resource = place.get("name") or ""
            pid = place.get("id") or ""
            if not pid and place_resource.startswith("places/"):
                pid = place_resource.removeprefix("places/")

            name = _display_name(place)
            address = place.get("formattedAddress") or ""
            website = place.get("websiteUri")
            candidates.append(
                {
                    "name": name,
                    "address": address,
                    "pid": pid,
                    "place_resource": place_resource,
                    "website": website,
                }
            )

        detail_sem = asyncio.Semaphore(max(1, settings.places_details_max_concurrency))

        async def _ensure_website(c: dict[str, Any]) -> None:
            if c.get("website") or not c.get("place_resource"):
                return
            async with detail_sem:
                w = await _place_details_website(client, str(c["place_resource"]), key)
            if w:
                c["website"] = w

        await asyncio.gather(
            *(_ensure_website(c) for c in candidates if not c.get("website") and c.get("place_resource"))
        )

        for c in candidates:
            name = c["name"]
            address = c["address"]
            pid = c["pid"]
            website = _normalize_dealer_website_url(str(c.get("website") or ""))

            if not website:
                logger.debug("Skipping %s — no website in Places data", name)
                continue
            trusted_national = _is_trusted_national_retailer_match(
                name,
                str(website or ""),
                vehicle_category=category,
            )
            if _looks_like_false_positive_category_match(
                name,
                str(website or ""),
                vehicle_category=category,
            ) and not trusted_national:
                logger.debug("Skipping %s — looks like non-inventory %s retailer", name, category)
                continue
            if make_q and _looks_like_false_positive_make_match(
                name,
                str(website or ""),
                make=make_q,
                vehicle_category=category,
            ):
                logger.debug("Skipping %s — looks like false-positive make match for %s", name, make_q)
                continue

            results.append(
                DealershipFound(
                    name=name,
                    place_id=pid or place_resource,
                    address=address,
                    website=website,
                )
            )

        if not make_q:
            if category == "car":
                return results
            category_matches = [
                d for d in results if _dealer_matches_category_context(d.name, d.website or "", vehicle_category=category)
            ]
            return category_matches if category_matches else results

        if category != "car":
            category_matches = [
                d for d in results if _dealer_matches_category_context(d.name, d.website or "", vehicle_category=category)
            ]
            category_brand_matches = [
                d
                for d in category_matches
                if _name_matches_make(" ".join(filter(None, [d.name, d.website or ""])), make_q)
            ]
            if category_brand_matches:
                extras = [d for d in category_matches if d not in category_brand_matches]
                return category_brand_matches + extras[: _generic_category_fallback_cap(category)]
            # For multi-brand categories (boat, motorcycle) with a specific make that
            # has no brand-name matches in the dealer list, limit how many generic
            # marinas we return.  Google Places already ran brand-specific queries
            # (e.g. "Boston Whaler boat dealer near …") so the first results are the
            # most likely candidates. Returning all 20+ generic marinas wastes time
            # on dealers that almost certainly don't carry the brand.
            if category_matches:
                max_generic = min(len(category_matches), _generic_category_fallback_cap(category))
                return category_matches[:max_generic]

        # Include website in the haystack: OEM often appears in the domain/path (e.g. …/shop-brp/can-am)
        # but not in the Google Places display name ("River Raisin Powersports").
        brand_matches = [
            d
            for d in results
            if _name_matches_make(" ".join(filter(None, [d.name, d.website or ""])), make_q)
        ]
        # If we found brand-specific dealers, prefer those so searches feel sane to users.
        return brand_matches if brand_matches else results


async def find_car_dealerships(
    location: str,
    *,
    make: str = "",
    model: str = "",
    limit: int = 20,
    radius_miles: int = 50,
    market_region: str = "us",
) -> list[DealershipFound]:
    return await find_dealerships(
        location,
        make=make,
        model=model,
        vehicle_category="car",
        limit=limit,
        radius_miles=radius_miles,
        market_region=market_region,
    )


async def _place_details_website(
    client: httpx.AsyncClient,
    place_resource_name: str,
    key: str,
) -> str | None:
    """
    place_resource_name: `places/ChIJ…` from Text Search `name` field.
    """
    if not place_resource_name:
        return None
    # Resource name is `places/{placeId}` → GET .../v1/places/ChIJ…
    url = f"{PLACES_BASE}/{place_resource_name}"
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": DETAILS_FIELD_MASK,
    }
    r = await client.get(url, headers=headers)
    if r.status_code != 200:
        logger.debug(
            "Place Details HTTP %s for %s: %s",
            r.status_code,
            place_resource_name,
            r.text[:300],
        )
        return None
    data = r.json()
    uri = data.get("websiteUri")
    return _normalize_dealer_website_url(str(uri)) if uri else None
