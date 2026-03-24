"""Google Places API (New): Text Search + Place Details for dealership websites."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import httpx

from app.config import settings
from app.schemas import DealershipFound

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
    mk = make.strip().lower()
    nm = dealer_name.strip().lower()
    if not mk:
        return True
    # Treat punctuation/spacing variants as equivalent.
    mk_compact = "".join(ch for ch in mk if ch.isalnum())
    nm_compact = "".join(ch for ch in nm if ch.isalnum())
    return mk in nm or (mk_compact and mk_compact in nm_compact)


async def _search_places_text(
    client: httpx.AsyncClient,
    key: str,
    *,
    text_query: str,
    limit: int,
    location_bias: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "textQuery": text_query,
        "includedType": "car_dealer",
        "strictTypeFiltering": True,
        "pageSize": min(limit, 20),
        "languageCode": "en",
    }
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

    return {
        "circle": {
            "center": {"latitude": lat, "longitude": lng},
            "radius": min(
                int(radius_miles * METERS_PER_MILE),
                MAX_LOCATION_BIAS_RADIUS_METERS,
            ),
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

    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw

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


async def find_car_dealerships(
    location: str,
    *,
    make: str = "",
    model: str = "",
    limit: int = 20,
    radius_miles: int = 50,
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
        text_queries: list[str] = []
        if make_q and model_q:
            text_queries.append(f"{make_q} {model_q} car dealership near {location}")
        elif make_q:
            text_queries.append(f"{make_q} car dealership near {location}")
        elif model_q:
            text_queries.append(f"{model_q} car dealership near {location}")
        else:
            text_queries.append(f"car dealership near {location}")

        # Places ranking can under-return franchise dealers for some low-volume models.
        # Supplement with a fixed query set so dealership discovery stays consistent.
        if make_q:
            text_queries.append(f"new {make_q} near {location}")
            text_queries.append(f"{make_q} showroom near {location}")
            text_queries.append(f"{make_q} dealer near {location}")
            text_queries.append(f"{make_q} inventory near {location}")

        places: list[dict[str, Any]] = []
        seen_place_resources: set[str] = set()
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

        results: list[DealershipFound] = []

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

            if not website and place_resource:
                website = await _place_details_website(client, place_resource, key)
            website = _normalize_dealer_website_url(str(website or ""))

            if not website:
                logger.debug("Skipping %s — no website in Places data", name)
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
            return results

        brand_matches = [d for d in results if _name_matches_make(d.name, make_q)]
        # If we found brand-specific dealers, prefer those so searches feel sane to users.
        return brand_matches if brand_matches else results


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
