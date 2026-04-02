from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.schemas import VehicleListing

logger = logging.getLogger(__name__)

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

_client_lock = asyncio.Lock()
_cache_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None
_semaphore: asyncio.Semaphore | None = None


@dataclass(slots=True)
class _CachedValuation:
    expires_at: float
    payload: dict[str, Any] | None


_valuation_cache: dict[str, _CachedValuation] = {}


def _normalize_vin(value: str | None) -> str | None:
    raw = (value or "").strip().upper()
    if _VIN_RE.fullmatch(raw):
        return raw
    return None


def _listing_vin(listing: VehicleListing) -> str | None:
    return _normalize_vin(listing.vin) or _normalize_vin(listing.vehicle_identifier)


def _configured() -> bool:
    template = (settings.black_book_vin_url_template or "").strip()
    if "{vin}" not in template:
        return False
    return bool(settings.black_book_enabled and settings.black_book_api_key and template)


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=httpx.Timeout(settings.black_book_timeout),
                )
    return _client


async def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        async with _client_lock:
            if _semaphore is None:
                _semaphore = asyncio.Semaphore(max(1, int(settings.black_book_max_concurrency or 1)))
    return _semaphore


async def close_black_book_http_client() -> None:
    global _client
    async with _client_lock:
        if _client is not None:
            await _client.aclose()
            _client = None


def _pull_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            nested = _pull_number(value, keys)
            if nested is not None:
                return nested
        try:
            if value is None:
                continue
            number = float(value)
            if number > 0:
                return number
        except (TypeError, ValueError):
            continue
    return None


def _pull_any_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item
    return {}


def _normalize_confidence(raw: float | None) -> float | None:
    if raw is None:
        return None
    if raw > 1.0:
        raw = raw / 100.0
    return max(0.0, min(1.0, raw))


def _parse_black_book_payload(vin: str, payload: Any) -> dict[str, Any] | None:
    data = _pull_any_dict(payload)
    if not data:
        return None
    retail = _pull_number(
        data,
        (
            "retailValue",
            "retail_value",
            "cleanRetail",
            "clean_retail",
            "retail",
            "valueRetail",
        ),
    )
    trade_in = _pull_number(
        data,
        (
            "tradeInValue",
            "trade_in_value",
            "tradeValue",
            "trade_value",
            "trade",
            "wholesale",
        ),
    )
    range_low = _pull_number(data, ("rangeLow", "range_low", "low", "lowerBound", "valueLow"))
    range_high = _pull_number(data, ("rangeHigh", "range_high", "high", "upperBound", "valueHigh"))
    confidence_raw = _pull_number(data, ("confidence", "confidenceScore", "score", "matchConfidence"))
    confidence = _normalize_confidence(confidence_raw)

    if retail is None and trade_in is None and range_low is None and range_high is None:
        return None
    return {
        "vin": vin,
        "provider": "black_book",
        "external_retail_value": retail,
        "external_trade_in_value": trade_in,
        "external_valuation_range_low": range_low,
        "external_valuation_range_high": range_high,
        "external_valuation_confidence": confidence,
    }


async def _lookup_black_book(vin: str) -> dict[str, Any] | None:
    if not _configured():
        return None
    now = time.time()
    async with _cache_lock:
        cached = _valuation_cache.get(vin)
        if cached is not None and cached.expires_at > now:
            return cached.payload

    template = settings.black_book_vin_url_template.strip()
    url = template.replace("{vin}", vin)
    headers = {settings.black_book_auth_header or "X-API-Key": settings.black_book_api_key}
    client = await _get_client()
    semaphore = await _get_semaphore()
    payload: Any = None
    try:
        async with semaphore:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.debug("Black Book lookup failed for %s: %s", vin, exc)

    parsed = _parse_black_book_payload(vin, payload)
    async with _cache_lock:
        _valuation_cache[vin] = _CachedValuation(
            expires_at=now + max(300, int(settings.black_book_cache_ttl_seconds or 0)),
            payload=parsed,
        )
    return parsed


def _merge_external_valuation(listing: VehicleListing, valuation: dict[str, Any]) -> VehicleListing:
    update: dict[str, Any] = {"external_valuation_provider": valuation.get("provider") or "black_book"}
    for key in (
        "external_retail_value",
        "external_trade_in_value",
        "external_valuation_range_low",
        "external_valuation_range_high",
        "external_valuation_confidence",
    ):
        value = valuation.get(key)
        if value is not None:
            update[key] = value
    return listing.model_copy(update=update)


async def enrich_vehicle_listings_with_black_book_values(listings: list[VehicleListing]) -> list[VehicleListing]:
    if not listings or not _configured():
        return listings
    vin_to_indexes: dict[str, list[int]] = {}
    for index, listing in enumerate(listings):
        vin = _listing_vin(listing)
        if vin is None:
            continue
        vin_to_indexes.setdefault(vin, []).append(index)
    if not vin_to_indexes:
        return listings

    lookups = await asyncio.gather(*[_lookup_black_book(vin) for vin in vin_to_indexes])
    out = list(listings)
    for vin, valuation in zip(vin_to_indexes, lookups, strict=False):
        if not valuation:
            continue
        for idx in vin_to_indexes[vin]:
            out[idx] = _merge_external_valuation(out[idx], valuation)
    return out
