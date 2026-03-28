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


def inventory_listings_cache_key(
    *,
    website: str,
    domain: str,
    make: str,
    model: str,
    vehicle_condition: str,
    inventory_scope: str,
    max_pages: int,
) -> str:
    payload = json.dumps(
        {
            "website": (website or "").strip().rstrip("/").lower(),
            "domain": (domain or "").strip().lower(),
            "make": (make or "").strip().lower(),
            "model": (model or "").strip().lower(),
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
            return json.loads(row[0])
        except Exception as e:
            logger.debug("Inventory cache read failed: %s", e)
            return None


def set_cached_inventory_listings(key: str, payload: dict[str, Any]) -> None:
    with _cache_lock:
        conn = _ensure_connection()
        if not conn:
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
