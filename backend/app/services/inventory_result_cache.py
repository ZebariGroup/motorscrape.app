"""SQLite cache for per-dealership listing payloads (reduces repeat scrape cost)."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


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


def _connect() -> sqlite3.Connection | None:
    if not settings.inventory_cache_enabled:
        return None
    path = (settings.inventory_cache_path or "").strip()
    if not path:
        return None
    conn = sqlite3.connect(path, timeout=30)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS inv_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL)"
    )
    return conn


def get_cached_inventory_listings(key: str) -> dict[str, Any] | None:
    conn = _connect()
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
    finally:
        conn.close()


def set_cached_inventory_listings(key: str, payload: dict[str, Any]) -> None:
    conn = _connect()
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
    finally:
        conn.close()
