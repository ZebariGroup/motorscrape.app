"""Google Places (legacy) Text Search + Place Details for dealership websites."""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.schemas import DealershipFound

logger = logging.getLogger(__name__)

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def _places_failure_message(payload: dict, *, label: str) -> str:
    status = payload.get("status")
    detail = payload.get("error_message") or "No error_message from Google."
    return f"{label} failed: {status}. {detail}"


async def find_car_dealerships(location: str, *, limit: int = 20) -> list[DealershipFound]:
    """
    Find car dealerships near the given location using Places Text Search,
    then fetch Place Details for each result to obtain `website` when missing.
    """
    key = settings.google_places_api_key
    if not key:
        raise ValueError(
            "Google Places API key is not set. Use env var GOOGLE_PLACES_API_KEY "
            "(or GOOGLE_MAPS_API_KEY). On Vercel, add it in Project → Settings → "
            "Environment Variables for Production and Preview; a local .env file is not deployed."
        )

    query = f"car dealership near {location}"
    params = {"query": query, "key": key, "type": "car_dealer"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(TEXT_SEARCH_URL, params=params)
        r.raise_for_status()
        payload = r.json()
        status = payload.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            logger.warning("Places text search status=%s error_message=%s", status, payload.get("error_message"))
            raise RuntimeError(_places_failure_message(payload, label="Google Places Text Search"))

        results: list[DealershipFound] = []
        for item in payload.get("results", [])[:limit]:
            place_id = item.get("place_id") or ""
            name = item.get("name") or "Unknown"
            address = item.get("formatted_address") or ""
            website = item.get("website")  # usually absent on text search

            if not website and place_id:
                website = await _place_details_website(client, place_id, key)

            if not website:
                logger.debug("Skipping %s — no website in Places data", name)
                continue

            results.append(
                DealershipFound(
                    name=name,
                    place_id=place_id,
                    address=address,
                    website=website,
                )
            )

        return results


async def _place_details_website(client: httpx.AsyncClient, place_id: str, key: str) -> str | None:
    params = {
        "place_id": place_id,
        "fields": "website,name",
        "key": key,
    }
    r = await client.get(DETAILS_URL, params=params)
    r.raise_for_status()
    data = r.json()
    st = data.get("status")
    if st != "OK":
        logger.debug(
            "Place Details status=%s place_id=%s error_message=%s",
            st,
            place_id,
            data.get("error_message"),
        )
        return None
    result = data.get("result") or {}
    return result.get("website")
