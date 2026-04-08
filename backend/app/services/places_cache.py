"""SQLite cache for Places search, detail, and geocode lookups."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from typing import Any

from app.config import settings
from app.schemas import DealershipFound
from app.services.kv_rest import kv_rest_store

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_cache_conn: sqlite3.Connection | None = None
_cache_db_path: str | None = None
KV_KEY_PREFIX = "motorscrape:places:v1:"


def _ensure_connection() -> sqlite3.Connection | None:
    global _cache_conn, _cache_db_path
    if not settings.places_cache_enabled:
        return None
    path = (settings.places_cache_path or "").strip()
    if not path:
        return None
    if _cache_conn is not None and _cache_db_path != path:
        try:
            _cache_conn.close()
        except Exception:
            pass
        _cache_conn = None
        _cache_db_path = None
    if _cache_conn is None:
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS places_cache (
                namespace TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                payload TEXT NOT NULL,
                expires_at REAL NOT NULL,
                PRIMARY KEY (namespace, cache_key)
            )
            """
        )
        _cache_conn = conn
        _cache_db_path = path
    return _cache_conn


def _make_key(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _normalize_cache_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _use_kv() -> bool:
    return bool(settings.places_cache_enabled and kv_rest_store.enabled())


def _kv_key(namespace: str, cache_key: str) -> str:
    return f"{KV_KEY_PREFIX}{namespace}:{cache_key}"


def _get(namespace: str, cache_key: str) -> Any | None:
    if _use_kv():
        try:
            return kv_rest_store.get_json(_kv_key(namespace, cache_key))
        except Exception as exc:
            logger.debug("Places KV cache read failed for %s: %s", namespace, exc)
            return None
    with _cache_lock:
        conn = _ensure_connection()
        if not conn:
            return None
        try:
            row = conn.execute(
                "SELECT payload, expires_at FROM places_cache WHERE namespace = ? AND cache_key = ?",
                (namespace, cache_key),
            ).fetchone()
            if not row:
                return None
            if time.time() > float(row[1]):
                conn.execute(
                    "DELETE FROM places_cache WHERE namespace = ? AND cache_key = ?",
                    (namespace, cache_key),
                )
                conn.commit()
                return None
            return json.loads(str(row[0]))
        except Exception as exc:
            logger.debug("Places cache read failed for %s: %s", namespace, exc)
            return None


def _set(namespace: str, cache_key: str, payload: Any, ttl_seconds: int) -> None:
    if _use_kv():
        try:
            kv_rest_store.set_json(_kv_key(namespace, cache_key), payload, ttl_seconds=max(60, int(ttl_seconds or 0)))
        except Exception as exc:
            logger.debug("Places KV cache write failed for %s: %s", namespace, exc)
        return
    with _cache_lock:
        conn = _ensure_connection()
        if not conn:
            return
        expires_at = time.time() + max(60, int(ttl_seconds or 0))
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO places_cache (namespace, cache_key, payload, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (namespace, cache_key, json.dumps(payload, default=str), expires_at),
            )
            conn.commit()
        except Exception as exc:
            logger.debug("Places cache write failed for %s: %s", namespace, exc)


def places_search_cache_key(
    *,
    location: str,
    make: str,
    model: str,
    vehicle_category: str,
    radius_miles: int,
    market_region: str,
    prefer_small_dealers: bool = False,
) -> str:
    return _make_key(
        {
            "namespace": "places_search_v2",
            "location": _normalize_cache_text(location),
            "make": _normalize_cache_text(make),
            "model": _normalize_cache_text(model),
            "vehicle_category": _normalize_cache_text(vehicle_category or "car") or "car",
            "radius_miles": int(radius_miles or 0),
            "market_region": _normalize_cache_text(market_region or "us") or "us",
            "prefer_small_dealers": bool(prefer_small_dealers),
        }
    )


def get_cached_places_search(key: str) -> list[DealershipFound] | None:
    payload = _get("search", key)
    if not isinstance(payload, list):
        return None
    cached: list[DealershipFound] = []
    for item in payload:
        if not isinstance(item, dict):
            return None
        try:
            cached.append(DealershipFound.model_validate(item))
        except Exception:
            return None
    return cached


def set_cached_places_search(key: str, results: list[DealershipFound], *, ttl_seconds: int | None = None) -> None:
    payload = [item.model_dump(mode="json") for item in results]
    ttl = ttl_seconds
    if ttl is None:
        ttl = (
            settings.places_search_cache_ttl_seconds
            if results
            else max(60, int(getattr(settings, "places_search_empty_cache_ttl_seconds", 60 * 60 * 6) or 0))
        )
    _set("search", key, payload, ttl)


def get_cached_place_website(place_resource_name: str) -> str | None:
    payload = _get("details", place_resource_name.strip())
    if not isinstance(payload, dict):
        return None
    value = payload.get("website")
    return str(value) if isinstance(value, str) else None


def set_cached_place_website(place_resource_name: str, website: str | None) -> None:
    _set(
        "details",
        place_resource_name.strip(),
        {"website": (website or "").strip()},
        settings.places_details_cache_ttl_seconds,
    )


def geocode_cache_key(location: str) -> str:
    return _make_key({"namespace": "places_geocode_v1", "location": _normalize_cache_text(location)})


def get_cached_geocode_center(location: str) -> tuple[float, float] | None:
    payload = _get("geocode", geocode_cache_key(location))
    if not isinstance(payload, dict):
        return None
    try:
        lat = float(payload["lat"])
        lng = float(payload["lng"])
    except Exception:
        return None
    return (lat, lng)


def set_cached_geocode_center(location: str, center: tuple[float, float] | None) -> None:
    if center is None:
        return
    _set(
        "geocode",
        geocode_cache_key(location),
        {"lat": float(center[0]), "lng": float(center[1])},
        settings.places_geocode_cache_ttl_seconds,
    )
