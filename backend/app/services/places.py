"""Google Places API (New): Text Search + Place Details for dealership websites."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.schemas import DealershipFound

logger = logging.getLogger(__name__)

SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
# GET https://places.googleapis.com/v1/places/{placeId} — {name} is "places/ChIJ…"
PLACES_BASE = "https://places.googleapis.com/v1"

# Text Search (New) field mask — websiteUri uses Enterprise SKU; omit if you need to trim billing.
SEARCH_FIELD_MASK = (
    "places.id,places.name,places.displayName,places.formattedAddress,places.websiteUri"
)
DETAILS_FIELD_MASK = "websiteUri"


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


async def find_car_dealerships(location: str, *, limit: int = 20) -> list[DealershipFound]:
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

    body: dict[str, Any] = {
        "textQuery": f"car dealership near {location}",
        "includedType": "car_dealer",
        "strictTypeFiltering": True,
        "pageSize": min(limit, 20),
        "languageCode": "en",
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": SEARCH_FIELD_MASK,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(SEARCH_TEXT_URL, json=body, headers=headers)
        if r.status_code != 200:
            logger.warning("Places searchText HTTP %s: %s", r.status_code, r.text[:500])
            raise RuntimeError(
                f"Google Places Text Search (New) failed: HTTP {r.status_code}. {_api_error_message(r.json() if r.content else {})}"
            )

        payload = r.json()
        places = payload.get("places") or []
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

        return results


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
    return str(uri) if uri else None
