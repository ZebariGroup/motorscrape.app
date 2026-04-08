"""Persistent dealer scoring used to prioritize higher-quality inventory scrapes."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

NO_SCORE_DEFAULT = 50.0
_LISTINGS_CAP = 50
_FAST_SECONDS = 30.0
_SLOW_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class DealerScoreCard:
    score: float = NO_SCORE_DEFAULT
    failure_streak: int = 0
    last_elapsed_s: float | None = None


def _connect(db_path: str | None = None) -> sqlite3.Connection | None:
    path_str = (db_path or settings.platform_cache_path or "").strip()
    if not path_str:
        return None
    try:
        path = Path(path_str)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        return conn
    except Exception as e:
        logger.warning("Dealer score store disabled for %s: %s", path_str, e)
        return None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dealer_scores (
            domain TEXT PRIMARY KEY,
            score REAL NOT NULL DEFAULT 50.0,
            run_count INTEGER NOT NULL DEFAULT 0,
            last_run_at REAL NOT NULL,
            last_listings INTEGER,
            last_price_fill REAL,
            last_vin_fill REAL,
            last_elapsed_s REAL,
            failure_streak INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _listings_score(listings: int) -> float:
    capped = min(max(0, int(listings)), _LISTINGS_CAP)
    return (capped / _LISTINGS_CAP) * 100.0


def _speed_score(elapsed_s: float) -> float:
    elapsed = max(0.0, float(elapsed_s))
    if elapsed <= _FAST_SECONDS:
        return 100.0
    if elapsed >= _SLOW_SECONDS:
        return 0.0
    span = _SLOW_SECONDS - _FAST_SECONDS
    return ((max(0.0, _SLOW_SECONDS - elapsed)) / span) * 100.0


def compute_raw_score(
    *,
    listings: int,
    price_fill: float,
    vin_fill: float,
    elapsed_s: float,
    failed: bool = False,
) -> float:
    if failed:
        return 0.0
    price_fill_score = _clamp(float(price_fill), 0.0, 1.0) * 100.0
    vin_fill_score = _clamp(float(vin_fill), 0.0, 1.0) * 100.0
    raw = (
        (_listings_score(listings) * 0.40)
        + (price_fill_score * 0.25)
        + (vin_fill_score * 0.15)
        + (_speed_score(elapsed_s) * 0.20)
    )
    return _clamp(raw, 0.0, 100.0)


def record_scrape_outcome(
    domain: str,
    *,
    listings: int,
    price_fill: float,
    vin_fill: float,
    elapsed_s: float,
    failed: bool = False,
    db_path: str | None = None,
) -> None:
    if not domain:
        return
    conn = _connect(db_path=db_path)
    if not conn:
        return
    try:
        existing = conn.execute(
            """
            SELECT score, run_count, failure_streak
            FROM dealer_scores
            WHERE domain = ?
            """,
            (domain,),
        ).fetchone()
        alpha = _clamp(float(getattr(settings, "dealer_score_ema_alpha", 0.35)), 0.01, 1.0)
        raw_score = compute_raw_score(
            listings=listings,
            price_fill=price_fill,
            vin_fill=vin_fill,
            elapsed_s=elapsed_s,
            failed=failed,
        )
        if existing:
            prior_score = float(existing["score"])
            score = (alpha * raw_score) + ((1.0 - alpha) * prior_score)
            run_count = int(existing["run_count"]) + 1
            failure_streak = int(existing["failure_streak"]) + 1 if failed else 0
        else:
            score = raw_score
            run_count = 1
            failure_streak = 1 if failed else 0
        conn.execute(
            """
            INSERT INTO dealer_scores (
                domain, score, run_count, last_run_at, last_listings,
                last_price_fill, last_vin_fill, last_elapsed_s, failure_streak
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                score = excluded.score,
                run_count = excluded.run_count,
                last_run_at = excluded.last_run_at,
                last_listings = excluded.last_listings,
                last_price_fill = excluded.last_price_fill,
                last_vin_fill = excluded.last_vin_fill,
                last_elapsed_s = excluded.last_elapsed_s,
                failure_streak = excluded.failure_streak
            """,
            (
                domain,
                _clamp(score, 0.0, 100.0),
                run_count,
                time.time(),
                max(0, int(listings)),
                _clamp(float(price_fill), 0.0, 1.0),
                _clamp(float(vin_fill), 0.0, 1.0),
                max(0.0, float(elapsed_s)),
                failure_streak,
            ),
        )
        conn.commit()
    except Exception as e:
        logger.debug("Dealer score upsert failed for %s: %s", domain, e)
    finally:
        conn.close()


def get_scores(domains: list[str], *, db_path: str | None = None) -> dict[str, float]:
    normalized_domains = [str(domain or "").strip() for domain in domains if str(domain or "").strip()]
    if not normalized_domains:
        return {}
    conn = _connect(db_path=db_path)
    if not conn:
        return {}
    try:
        placeholders = ",".join("?" for _ in normalized_domains)
        rows = conn.execute(
            f"""
            SELECT domain, score
            FROM dealer_scores
            WHERE domain IN ({placeholders})
            """,
            normalized_domains,
        ).fetchall()
        return {str(row["domain"]): float(row["score"]) for row in rows}
    except Exception as e:
        logger.debug("Dealer score lookup failed: %s", e)
        return {}
    finally:
        conn.close()


def get_score_cards(domains: list[str], *, db_path: str | None = None) -> dict[str, DealerScoreCard]:
    normalized_domains = [str(domain or "").strip() for domain in domains if str(domain or "").strip()]
    if not normalized_domains:
        return {}
    conn = _connect(db_path=db_path)
    if not conn:
        return {}
    try:
        placeholders = ",".join("?" for _ in normalized_domains)
        rows = conn.execute(
            f"""
            SELECT domain, score, failure_streak, last_elapsed_s
            FROM dealer_scores
            WHERE domain IN ({placeholders})
            """,
            normalized_domains,
        ).fetchall()
        return {
            str(row["domain"]): DealerScoreCard(
                score=float(row["score"]),
                failure_streak=int(row["failure_streak"] or 0),
                last_elapsed_s=float(row["last_elapsed_s"]) if row["last_elapsed_s"] is not None else None,
            )
            for row in rows
        }
    except Exception as e:
        logger.debug("Dealer score-card lookup failed: %s", e)
        return {}
    finally:
        conn.close()
