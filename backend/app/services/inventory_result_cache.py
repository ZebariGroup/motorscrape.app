"""SQLite cache for per-dealership listing payloads (reduces repeat scrape cost)."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from typing import Any

from app.config import settings
from app.services.kv_rest import kv_rest_store

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_cache_conn: sqlite3.Connection | None = None
_cache_db_path: str | None = None
KV_KEY_PREFIX = "motorscrape:inventory:v1:"

_FAMILY_INVENTORY_PLATFORMS = {
    "ford_family_inventory",
    "gm_family_inventory",
    "honda_acura_inventory",
    "nissan_infiniti_inventory",
    "toyota_lexus_oem_inventory",
}
_MIN_CACHE_LISTINGS_FOR_FAMILY_STACK = 8
_CACHE_META_KEYS = {"_cache_cached_at", "_cache_is_stale", "_cache_expires_at"}


def inventory_listings_cache_key(
    *,
    website: str,
    domain: str,
    make: str,
    model: str,
    vehicle_category: str,
    vehicle_condition: str,
    inventory_scope: str,
    max_pages: int,
) -> str:
    make_norm = (make or "").strip().lower()
    category_norm = (vehicle_category or "car").strip().lower() or "car"
    # v2 includes vehicle_category in the key to prevent cross-category stale payload reuse.
    namespace = "harley_v3" if "harley" in make_norm else "v2"
    payload = json.dumps(
        {
            "namespace": namespace,
            "website": (website or "").strip().rstrip("/").lower(),
            "domain": (domain or "").strip().lower(),
            "make": make_norm,
            "model": (model or "").strip().lower(),
            "vehicle_category": category_norm,
            "vehicle_condition": (vehicle_condition or "all").strip().lower(),
            "inventory_scope": (inventory_scope or "all").strip().lower(),
            "max_pages": int(max_pages),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _ensure_connection() -> sqlite3.Connection | None:
    """Return a process-wide connection (thread-safe via _cache_lock)."""
    global _cache_conn, _cache_db_path
    if not settings.inventory_cache_enabled:
        return None
    path = (settings.inventory_cache_path or "").strip()
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
            "CREATE TABLE IF NOT EXISTS inv_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL)"
        )
        _cache_conn = conn
        _cache_db_path = path
    return _cache_conn


def _use_kv() -> bool:
    return bool(settings.inventory_cache_enabled and kv_rest_store.enabled())


def _kv_key(key: str) -> str:
    return f"{KV_KEY_PREFIX}{key}"


def _cache_payload_listing_count(payload: dict[str, Any]) -> int:
    listings = payload.get("listings")
    if not isinstance(listings, list):
        return 0
    return len(listings)


def _fresh_ttl_seconds() -> float:
    return max(60.0, float(getattr(settings, "inventory_cache_ttl_seconds", 0) or 0))


def _stale_window_seconds() -> float:
    return max(0.0, float(getattr(settings, "inventory_cache_stale_revalidate_seconds", 0) or 0))


def _strip_cache_meta(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _CACHE_META_KEYS}


def _annotate_cache_payload(payload: dict[str, Any], *, cached_at: float, expires_at: float) -> dict[str, Any]:
    fresh_until = float(cached_at) + _fresh_ttl_seconds()
    is_stale = time.time() > fresh_until
    annotated = _strip_cache_meta(payload)
    annotated["_cache_cached_at"] = float(cached_at)
    annotated["_cache_is_stale"] = is_stale
    annotated["_cache_expires_at"] = float(expires_at)
    return annotated


def _cache_payload_is_plausible(payload: dict[str, Any]) -> bool:
    platform_id = str(payload.get("platform_id") or "").strip()
    if platform_id not in _FAMILY_INVENTORY_PLATFORMS:
        return True
    return _cache_payload_listing_count(payload) >= _MIN_CACHE_LISTINGS_FOR_FAMILY_STACK


def get_inventory_cache_entry(key: str, *, allow_stale: bool = False) -> dict[str, Any] | None:
    if _use_kv():
        try:
            payload = kv_rest_store.get_json(_kv_key(key))
            if not isinstance(payload, dict) or not _cache_payload_is_plausible(payload):
                return None
            cached_at = float(payload.get("_cache_cached_at") or time.time())
            expires_at = cached_at + _fresh_ttl_seconds() + _stale_window_seconds()
            entry = _annotate_cache_payload(payload, cached_at=cached_at, expires_at=expires_at)
            if entry["_cache_is_stale"] and not allow_stale:
                return None
            return entry
        except Exception as e:
            logger.debug("Inventory KV cache read failed: %s", e)
            return None
    with _cache_lock:
        conn = _ensure_connection()
        if not conn:
            return None
        try:
            row = conn.execute("SELECT payload, expires_at FROM inv_cache WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            expires_at = float(row[1])
            if time.time() > expires_at:
                conn.execute("DELETE FROM inv_cache WHERE key = ?", (key,))
                conn.commit()
                return None
            payload = json.loads(row[0])
            if not isinstance(payload, dict) or not _cache_payload_is_plausible(payload):
                return None
            cached_at = float(payload.get("_cache_cached_at") or max(0.0, expires_at - _fresh_ttl_seconds()))
            entry = _annotate_cache_payload(payload, cached_at=cached_at, expires_at=expires_at)
            if entry["_cache_is_stale"] and not allow_stale:
                return None
            return entry
        except Exception as e:
            logger.debug("Inventory cache read failed: %s", e)
            return None


def get_cached_inventory_listings(key: str) -> dict[str, Any] | None:
    entry = get_inventory_cache_entry(key)
    if not entry:
        return None
    return _strip_cache_meta(entry)


def set_cached_inventory_listings(key: str, payload: dict[str, Any]) -> None:
    fresh_ttl = _fresh_ttl_seconds()
    stale_window = _stale_window_seconds()
    cached_at = time.time()
    payload_to_store = _strip_cache_meta(payload)
    payload_to_store["_cache_cached_at"] = cached_at
    if _use_kv():
        if not _cache_payload_is_plausible(payload_to_store):
            logger.debug(
                "Skipping inventory KV cache write for partial family-stack payload: platform=%s listings=%s",
                payload_to_store.get("platform_id"),
                _cache_payload_listing_count(payload_to_store),
            )
            return
        try:
            kv_rest_store.set_json(
                _kv_key(key),
                payload_to_store,
                ttl_seconds=max(60, int(fresh_ttl + stale_window)),
            )
        except Exception as e:
            logger.debug("Inventory KV cache write failed: %s", e)
        return
    with _cache_lock:
        conn = _ensure_connection()
        if not conn:
            return
        if not _cache_payload_is_plausible(payload_to_store):
            logger.debug(
                "Skipping inventory cache write for partial family-stack payload: platform=%s listings=%s",
                payload_to_store.get("platform_id"),
                _cache_payload_listing_count(payload_to_store),
            )
            return
        exp = cached_at + fresh_ttl + stale_window
        try:
            conn.execute(
                "INSERT OR REPLACE INTO inv_cache (key, payload, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(payload_to_store, default=str), exp),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Inventory cache write failed: %s", e)
