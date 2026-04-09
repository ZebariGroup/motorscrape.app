from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.schemas import VehicleListing

logger = logging.getLogger(__name__)

MARKETCHECK_BASE_URL = "https://marketcheck-prod.apigee.net/v2/search/car/active"

_marketcheck_lock = asyncio.Lock()
_marketcheck_client: httpx.AsyncClient | None = None
_marketcheck_semaphore: asyncio.Semaphore | None = None
_cache_lock = asyncio.Lock()

@dataclass(slots=True)
class _CachedMarketcheck:
    expires_at: float
    decoded: dict[str, Any] | None

_decode_cache: dict[str, _CachedMarketcheck] = {}

async def _get_client() -> httpx.AsyncClient:
    global _marketcheck_client
    if _marketcheck_client is None:
        async with _marketcheck_lock:
            if _marketcheck_client is None:
                _marketcheck_client = httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=httpx.Timeout(settings.marketcheck_timeout),
                )
    return _marketcheck_client

async def _get_semaphore() -> asyncio.Semaphore:
    global _marketcheck_semaphore
    if _marketcheck_semaphore is None:
        async with _marketcheck_lock:
            if _marketcheck_semaphore is None:
                _marketcheck_semaphore = asyncio.Semaphore(max(1, int(settings.marketcheck_max_concurrency or 1)))
    return _marketcheck_semaphore

async def close_marketcheck_http_client() -> None:
    global _marketcheck_client
    async with _marketcheck_lock:
        if _marketcheck_client is not None:
            await _marketcheck_client.aclose()
            _marketcheck_client = None

def _parse_marketcheck_response(vin: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    listings = payload.get("listings")
    if not listings or not isinstance(listings, list):
        return None
    
    # We just need the first match for the VIN to extract specs and market value
    first_match = listings[0]
    
    build = first_match.get("build", {})
    trim = build.get("trim")
    
    # Marketcheck often provides an estimated market value or price
    estimated_market_value = first_match.get("price")
    
    # Extract features/packages if available
    features = []
    extra = first_match.get("extra", {})
    if extra and isinstance(extra.get("features"), list):
        features = extra["features"]
        
    days_to_sell = first_match.get("dom") # Days on market
    
    decoded = {
        "marketcheck_trim": trim,
        "estimated_market_value": float(estimated_market_value) if estimated_market_value else None,
        "marketcheck_features": features,
        "marketcheck_days_to_sell": int(days_to_sell) if days_to_sell is not None else None,
    }
    
    if not any(value for value in decoded.values() if value is not None and value != []):
        return None
        
    return decoded

async def _fetch_marketcheck_data(vin: str) -> dict[str, Any] | None:
    if not settings.marketcheck_api_key:
        return None
        
    now = time.time()
    async with _cache_lock:
        cached = _decode_cache.get(vin)
        if cached is not None and cached.expires_at > now:
            return cached.decoded

    client = await _get_client()
    semaphore = await _get_semaphore()
    decoded: dict[str, Any] | None = None
    
    try:
        async with semaphore:
            response = await client.get(
                MARKETCHECK_BASE_URL,
                params={
                    "api_key": settings.marketcheck_api_key,
                    "vins": vin,
                    "rows": 1,
                }
            )
            response.raise_for_status()
            payload = response.json()
            decoded = _parse_marketcheck_response(vin, payload)
    except Exception as exc:
        logger.debug("Marketcheck fetch failed for %s: %s", vin, exc)

    async with _cache_lock:
        _decode_cache[vin] = _CachedMarketcheck(
            expires_at=now + max(60, int(settings.marketcheck_cache_ttl_seconds or 0)),
            decoded=decoded,
        )
    return decoded

def _merge_marketcheck_fields(listing: VehicleListing, decoded: dict[str, Any]) -> VehicleListing:
    update: dict[str, Any] = {}
    if not listing.marketcheck_trim and decoded.get("marketcheck_trim"):
        update["marketcheck_trim"] = decoded["marketcheck_trim"]
    if decoded.get("estimated_market_value") is not None:
        update["estimated_market_value"] = decoded["estimated_market_value"]
    if decoded.get("marketcheck_features"):
        update["marketcheck_features"] = decoded["marketcheck_features"]
    if decoded.get("marketcheck_days_to_sell") is not None:
        update["marketcheck_days_to_sell"] = decoded["marketcheck_days_to_sell"]
        
    if not update:
        return listing
    return listing.model_copy(update=update)

async def enrich_with_marketcheck(listings: list[VehicleListing]) -> list[VehicleListing]:
    if not settings.marketcheck_api_key or not listings:
        return listings

    vin_to_indexes: dict[str, list[int]] = {}
    for idx, listing in enumerate(listings):
        vin = listing.vin or listing.vehicle_identifier
        if not vin or len(vin) != 17:
            continue
        vin_to_indexes.setdefault(vin, []).append(idx)

    if not vin_to_indexes:
        return listings

    decoded_rows = await asyncio.gather(*[_fetch_marketcheck_data(vin) for vin in vin_to_indexes])
    out = list(listings)
    for vin, decoded in zip(vin_to_indexes, decoded_rows, strict=False):
        if not decoded:
            continue
        for idx in vin_to_indexes[vin]:
            out[idx] = _merge_marketcheck_fields(out[idx], decoded)
    return out
