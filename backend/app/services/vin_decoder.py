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

VPIC_DECODE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/{vin}"
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

_vin_decoder_lock = asyncio.Lock()
_vin_decoder_client: httpx.AsyncClient | None = None
_vin_decoder_semaphore: asyncio.Semaphore | None = None
_cache_lock = asyncio.Lock()


@dataclass(slots=True)
class _CachedDecode:
    expires_at: float
    decoded: dict[str, Any] | None


_decode_cache: dict[str, _CachedDecode] = {}


def _normalize_vin(value: str | None) -> str | None:
    raw = (value or "").strip().upper()
    if _VIN_RE.fullmatch(raw):
        return raw
    return None


def _vehicle_vin(listing: VehicleListing) -> str | None:
    return _normalize_vin(listing.vin) or _normalize_vin(listing.vehicle_identifier)


async def _get_client() -> httpx.AsyncClient:
    global _vin_decoder_client
    if _vin_decoder_client is None:
        async with _vin_decoder_lock:
            if _vin_decoder_client is None:
                _vin_decoder_client = httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=httpx.Timeout(settings.vin_decoder_timeout),
                )
    return _vin_decoder_client


async def _get_semaphore() -> asyncio.Semaphore:
    global _vin_decoder_semaphore
    if _vin_decoder_semaphore is None:
        async with _vin_decoder_lock:
            if _vin_decoder_semaphore is None:
                _vin_decoder_semaphore = asyncio.Semaphore(max(1, int(settings.vin_decoder_max_concurrency or 1)))
    return _vin_decoder_semaphore


async def close_vin_decoder_http_client() -> None:
    global _vin_decoder_client
    async with _vin_decoder_lock:
        if _vin_decoder_client is not None:
            await _vin_decoder_client.aclose()
            _vin_decoder_client = None


def _clean_field(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text in {"0", "Not Applicable"}:
        return None
    return text


def _build_engine_label(row: dict[str, Any]) -> str | None:
    displacement_l = _clean_field(row.get("DisplacementL"))
    cylinders = _clean_field(row.get("EngineCylinders"))
    if displacement_l and cylinders:
        return f"{displacement_l}L {cylinders}-cyl"
    if displacement_l:
        return f"{displacement_l}L"
    if cylinders:
        return f"{cylinders}-cyl"
    return None


def _parse_decoded_row(vin: str, row: dict[str, Any]) -> dict[str, Any] | None:
    make = _clean_field(row.get("Make"))
    model = _clean_field(row.get("Model"))
    model_year = _clean_field(row.get("ModelYear"))
    trim = _clean_field(row.get("Trim")) or _clean_field(row.get("Series"))
    body_style = _clean_field(row.get("BodyClass"))
    drivetrain = _clean_field(row.get("DriveType"))
    fuel_type = _clean_field(row.get("FuelTypePrimary"))
    transmission = _clean_field(row.get("TransmissionStyle"))
    engine = _build_engine_label(row)

    year_value: int | None = None
    if model_year and model_year.isdigit():
        year_candidate = int(model_year)
        if 1900 <= year_candidate <= 2100:
            year_value = year_candidate

    decoded = {
        "vin": vin,
        "vehicle_identifier": vin,
        "make": make,
        "model": model,
        "year": year_value,
        "trim": trim,
        "body_style": body_style,
        "drivetrain": drivetrain,
        "engine": engine,
        "transmission": transmission,
        "fuel_type": fuel_type,
    }
    if not any(value for key, value in decoded.items() if key not in {"vin", "vehicle_identifier"}):
        return None
    return decoded


async def _decode_vin(vin: str) -> dict[str, Any] | None:
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
            response = await client.get(VPIC_DECODE_URL.format(vin=vin), params={"format": "json"})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.debug("VIN decode failed for %s: %s", vin, exc)
        payload = {}

    results = payload.get("Results") if isinstance(payload, dict) else None
    if isinstance(results, list) and results:
        first_row = results[0]
        if isinstance(first_row, dict):
            decoded = _parse_decoded_row(vin, first_row)

    async with _cache_lock:
        _decode_cache[vin] = _CachedDecode(
            expires_at=now + max(60, int(settings.vin_decoder_cache_ttl_seconds or 0)),
            decoded=decoded,
        )
    return decoded


def _merge_decoded_fields(listing: VehicleListing, decoded: dict[str, Any]) -> VehicleListing:
    update: dict[str, Any] = {}
    if not listing.vin and decoded.get("vin"):
        update["vin"] = decoded["vin"]
    if not listing.vehicle_identifier and decoded.get("vehicle_identifier"):
        update["vehicle_identifier"] = decoded["vehicle_identifier"]
    if not listing.make and decoded.get("make"):
        update["make"] = decoded["make"]
    if not listing.model and decoded.get("model"):
        update["model"] = decoded["model"]
    if listing.year is None and decoded.get("year") is not None:
        update["year"] = decoded["year"]
    if not listing.trim and decoded.get("trim"):
        update["trim"] = decoded["trim"]
    if not listing.body_style and decoded.get("body_style"):
        update["body_style"] = decoded["body_style"]
    if not listing.drivetrain and decoded.get("drivetrain"):
        update["drivetrain"] = decoded["drivetrain"]
    if not listing.engine and decoded.get("engine"):
        update["engine"] = decoded["engine"]
    if not listing.transmission and decoded.get("transmission"):
        update["transmission"] = decoded["transmission"]
    if not listing.fuel_type and decoded.get("fuel_type"):
        update["fuel_type"] = decoded["fuel_type"]
    if not update:
        return listing
    return listing.model_copy(update=update)


async def enrich_vehicle_listings_with_vin_data(listings: list[VehicleListing]) -> list[VehicleListing]:
    if not settings.vin_decoder_enabled or not listings:
        return listings

    vin_to_indexes: dict[str, list[int]] = {}
    for idx, listing in enumerate(listings):
        vin = _vehicle_vin(listing)
        if vin is None:
            continue
        vin_to_indexes.setdefault(vin, []).append(idx)

    if not vin_to_indexes:
        return listings

    decoded_rows = await asyncio.gather(*[_decode_vin(vin) for vin in vin_to_indexes])
    out = list(listings)
    for vin, decoded in zip(vin_to_indexes, decoded_rows, strict=False):
        if not decoded:
            continue
        for idx in vin_to_indexes[vin]:
            out[idx] = _merge_decoded_fields(out[idx], decoded)
    return out
