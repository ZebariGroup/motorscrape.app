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

MARKETCHECK_DECODE_URL = "https://api.marketcheck.com/v2/decode/car/{vin}/specs"
MARKETCHECK_PREDICT_URL = "https://api.marketcheck.com/v2/predict/car/price"

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

def _parse_marketcheck_decode(payload: dict[str, Any]) -> dict[str, Any]:
    trim = payload.get("trim")
    features = []
    # Marketcheck decode endpoint might return installed options/features
    if "installed_options" in payload and isinstance(payload["installed_options"], list):
        features = payload["installed_options"]
        
    return {
        "marketcheck_trim": trim,
        "marketcheck_features": features,
    }

async def _fetch_marketcheck_data(vin: str, miles: int | None) -> dict[str, Any] | None:
    if not settings.marketcheck_api_key:
        return None
        
    now = time.time()
    async with _cache_lock:
        cached = _decode_cache.get(vin)
        if cached is not None and cached.expires_at > now:
            return cached.decoded

    client = await _get_client()
    semaphore = await _get_semaphore()
    decoded: dict[str, Any] = {}
    
    try:
        async with semaphore:
            # 1. Decode VIN for exact trim
            decode_resp = await client.get(
                MARKETCHECK_DECODE_URL.format(vin=vin),
                params={"api_key": settings.marketcheck_api_key}
            )
            if decode_resp.status_code == 200:
                decoded.update(_parse_marketcheck_decode(decode_resp.json()))
                
            # 2. Predict Price (Estimated Market Value) if we have miles
            if miles is not None and miles > 0:
                predict_resp = await client.get(
                    MARKETCHECK_PREDICT_URL,
                    params={
                        "api_key": settings.marketcheck_api_key,
                        "vin": vin,
                        "miles": miles,
                        "car_type": "used"
                    }
                )
                if predict_resp.status_code == 200:
                    predict_data = predict_resp.json()
                    predicted_price = predict_data.get("predicted_price")
                    if predicted_price:
                        decoded["estimated_market_value"] = float(predicted_price)
                        
    except Exception as exc:
        logger.debug("Marketcheck fetch failed for %s: %s", vin, exc)

    if not any(value for value in decoded.values() if value is not None and value != []):
        decoded_result = None
    else:
        decoded_result = decoded

    async with _cache_lock:
        _decode_cache[vin] = _CachedMarketcheck(
            expires_at=now + max(60, int(settings.marketcheck_cache_ttl_seconds or 0)),
            decoded=decoded_result,
        )
    return decoded_result

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
    vin_to_miles: dict[str, int | None] = {}
    for idx, listing in enumerate(listings):
        vin = listing.vin or listing.vehicle_identifier
        if not vin or len(vin) != 17:
            continue
        vin_to_indexes.setdefault(vin, []).append(idx)
        # Grab miles if available (usage_value if unit is miles, or fallback to mileage)
        miles = None
        if listing.usage_unit == "miles" and listing.usage_value:
            miles = listing.usage_value
        elif listing.mileage:
            miles = listing.mileage
        vin_to_miles[vin] = miles

    if not vin_to_indexes:
        return listings

    decoded_rows = await asyncio.gather(*[_fetch_marketcheck_data(vin, vin_to_miles[vin]) for vin in vin_to_indexes])
    out = list(listings)
    for vin, decoded in zip(vin_to_indexes, decoded_rows, strict=False):
        if not decoded:
            continue
        for idx in vin_to_indexes[vin]:
            out[idx] = _merge_marketcheck_fields(out[idx], decoded)
    return out
