"""Persistent cache for dealer-domain platform detection and routing hints."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings

logger = logging.getLogger(__name__)


def normalize_dealer_domain(website: str) -> str:
    host = urlparse((website or "").strip()).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


@dataclass(slots=True)
class PlatformCacheEntry:
    domain: str
    platform_id: str
    confidence: float
    extraction_mode: str
    requires_render: bool
    inventory_url_hint: str | None
    detection_source: str
    last_verified_at: datetime
    failure_count: int = 0
    metadata: dict | None = None

    @property
    def is_stale(self) -> bool:
        ttl = timedelta(hours=max(1, settings.platform_cache_ttl_hours))
        return datetime.now(UTC) - self.last_verified_at > ttl

    @property
    def is_usable(self) -> bool:
        return not self.is_stale and self.failure_count < settings.platform_cache_failure_threshold


class PlatformStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.enabled = settings.platform_cache_enabled
        self.db_path = db_path or settings.platform_cache_path

    def _connect(self) -> sqlite3.Connection | None:
        if not self.enabled or not self.db_path:
            return None
        try:
            path = Path(self.db_path)
            if path.parent and not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            self._ensure_schema(conn)
            return conn
        except Exception as e:
            logger.warning("Platform cache disabled for %s: %s", self.db_path, e)
            self.enabled = False
            return None

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dealer_platform_cache (
                domain TEXT PRIMARY KEY,
                platform_id TEXT NOT NULL,
                confidence REAL NOT NULL,
                extraction_mode TEXT NOT NULL,
                requires_render INTEGER NOT NULL DEFAULT 0,
                inventory_url_hint TEXT,
                detection_source TEXT NOT NULL,
                last_verified_at TEXT NOT NULL,
                failure_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.commit()

    def get(self, domain: str) -> PlatformCacheEntry | None:
        if not domain:
            return None
        conn = self._connect()
        if not conn:
            return None
        try:
            row = conn.execute(
                """
                SELECT domain, platform_id, confidence, extraction_mode, requires_render,
                       inventory_url_hint, detection_source, last_verified_at, failure_count,
                       metadata_json
                FROM dealer_platform_cache
                WHERE domain = ?
                """,
                (domain,),
            ).fetchone()
            if not row:
                return None
            return PlatformCacheEntry(
                domain=row["domain"],
                platform_id=row["platform_id"],
                confidence=float(row["confidence"]),
                extraction_mode=row["extraction_mode"],
                requires_render=bool(row["requires_render"]),
                inventory_url_hint=row["inventory_url_hint"],
                detection_source=row["detection_source"],
                last_verified_at=datetime.fromisoformat(row["last_verified_at"]),
                failure_count=int(row["failure_count"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
        except Exception as e:
            logger.debug("Platform cache get failed for %s: %s", domain, e)
            return None
        finally:
            conn.close()

    def upsert(
        self,
        *,
        domain: str,
        platform_id: str,
        confidence: float,
        extraction_mode: str,
        requires_render: bool,
        detection_source: str,
        inventory_url_hint: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if not domain or not platform_id:
            return
        conn = self._connect()
        if not conn:
            return
        try:
            conn.execute(
                """
                INSERT INTO dealer_platform_cache (
                    domain, platform_id, confidence, extraction_mode, requires_render,
                    inventory_url_hint, detection_source, last_verified_at, failure_count,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    platform_id = excluded.platform_id,
                    confidence = excluded.confidence,
                    extraction_mode = excluded.extraction_mode,
                    requires_render = excluded.requires_render,
                    inventory_url_hint = COALESCE(excluded.inventory_url_hint, dealer_platform_cache.inventory_url_hint),
                    detection_source = excluded.detection_source,
                    last_verified_at = excluded.last_verified_at,
                    failure_count = 0,
                    metadata_json = excluded.metadata_json
                """,
                (
                    domain,
                    platform_id,
                    float(confidence),
                    extraction_mode,
                    int(requires_render),
                    inventory_url_hint,
                    detection_source,
                    datetime.now(UTC).isoformat(),
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Platform cache upsert failed for %s: %s", domain, e)
        finally:
            conn.close()

    def record_failure(self, domain: str) -> None:
        if not domain:
            return
        conn = self._connect()
        if not conn:
            return
        try:
            conn.execute(
                """
                UPDATE dealer_platform_cache
                SET failure_count = failure_count + 1
                WHERE domain = ?
                """,
                (domain,),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Platform cache failure update failed for %s: %s", domain, e)
        finally:
            conn.close()


platform_store = PlatformStore()
