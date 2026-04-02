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

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_cache_conn: sqlite3.Connection | None = None
_cache_db_path: str | None = None

_FAMILY_INVENTORY_PLATFORMS = {
    "ford_family_inventory",
    "gm_family_inventory",
    "honda_acura_inventory",
    "nissan_infiniti_inventory",
    "toyota_lexus_oem_inventory",
}
_MIN_CACHE_LISTINGS_FOR_FAMILY_STACK = 8


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


def _cache_payload_listing_count(payload: dict[str, Any]) -> int:
    listings = payload.get("listings")
    if not isinstance(listings, list):
        return 0
    return len(listings)


def _cache_payload_is_plausible(payload: dict[str, Any]) -> bool:
    platform_id = str(payload.get("platform_id") or "").strip()
    if platform_id not in _FAMILY_INVENTORY_PLATFORMS:
        return True
    return _cache_payload_listing_count(payload) >= _MIN_CACHE_LISTINGS_FOR_FAMILY_STACK


def get_cached_inventory_listings(key: str) -> dict[str, Any] | None:
    with _cache_lock:
        conn = _ensure_connection()
        if not conn:
            return None
        try:
            row = conn.execute("SELECT payload, expires_at FROM inv_cache WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            if time.time() > float(row[1]):
                conn.execute("DELETE FROM inv_cache WHERE key = ?", (key,))
                conn.commit()
                return None
            payload = json.loads(row[0])
            if not isinstance(payload, dict) or not _cache_payload_is_plausible(payload):
                return None
            return payload
        except Exception as e:
            logger.debug("Inventory cache read failed: %s", e)
            return None


def set_cached_inventory_listings(key: str, payload: dict[str, Any]) -> None:
    with _cache_lock:
        conn = _ensure_connection()
        if not conn:
            return
        if not _cache_payload_is_plausible(payload):
            logger.debug(
                "Skipping inventory cache write for partial family-stack payload: platform=%s listings=%s",
                payload.get("platform_id"),
                _cache_payload_listing_count(payload),
            )
            return
        exp = time.time() + max(60.0, float(settings.inventory_cache_ttl_seconds))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO inv_cache (key, payload, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(payload, default=str), exp),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Inventory cache write failed: %s", e)
