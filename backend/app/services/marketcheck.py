from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MARKETCHECK_DECODE_URL = "https://api.marketcheck.com/v2/decode/car/{vin}/specs"
MARKETCHECK_PREDICT_URL = "https://api.marketcheck.com/v2/predict/car/price"
MARKETCHECK_HISTORY_URL = "https://api.marketcheck.com/v2/history/car/{vin}"

_marketcheck_lock = asyncio.Lock()
_marketcheck_client: httpx.AsyncClient | None = None
_marketcheck_semaphore: asyncio.Semaphore | None = None
_cache_lock = asyncio.Lock()


@dataclass(slots=True)
class _CachedMarketcheckDetails:
    expires_at: float
    details: dict[str, Any] | None


_details_cache: dict[tuple[str, int | None], _CachedMarketcheckDetails] = {}


def _normalize_vin(vin: str) -> str:
    return vin.strip().upper()


def _normalize_miles(miles: int | None) -> int | None:
    if miles is None:
        return None
    miles_int = int(miles)
    return miles_int if miles_int > 0 else None


def _details_cache_key(vin: str, miles: int | None) -> tuple[str, int | None]:
    return (_normalize_vin(vin), _normalize_miles(miles))


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


def _extract_marketcheck_features(payload: dict[str, Any]) -> list[str]:
    raw_features = payload.get("installed_options")
    if not isinstance(raw_features, list):
        return []

    features: list[str] = []
    for raw in raw_features:
        if isinstance(raw, str):
            text = raw.strip()
        elif isinstance(raw, dict):
            text = str(
                raw.get("name")
                or raw.get("description")
                or raw.get("option")
                or raw.get("value")
                or ""
            ).strip()
        else:
            text = ""
        if text and text not in features:
            features.append(text)
    return features


def _parse_marketcheck_decode(payload: dict[str, Any]) -> dict[str, Any]:
    trim = payload.get("trim")
    return {
        "year": payload.get("year"),
        "make": payload.get("make"),
        "model": payload.get("model"),
        "marketcheck_trim": trim,
        "body_style": payload.get("body_type"),
        "vehicle_type": payload.get("vehicle_type"),
        "transmission": payload.get("transmission"),
        "drivetrain": payload.get("drivetrain"),
        "fuel_type": payload.get("fuel_type"),
        "engine": payload.get("engine"),
        "marketcheck_features": _extract_marketcheck_features(payload),
    }


def _compact_marketcheck_details(details: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in details.items():
        if value is None:
            continue
        if key != "marketcheck_features" and value == []:
            continue
        compact[key] = value
    if "marketcheck_features" not in compact and any(key != "marketcheck_features" for key in compact):
        compact["marketcheck_features"] = []
    return compact


async def fetch_marketcheck_details(vin: str, miles: int | None = None) -> dict[str, Any] | None:
    if not settings.marketcheck_api_key:
        return None

    normalized_vin = _normalize_vin(vin)
    if len(normalized_vin) != 17:
        return None

    normalized_miles = _normalize_miles(miles)
    cache_key = _details_cache_key(normalized_vin, normalized_miles)
    now = time.time()
    async with _cache_lock:
        cached = _details_cache.get(cache_key)
        if cached is not None and cached.expires_at > now:
            return cached.details

    client = await _get_client()
    semaphore = await _get_semaphore()
    details: dict[str, Any] = {}

    try:
        async with semaphore:
            decode_resp = await client.get(
                MARKETCHECK_DECODE_URL.format(vin=normalized_vin),
                params={"api_key": settings.marketcheck_api_key},
            )
            if decode_resp.status_code == 429:
                logger.info("Marketcheck decode rate limited for %s", normalized_vin)
            if decode_resp.status_code == 200:
                details.update(_parse_marketcheck_decode(decode_resp.json()))
            elif decode_resp.status_code >= 400 and decode_resp.status_code != 429:
                logger.debug("Marketcheck decode HTTP %s for %s", decode_resp.status_code, normalized_vin)

            if normalized_miles is not None and decode_resp.status_code != 429:
                predict_resp = await client.get(
                    MARKETCHECK_PREDICT_URL,
                    params={
                        "api_key": settings.marketcheck_api_key,
                        "vin": normalized_vin,
                        "miles": normalized_miles,
                        "car_type": "used",
                    },
                )
                if predict_resp.status_code == 429:
                    logger.info("Marketcheck predict rate limited for %s", normalized_vin)
                if predict_resp.status_code == 200:
                    predict_data = predict_resp.json()
                    predicted_price = predict_data.get("predicted_price")
                    if predicted_price is not None:
                        details["estimated_market_value"] = float(predicted_price)
                elif predict_resp.status_code >= 400 and predict_resp.status_code != 429:
                    logger.debug("Marketcheck predict HTTP %s for %s", predict_resp.status_code, normalized_vin)
    except Exception as exc:
        logger.debug("Marketcheck fetch failed for %s: %s", normalized_vin, exc)

    compact_details = _compact_marketcheck_details(details)
    if not compact_details:
        details_result = None
    else:
        details_result = {"vin": normalized_vin, **compact_details}

    async with _cache_lock:
        _details_cache[cache_key] = _CachedMarketcheckDetails(
            expires_at=now + max(60, int(settings.marketcheck_cache_ttl_seconds or 0)),
            details=details_result,
        )
    return details_result


async def fetch_premium_report(vin: str) -> list[dict[str, Any]] | None:
    """Fetch the historical listings for a VIN from Marketcheck's History API."""
    if not settings.marketcheck_api_key:
        return None

    normalized_vin = _normalize_vin(vin)
    if len(normalized_vin) != 17:
        return None

    client = await _get_client()
    try:
        response = await client.get(
            MARKETCHECK_HISTORY_URL.format(vin=normalized_vin),
            params={"api_key": settings.marketcheck_api_key},
        )
        if response.status_code == 429:
            logger.info("Marketcheck history rate limited for %s", normalized_vin)
        if response.status_code == 200:
            return response.json()
        if response.status_code >= 400 and response.status_code != 429:
            logger.debug("Marketcheck history HTTP %s for %s", response.status_code, normalized_vin)
    except Exception as exc:
        logger.error("Marketcheck history fetch failed for %s: %s", normalized_vin, exc)
    return None
