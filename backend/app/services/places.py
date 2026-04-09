"""Google Places API (New): Text Search + Place Details for dealership websites."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.config import settings
from app.schemas import DealershipFound
from app.services.dealer_bias import dealer_preference_bias
from app.services.inventory_filters import normalize_model_text, text_mentions_make
from app.services.places_cache import (
    get_cached_geocode_center,
    get_cached_place_website,
    get_cached_places_search,
    places_search_cache_key,
    set_cached_geocode_center,
    set_cached_place_website,
    set_cached_places_search,
)

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
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
# GET https://places.googleapis.com/v1/places/{placeId} — {name} is "places/ChIJ…"
PLACES_BASE = "https://places.googleapis.com/v1"
METERS_PER_MILE = 1609.34
MAX_LOCATION_BIAS_RADIUS_METERS = 50_000
MAX_LOCATION_BIAS_RADIUS_MILES = int(MAX_LOCATION_BIAS_RADIUS_METERS // METERS_PER_MILE)

DISCOVERY_FIELD_MASK = "places.id,places.name,places.displayName,places.formattedAddress,places.location"
DISCOVERY_FIELD_MASK_WITH_WEBSITE = f"{DISCOVERY_FIELD_MASK},places.websiteUri"
DETAILS_FIELD_MASK = "websiteUri"
SUPPORTED_VEHICLE_CATEGORIES = {"car", "motorcycle", "boat", "other"}
EARTH_RADIUS_MILES = 3958.8


@dataclass(slots=True)
class PlacesSearchMetrics:
    search_calls: int = 0
    details_calls: int = 0
    location_resolve_calls: int = 0
    fallback_query_passes: int = 0
    search_cache_hits: int = 0
    detail_cache_hits: int = 0
    geocode_cache_hits: int = 0
    query_variants_total: int = 0
    query_variants_used: int = 0
    detail_candidates_considered: int = 0
    detail_candidates_resolved: int = 0
    detail_candidates_skipped: int = 0
    search_status_code_counts: dict[str, int] = field(default_factory=dict)
    detail_status_code_counts: dict[str, int] = field(default_factory=dict)
    geocode_status_code_counts: dict[str, int] = field(default_factory=dict)

    @property
    def discovery_mode(self) -> str:
        return "enterprise_with_website" if settings.places_discovery_include_website_uri else "pro_without_website"

    def bump_status(self, bucket: dict[str, int], status_code: int | str) -> None:
        key = str(status_code)
        bucket[key] = int(bucket.get(key, 0)) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "search_calls": self.search_calls,
            "details_calls": self.details_calls,
            "location_resolve_calls": self.location_resolve_calls,
            "fallback_query_passes": self.fallback_query_passes,
            "search_cache_hits": self.search_cache_hits,
            "detail_cache_hits": self.detail_cache_hits,
            "geocode_cache_hits": self.geocode_cache_hits,
            "query_variants_total": self.query_variants_total,
            "query_variants_used": self.query_variants_used,
            "detail_candidates_considered": self.detail_candidates_considered,
            "detail_candidates_resolved": self.detail_candidates_resolved,
            "detail_candidates_skipped": self.detail_candidates_skipped,
            "discovery_mode": self.discovery_mode,
            "search_status_code_counts": dict(sorted(self.search_status_code_counts.items())),
            "detail_status_code_counts": dict(sorted(self.detail_status_code_counts.items())),
            "geocode_status_code_counts": dict(sorted(self.geocode_status_code_counts.items())),
        }


@dataclass(slots=True)
class _GeocodeLocationLabel:
    search_label: str
    country_code: str | None = None


def _normalize_location_text(location: str) -> str:
    return re.sub(r"\s+", " ", str(location or "").strip())


def _resolved_location_cache_key(
    location: str,
    *,
    center: tuple[float, float] | None,
) -> str:
    normalized = _normalize_location_text(location)
    if center is None:
        return normalized
    lat, lng = center
    return f"resolved:{lat:.3f},{lng:.3f}"


def _search_field_mask() -> str:
    if settings.places_discovery_include_website_uri:
        return DISCOVERY_FIELD_MASK_WITH_WEBSITE
    return DISCOVERY_FIELD_MASK
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
_CORPORATE_NON_DEALER_NAME_HINTS: tuple[str, ...] = (
    "main office",
    "corporate office",
    "headquarters",
    "head office",
    "national office",
    "home office",
)
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


def _looks_like_corporate_non_dealer(name: str) -> bool:
    hay = (name or "").strip().lower()
    if not hay:
        return False
    return any(token in hay for token in _CORPORATE_NON_DEALER_NAME_HINTS)


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
    location_restriction: dict[str, Any] | None = None,
    included_type: str | None = None,
    strict_type_filtering: bool = False,
    metrics: PlacesSearchMetrics | None = None,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "textQuery": text_query,
        "pageSize": min(limit, 20),
        "languageCode": "en",
    }
    if included_type:
        body["includedType"] = included_type
        body["strictTypeFiltering"] = strict_type_filtering
    if location_restriction:
        body["locationRestriction"] = location_restriction
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": _search_field_mask(),
    }
    if metrics is not None:
        metrics.search_calls += 1
    r = await client.post(SEARCH_TEXT_URL, json=body, headers=headers)
    if metrics is not None:
        metrics.bump_status(metrics.search_status_code_counts, r.status_code)
    if r.status_code != 200:
        logger.warning("Places searchText HTTP %s for %r: %s", r.status_code, text_query, r.text[:500])
        raise RuntimeError(
            f"Google Places Text Search (New) failed: HTTP {r.status_code}. {_api_error_message(r.json() if r.content else {})}"
        )
    payload = r.json()
    places = payload.get("places") or []
    return [p for p in places if isinstance(p, dict)]


async def _resolve_location_center(
    client: httpx.AsyncClient,
    key: str,
    *,
    location: str,
    metrics: PlacesSearchMetrics | None = None,
) -> tuple[float, float] | None:
    normalized_location = _normalize_location_text(location)
    if not normalized_location:
        return None
    cached = get_cached_geocode_center(normalized_location)
    if cached is not None:
        if metrics is not None:
            metrics.geocode_cache_hits += 1
        return cached
    params = {"address": normalized_location, "key": key}
    if metrics is not None:
        metrics.location_resolve_calls += 1
    try:
        r = await client.get(GEOCODE_URL, params=params)
    except Exception as e:
        logger.debug("Location geocode lookup failed for %r: %s", normalized_location, e)
        return None
    if metrics is not None:
        metrics.bump_status(metrics.geocode_status_code_counts, r.status_code)
    if r.status_code != 200:
        logger.debug("Location geocode HTTP %s for %r: %s", r.status_code, normalized_location, r.text[:300])
        return None
    payload = r.json() if r.content else {}
    
    if payload.get("status") == "REQUEST_DENIED":
        logger.error(f"Geocoding API REQUEST_DENIED. Please enable the 'Geocoding API' in Google Cloud Console for your API key. Error: {payload.get('error_message')}")
        
    results = payload.get("results") if isinstance(payload, dict) else None
    if not results or not isinstance(results, list) or not isinstance(results[0], dict):
        return None
    geometry = results[0].get("geometry") or {}
    point = geometry.get("location") or {}
    lat = point.get("lat")
    lng = point.get("lng")
    if lat is None or lng is None:
        return None
    center = (float(lat), float(lng))
    set_cached_geocode_center(normalized_location, center)
    return center


def _address_component_value(
    components: list[dict[str, Any]],
    *types: str,
    short: bool = False,
) -> str | None:
    type_set = set(types)
    for component in components:
        raw_types = component.get("types")
        if not isinstance(raw_types, list) or not any(t in type_set for t in raw_types):
            continue
        value = component.get("short_name" if short else "long_name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def _reverse_geocode_search_label(
    client: httpx.AsyncClient,
    key: str,
    *,
    lat: float,
    lng: float,
    metrics: PlacesSearchMetrics | None = None,
) -> _GeocodeLocationLabel | None:
    params = {
        "latlng": f"{lat:.6f},{lng:.6f}",
        "key": key,
        "result_type": "locality|postal_town|administrative_area_level_3|administrative_area_level_2",
    }
    if metrics is not None:
        metrics.location_resolve_calls += 1
    try:
        r = await client.get(GEOCODE_URL, params=params)
    except Exception as e:
        logger.debug("Reverse geocode lookup failed for (%s, %s): %s", lat, lng, e)
        return None
    if metrics is not None:
        metrics.bump_status(metrics.geocode_status_code_counts, r.status_code)
    if r.status_code != 200:
        logger.debug("Reverse geocode HTTP %s for (%s, %s): %s", r.status_code, lat, lng, r.text[:300])
        return None
    payload = r.json() if r.content else {}
    results = payload.get("results") if isinstance(payload, dict) else None
    if not results or not isinstance(results, list):
        return None

    for result in results:
        if not isinstance(result, dict):
            continue
        components = result.get("address_components")
        if not isinstance(components, list):
            continue
        locality = _address_component_value(
            components,
            "locality",
            "postal_town",
            "administrative_area_level_3",
            "administrative_area_level_2",
        )
        if not locality:
            continue
        region = _address_component_value(components, "administrative_area_level_1", short=True)
        country_code = _address_component_value(components, "country", short=True)
        label = locality if not region else f"{locality}, {region}"
        return _GeocodeLocationLabel(search_label=label, country_code=country_code)
    return None


def _destination_point(*, lat: float, lng: float, bearing_degrees: float, distance_miles: float) -> tuple[float, float]:
    angular_distance = distance_miles / EARTH_RADIUS_MILES
    bearing = math.radians(bearing_degrees)
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lng2 = lng1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lat2), ((math.degrees(lng2) + 540.0) % 360.0) - 180.0)


def _should_expand_large_radius_locations(
    *,
    location: str,
    radius_miles: int,
    market_region: str,
) -> bool:
    if "|" in (location or ""):
        return False
    if radius_miles < 150:
        return False
    return (market_region or "").strip().lower() in {"", "us", "ca"}


async def expand_large_radius_search_locations(
    location: str,
    *,
    radius_miles: int,
    market_region: str = "us",
    max_locations: int = 5,
    metrics: PlacesSearchMetrics | None = None,
) -> list[str]:
    """Add nearby city-style aliases for sparse large-radius ZIP/city searches."""
    base_location = _normalize_location_text(location)
    if not base_location:
        return []
    max_locations = max(1, int(max_locations or 1))
    locations: list[str] = [base_location]
    if max_locations <= 1 or not _should_expand_large_radius_locations(location=base_location, radius_miles=radius_miles, market_region=market_region):
        return locations
    key = settings.google_places_api_key.strip()
    if not key:
        return locations

    sample_distance = min(float(radius_miles) * 0.55, max(60.0, float(radius_miles) - 20.0))
    bearings = (270.0, 180.0, 0.0, 90.0, 315.0, 225.0, 45.0, 135.0)
    try:
        async with httpx.AsyncClient() as client:
            center = await _resolve_location_center(client, key, location=base_location, metrics=metrics)
            if center is None:
                return locations
            origin_label = await _reverse_geocode_search_label(
                client,
                key,
                lat=center[0],
                lng=center[1],
                metrics=metrics,
            )
            seen = {base_location.lower()}
            same_country_code = origin_label.country_code if origin_label else None
            if origin_label is not None and origin_label.search_label.lower() not in seen:
                seen.add(origin_label.search_label.lower())
                locations.append(origin_label.search_label)
            for bearing in bearings:
                if len(locations) >= max_locations:
                    break
                sample_lat, sample_lng = _destination_point(
                    lat=center[0],
                    lng=center[1],
                    bearing_degrees=bearing,
                    distance_miles=sample_distance,
                )
                alias = await _reverse_geocode_search_label(
                    client,
                    key,
                    lat=sample_lat,
                    lng=sample_lng,
                    metrics=metrics,
                )
                if alias is None:
                    continue
                if same_country_code and alias.country_code and alias.country_code != same_country_code:
                    continue
                alias_key = alias.search_label.lower()
                if alias_key in seen:
                    continue
                seen.add(alias_key)
                locations.append(alias.search_label)
    except Exception as e:
        logger.debug("Large-radius location expansion failed for %r: %s", base_location, e)
        return [base_location]
    return locations[:max_locations]


async def resolve_search_location_center(
    location: str,
    *,
    metrics: PlacesSearchMetrics | None = None,
) -> tuple[float, float] | None:
    key = settings.google_places_api_key.strip()
    if not key:
        return None
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await _resolve_location_center(client, key, location=location, metrics=metrics)


def _bounding_box_for_radius(*, center_lat: float, center_lng: float, radius_miles: int) -> dict[str, Any]:
    lat_delta_deg = math.degrees(radius_miles / EARTH_RADIUS_MILES)
    # Avoid division by zero at the poles.
    cos_lat = max(0.0001, math.cos(math.radians(center_lat)))
    lng_delta_deg = math.degrees(radius_miles / (EARTH_RADIUS_MILES * cos_lat))

    low_lat = max(-90.0, center_lat - lat_delta_deg)
    high_lat = min(90.0, center_lat + lat_delta_deg)
    low_lng = max(-180.0, center_lng - lng_delta_deg)
    high_lng = min(180.0, center_lng + lng_delta_deg)
    return {
        "rectangle": {
            "low": {"latitude": low_lat, "longitude": low_lng},
            "high": {"latitude": high_lat, "longitude": high_lng},
        }
    }


def _haversine_distance_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    return EARTH_RADIUS_MILES * c


def _place_within_radius(
    place: dict[str, Any],
    *,
    center_lat: float,
    center_lng: float,
    radius_miles: int,
    require_coordinates: bool = False,
) -> bool:
    point = place.get("location") or {}
    lat = point.get("latitude")
    lng = point.get("longitude")
    if lat is None or lng is None:
        return not require_coordinates
    return _haversine_distance_miles(center_lat, center_lng, float(lat), float(lng)) <= float(radius_miles)


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

    # Social/profile URLs are discovery dead ends: Places sometimes returns a dealership's
    # Facebook or Instagram page instead of the actual inventory site.
    _SOCIAL_PROFILE_HOSTS = {
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
        "instagram.com",
        "www.instagram.com",
        "x.com",
        "www.x.com",
        "twitter.com",
        "www.twitter.com",
        "tiktok.com",
        "www.tiktok.com",
        "youtube.com",
        "www.youtube.com",
        "linkedin.com",
        "www.linkedin.com",
        "linktr.ee",
        "www.linktr.ee",
    }
    if host in _SOCIAL_PROFILE_HOSTS:
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


def _looks_like_us_zip_location(location: str) -> bool:
    value = (location or "").strip()
    if not value:
        return False
    return bool(re.fullmatch(r"\d{5}(?:-\d{4})?", value))


def _build_text_queries(
    *,
    vehicle_category: str,
    location: str,
    make: str,
    model: str,
    market_region: str = "us",
    prefer_small_dealers: bool = False,
) -> list[str]:
    config = _CATEGORY_SEARCH_CONFIG[_normalize_vehicle_category(vehicle_category)]
    make_q = make.strip()
    model_q = model.strip()
    dealer_terms = tuple(config["dealer_terms"])
    fallback_terms = tuple(config["fallback_terms"])
    eu = (market_region or "").strip().lower() == "eu"

    text_queries: list[str] = []
    primary_term = dealer_terms[0]
    prefer_smaller_car_queries = prefer_small_dealers and _normalize_vehicle_category(vehicle_category) == "car"
    if prefer_smaller_car_queries and make_q:
        if model_q:
            text_queries.append(f"{make_q} {model_q} used cars near {location}")
            text_queries.append(f"{model_q} used cars near {location}")
        text_queries.extend(
            [
                f"{make_q} used cars near {location}",
                f"used car dealer near {location}",
                f"auto sales near {location}",
                f"independent used car dealer near {location}",
            ]
        )
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
    cap = max(1, int(settings.places_text_query_variant_cap or 1))
    return deduped[:cap]


def _places_query_stop_target(*, limit: int, make: str, model: str) -> int:
    """Stop once we have enough likely candidates for dedupe/filtering."""
    limit = max(1, int(limit or 1))
    if not (make.strip() or model.strip()):
        return limit
    return min(limit, max(8, int(limit * 0.6)))


async def _search_places_query_batch(
    client: httpx.AsyncClient,
    key: str,
    *,
    text_queries: list[str],
    limit: int,
    location_restriction: dict[str, Any] | None = None,
    included_type: str | None = None,
    strict_type_filtering: bool = False,
    metrics: PlacesSearchMetrics | None = None,
) -> list[list[dict[str, Any]] | Exception]:
    if metrics is not None:
        metrics.query_variants_used += len(text_queries)
    return await asyncio.gather(
        *(
            _search_places_text(
                client,
                key,
                text_query=text_query,
                limit=limit,
                location_restriction=location_restriction,
                included_type=included_type,
                strict_type_filtering=strict_type_filtering,
                metrics=metrics,
            )
            for text_query in text_queries
        ),
        return_exceptions=True,
    )


def _append_discovered_places(
    *,
    found: list[dict[str, Any]],
    places: list[dict[str, Any]],
    seen_place_resources: set[str],
    location_center: tuple[float, float] | None,
    requested_radius: int,
    require_precise_radius_coordinates: bool,
) -> None:
    for place in found:
        if location_center is not None and not _place_within_radius(
            place,
            center_lat=location_center[0],
            center_lng=location_center[1],
            radius_miles=requested_radius,
            require_coordinates=require_precise_radius_coordinates,
        ):
            continue
        place_resource = str(place.get("name") or "")
        pid = str(place.get("id") or "")
        dedupe_key = place_resource or pid
        if not dedupe_key or dedupe_key in seen_place_resources:
            continue
        seen_place_resources.add(dedupe_key)
        places.append(place)


async def find_dealerships(
    location: str,
    *,
    make: str = "",
    model: str = "",
    vehicle_category: str = "car",
    prefer_small_dealers: bool = False,
    limit: int = 20,
    radius_miles: int = 50,
    market_region: str = "us",
    metrics: PlacesSearchMetrics | None = None,
    query_variant_limit: int | None = None,
    location_center_override: tuple[float, float] | None = None,
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

    normalized_location = _normalize_location_text(location)
    make_q = make.strip()
    model_q = model.strip()
    requested_radius = max(5, min(int(radius_miles or 25), 250))
    metrics = metrics or PlacesSearchMetrics()
    use_search_cache = query_variant_limit is None and location_center_override is None
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        location_center = location_center_override
        if location_center is None and requested_radius >= max(1, int(settings.places_geocode_min_radius_miles or 0)):
            location_center = await _resolve_location_center(
                client,
                key,
                location=normalized_location,
                metrics=metrics,
            )
        search_cache_key = places_search_cache_key(
            location=_resolved_location_cache_key(normalized_location, center=location_center),
            make=make_q,
            model=model_q,
            vehicle_category=vehicle_category,
            radius_miles=requested_radius,
            market_region=market_region,
            prefer_small_dealers=prefer_small_dealers,
        )
            
        if use_search_cache and location_center is not None and not prefer_small_dealers:
            from app.services.places_supabase import check_supabase_cache
            center_lat, center_lng = location_center
            supabase_cached_results = check_supabase_cache(
                make=make_q,
                vehicle_category=vehicle_category,
                lat=center_lat,
                lng=center_lng,
                radius_miles=requested_radius,
            )
            if supabase_cached_results is not None:
                metrics.search_cache_hits += 1
                return supabase_cached_results

        if use_search_cache:
            cached_results = get_cached_places_search(search_cache_key)
            if cached_results is not None:
                metrics.search_cache_hits += 1
                for r in cached_results:
                    if r.discovery_source is None:
                        r.discovery_source = "memory_cache"
                return cached_results

        location_restriction = None
        if location_center is not None:
            center_lat, center_lng = location_center
            location_restriction = _bounding_box_for_radius(
                center_lat=center_lat,
                center_lng=center_lng,
                radius_miles=requested_radius,
            )
        category = _normalize_vehicle_category(vehicle_category)
        places_category = _effective_places_search_category(vehicle_category, make_q)
        config = _CATEGORY_SEARCH_CONFIG[places_category]
        text_queries = _build_text_queries(
            vehicle_category=places_category,
            location=normalized_location,
            make=make_q,
            model=model_q,
            market_region=market_region,
            prefer_small_dealers=prefer_small_dealers,
        )
        if query_variant_limit is not None:
            text_queries = text_queries[: max(1, int(query_variant_limit))]
        metrics.query_variants_total = len(text_queries)
        query_stop_target = _places_query_stop_target(limit=limit, make=make_q, model=model_q)
        require_precise_radius_coordinates = bool(
            location_center is not None
            and category != "car"
            and make_q
            and _looks_like_us_zip_location(normalized_location)
        )

        places: list[dict[str, Any]] = []
        seen_place_resources: set[str] = set()
        query_batch_size = min(3, max(1, len(text_queries)))
        for start_idx in range(0, len(text_queries), query_batch_size):
            batch_queries = text_queries[start_idx : start_idx + query_batch_size]
            batch_results = await _search_places_query_batch(
                client,
                key,
                text_queries=batch_queries,
                limit=limit,
                location_restriction=location_restriction,
                included_type=config.get("included_type"),
                strict_type_filtering=bool(config.get("strict_type_filtering")),
                metrics=metrics,
            )
            batch_had_success = False
            first_error: Exception | None = None
            for found in batch_results:
                if isinstance(found, Exception):
                    if first_error is None:
                        first_error = found
                    continue
                batch_had_success = True
                _append_discovered_places(
                    found=found,
                    places=places,
                    seen_place_resources=seen_place_resources,
                    location_center=location_center,
                    requested_radius=requested_radius,
                    require_precise_radius_coordinates=require_precise_radius_coordinates,
                )
            if not batch_had_success and not places and first_error is not None:
                raise first_error
            if len(places) >= limit:
                break
            if start_idx + len(batch_queries) - 1 >= 1 and len(places) >= query_stop_target:
                break

        fallback_threshold = max(0, int(settings.places_untyped_fallback_result_threshold or 0))
        should_try_untyped_fallback = (
            bool(_CATEGORY_SEARCH_CONFIG[category].get("included_type"))
            and len(places) <= fallback_threshold
            and not model_q
        )
        if should_try_untyped_fallback:
            metrics.fallback_query_passes += 1
            for start_idx in range(0, len(text_queries), query_batch_size):
                batch_queries = text_queries[start_idx : start_idx + query_batch_size]
                batch_results = await _search_places_query_batch(
                    client,
                    key,
                    text_queries=batch_queries,
                    limit=limit,
                    location_restriction=location_restriction,
                    metrics=metrics,
                )
                for found in batch_results:
                    if isinstance(found, Exception):
                        continue
                    _append_discovered_places(
                        found=found,
                        places=places,
                        seen_place_resources=seen_place_resources,
                        location_center=location_center,
                        requested_radius=requested_radius,
                        require_precise_radius_coordinates=require_precise_radius_coordinates,
                    )
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
            
            location_obj = place.get("location") or {}
            lat = location_obj.get("latitude")
            lng = location_obj.get("longitude")
            
            candidates.append(
                {
                    "name": name,
                    "address": address,
                    "pid": pid,
                    "place_resource": place_resource,
                    "website": _normalize_dealer_website_url(str(website or "")) if website else "",
                    "lat": lat,
                    "lng": lng,
                }
            )

        detail_sem = asyncio.Semaphore(max(1, settings.places_details_max_concurrency))
        metrics.detail_candidates_considered = len(candidates)
        detail_budget = int(getattr(settings, "places_details_budget_per_search", 0) or 0)

        # Pre-populate websites from the place-website SQLite cache so those
        # candidates don't consume a live-API detail budget slot.
        for c in candidates:
            if not c.get("website") and c.get("place_resource"):
                cached_website = get_cached_place_website(str(c["place_resource"]))
                if cached_website is not None:
                    metrics.detail_cache_hits += 1
                    c["website"] = cached_website

        # Only candidates that still lack a website after the cache check need a live call.
        detail_candidates = [c for c in candidates if not c.get("website") and c.get("place_resource")]
        if detail_budget > 0 and len(detail_candidates) > detail_budget:
            metrics.detail_candidates_skipped = len(detail_candidates) - detail_budget
            detail_candidates = detail_candidates[:detail_budget]
        search_cache_complete = metrics.detail_candidates_skipped == 0

        async def _ensure_website(c: dict[str, Any]) -> None:
            if c.get("website") or not c.get("place_resource"):
                return
            async with detail_sem:
                w = await _place_details_website(client, str(c["place_resource"]), key, metrics=metrics)
            set_cached_place_website(str(c["place_resource"]), w)
            c["website"] = w or ""

        await asyncio.gather(
            *(_ensure_website(c) for c in detail_candidates)
        )

        for c in candidates:
            name = c["name"]
            address = c["address"]
            pid = c["pid"]
            website = _normalize_dealer_website_url(str(c.get("website") or ""))

            if not website:
                logger.debug("Skipping %s — no website in Places data", name)
                continue
            if _looks_like_corporate_non_dealer(name):
                logger.debug("Skipping %s — appears to be corporate office, not local dealer", name)
                continue
            metrics.detail_candidates_resolved += 1
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
                    lat=c.get("lat"),
                    lng=c.get("lng"),
                    discovery_source="google",
                )
            )

        def _finalize(found: list[DealershipFound]) -> list[DealershipFound]:
            if use_search_cache and found:
                # Only write the in-memory SQLite cache when the search was
                # complete (no candidates skipped due to the detail budget).
                if search_cache_complete:
                    set_cached_places_search(search_cache_key, found)
                # Always persist to Supabase — the found list only contains
                # dealers whose websites were resolved, so it is accurate even
                # when the detail budget trimmed some candidates.
                if location_center is not None and not prefer_small_dealers:
                    from app.services.places_supabase import save_to_supabase_cache
                    center_lat, center_lng = location_center
                    save_to_supabase_cache(
                        make=make_q,
                        vehicle_category=vehicle_category,
                        lat=center_lat,
                        lng=center_lng,
                        radius_miles=requested_radius,
                        dealerships=found,
                    )
            return found

        if not make_q:
            if category == "car":
                return _finalize(results)
            category_matches = [
                d for d in results if _dealer_matches_category_context(d.name, d.website or "", vehicle_category=category)
            ]
            return _finalize(category_matches if category_matches else results)

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
                # Keep generic multi-brand fallbacks only when we found very few
                # make-matching dealers. When we already have multiple strong
                # make matches, adding generic powersports/marine dealers mostly
                # adds "no listings" noise in downstream scrape runs.
                if len(category_brand_matches) >= 2:
                    return _finalize(category_brand_matches)
                extras = [d for d in category_matches if d not in category_brand_matches]
                return _finalize(category_brand_matches + extras[: _generic_category_fallback_cap(category)])
            # For multi-brand categories (boat, motorcycle) with a specific make that
            # has no brand-name matches in the dealer list, limit how many generic
            # marinas we return.  Google Places already ran brand-specific queries
            # (e.g. "Boston Whaler boat dealer near …") so the first results are the
            # most likely candidates. Returning all 20+ generic marinas wastes time
            # on dealers that almost certainly don't carry the brand.
            if category_matches:
                max_generic = min(len(category_matches), _generic_category_fallback_cap(category))
                return _finalize(category_matches[:max_generic])

        if prefer_small_dealers:
            ranked_results = sorted(
                results,
                key=lambda dealer: dealer_preference_bias(
                    dealer.name,
                    dealer.website,
                    search_make=make_q,
                ),
                reverse=True,
            )
            return _finalize(ranked_results)

        # Include website in the haystack: OEM often appears in the domain/path (e.g. …/shop-brp/can-am)
        # but not in the Google Places display name ("River Raisin Powersports").
        brand_matches = [
            d
            for d in results
            if _name_matches_make(" ".join(filter(None, [d.name, d.website or ""])), make_q)
        ]
        # If we found brand-specific dealers, prefer those so searches feel sane to users.
        return _finalize(brand_matches if brand_matches else results)


async def find_car_dealerships(
    location: str,
    *,
    make: str = "",
    model: str = "",
    prefer_small_dealers: bool = False,
    limit: int = 20,
    radius_miles: int = 50,
    market_region: str = "us",
    metrics: PlacesSearchMetrics | None = None,
    query_variant_limit: int | None = None,
    location_center_override: tuple[float, float] | None = None,
) -> list[DealershipFound]:
    return await find_dealerships(
        location,
        make=make,
        model=model,
        vehicle_category="car",
        prefer_small_dealers=prefer_small_dealers,
        limit=limit,
        radius_miles=radius_miles,
        market_region=market_region,
        metrics=metrics,
        query_variant_limit=query_variant_limit,
        location_center_override=location_center_override,
    )


async def _place_details_website(
    client: httpx.AsyncClient,
    place_resource_name: str,
    key: str,
    metrics: PlacesSearchMetrics | None = None,
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
    if metrics is not None:
        metrics.details_calls += 1
    r = await client.get(url, headers=headers)
    if metrics is not None:
        metrics.bump_status(metrics.detail_status_code_counts, r.status_code)
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
