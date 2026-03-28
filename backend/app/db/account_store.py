"""User accounts, monthly usage, anonymous usage, and Stripe linkage."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from passlib.context import CryptContext

from app.config import settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

_schema = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    stripe_metered_item_id TEXT,
    entitlements_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_monthly (
    user_id INTEGER NOT NULL,
    period TEXT NOT NULL,
    search_count INTEGER NOT NULL DEFAULT 0,
    overage_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, period),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS anon_usage (
    anon_key TEXT PRIMARY KEY,
    search_count INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_buckets (
    bucket_key TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket_key, window_start)
);

CREATE TABLE IF NOT EXISTS alert_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    criteria_json TEXT NOT NULL,
    cadence TEXT NOT NULL,
    day_of_week INTEGER,
    hour_local INTEGER NOT NULL,
    timezone TEXT NOT NULL,
    deliver_csv INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    next_run_at REAL NOT NULL,
    last_run_at REAL,
    last_run_status TEXT,
    last_result_count INTEGER,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alert_subscriptions_user_id
ON alert_subscriptions (user_id, is_active, next_run_at);

CREATE TABLE IF NOT EXISTS alert_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    trigger_source TEXT NOT NULL,
    status TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    emailed INTEGER NOT NULL DEFAULT 0,
    csv_attached INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    summary_json TEXT,
    started_at REAL NOT NULL,
    completed_at REAL,
    FOREIGN KEY (subscription_id) REFERENCES alert_subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alert_runs_user_id
ON alert_runs (user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id TEXT NOT NULL,
    user_id INTEGER,
    anon_key TEXT,
    trigger_source TEXT NOT NULL,
    status TEXT NOT NULL,
    location TEXT NOT NULL,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    vehicle_category TEXT NOT NULL,
    vehicle_condition TEXT NOT NULL,
    inventory_scope TEXT NOT NULL,
    radius_miles INTEGER NOT NULL,
    requested_max_dealerships INTEGER,
    requested_max_pages_per_dealer INTEGER,
    result_count INTEGER NOT NULL DEFAULT 0,
    dealer_discovery_count INTEGER,
    dealer_deduped_count INTEGER,
    dealerships_attempted INTEGER NOT NULL DEFAULT 0,
    dealerships_succeeded INTEGER NOT NULL DEFAULT 0,
    dealerships_failed INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    economics_json TEXT NOT NULL DEFAULT '{}',
    started_at REAL NOT NULL,
    completed_at REAL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_user_id
ON scrape_runs (user_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_anon_key
ON scrape_runs (anon_key, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_correlation_id
ON scrape_runs (correlation_id);

CREATE TABLE IF NOT EXISTS scrape_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrape_run_id INTEGER NOT NULL,
    correlation_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    phase TEXT,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    dealership_name TEXT,
    dealership_website TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scrape_events_run_id
ON scrape_events (scrape_run_id, sequence_no ASC);
"""

_lock = threading.Lock()


def _connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    with _lock:
        conn = _connect(path)
        try:
            conn.executescript(_schema)
            conn.commit()
        finally:
            conn.close()


@dataclass(slots=True)
class UserRecord:
    id: str
    email: str
    tier: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_metered_item_id: str | None
    entitlements: dict[str, Any]


@dataclass(slots=True)
class AlertSubscriptionRecord:
    id: str
    user_id: str
    name: str
    criteria: dict[str, Any]
    cadence: str
    day_of_week: int | None
    hour_local: int
    timezone: str
    deliver_csv: bool
    is_active: bool
    next_run_at: float
    last_run_at: float | None
    last_run_status: str | None
    last_result_count: int | None
    last_error: str | None
    created_at: float
    updated_at: float


@dataclass(slots=True)
class AlertRunRecord:
    id: str
    subscription_id: str
    user_id: str
    trigger_source: str
    status: str
    result_count: int
    emailed: bool
    csv_attached: bool
    error_message: str | None
    summary: dict[str, Any]
    started_at: float
    completed_at: float | None


@dataclass(slots=True)
class ScrapeRunRecord:
    id: str
    correlation_id: str
    user_id: str | None
    anon_key: str | None
    trigger_source: str
    status: str
    location: str
    make: str
    model: str
    vehicle_category: str
    vehicle_condition: str
    inventory_scope: str
    radius_miles: int
    requested_max_dealerships: int | None
    requested_max_pages_per_dealer: int | None
    result_count: int
    dealer_discovery_count: int | None
    dealer_deduped_count: int | None
    dealerships_attempted: int
    dealerships_succeeded: int
    dealerships_failed: int
    error_count: int
    warning_count: int
    error_message: str | None
    summary: dict[str, Any]
    economics: dict[str, Any]
    started_at: float
    completed_at: float | None


@dataclass(slots=True)
class ScrapeEventRecord:
    id: str
    scrape_run_id: str
    correlation_id: str
    sequence_no: int
    event_type: str
    phase: str | None
    level: str
    message: str
    dealership_name: str | None
    dealership_website: str | None
    payload: dict[str, Any]
    created_at: float


class AccountStore:
    def __init__(self, path: str) -> None:
        self.path = path
        init_db(path)

    def _conn(self) -> sqlite3.Connection:
        return _connect(self.path)

    def create_user(self, email: str, password: str, *, tier: str = "free") -> UserRecord:
        email_n = email.strip().lower()
        ph = _pwd.hash(password)
        now = time.time()
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO users (email, password_hash, tier, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (email_n, ph, tier, now, now),
            )
            uid = int(cur.lastrowid)
            c.commit()
        return self.get_user_by_id(uid)  # type: ignore[return-value]

    def get_user_by_id(self, user_id: int | str) -> UserRecord | None:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT id, email, tier, stripe_customer_id, stripe_subscription_id,
                       stripe_metered_item_id, entitlements_json
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return _row_to_user(row)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT id, email, tier, stripe_customer_id, stripe_subscription_id,
                       stripe_metered_item_id, entitlements_json
                FROM users WHERE email = ? COLLATE NOCASE
                """,
                (email.strip().lower(),),
            ).fetchone()
        return _row_to_user(row)

    def verify_login(self, email: str, password: str) -> UserRecord | None:
        email_n = email.strip().lower()
        with self._conn() as c:
            row = c.execute(
                "SELECT id, password_hash FROM users WHERE email = ? COLLATE NOCASE",
                (email_n,),
            ).fetchone()
        if row is None:
            return None
        if not _pwd.verify(password, str(row["password_hash"])):
            return None
        return self.get_user_by_id(int(row["id"]))

    def update_password(self, user_id: int | str, new_password: str) -> None:
        ph = _pwd.hash(new_password)
        with self._conn() as c:
            c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (ph, user_id))
            c.commit()

    def set_tier(
        self,
        user_id: int | str,
        tier: str,
        *,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        stripe_metered_item_id: str | None = None,
    ) -> None:
        now = time.time()
        fields: list[str] = ["tier = ?", "updated_at = ?"]
        args: list[Any] = [tier, now]
        if stripe_customer_id is not None:
            fields.append("stripe_customer_id = ?")
            args.append(stripe_customer_id)
        if stripe_subscription_id is not None:
            fields.append("stripe_subscription_id = ?")
            args.append(stripe_subscription_id)
        if stripe_metered_item_id is not None:
            fields.append("stripe_metered_item_id = ?")
            args.append(stripe_metered_item_id)
        args.append(user_id)
        with self._conn() as c:
            c.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", args)
            c.commit()

    def set_metered_item(self, user_id: int | str, metered_item_id: str | None) -> None:
        now = time.time()
        with self._conn() as c:
            c.execute(
                "UPDATE users SET stripe_metered_item_id = ?, updated_at = ? WHERE id = ?",
                (metered_item_id, now, user_id),
            )
            c.commit()

    def monthly_usage(self, user_id: int | str, period: str) -> tuple[int, int]:
        """Returns (included_searches, overage_searches)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT search_count, overage_count FROM usage_monthly WHERE user_id = ? AND period = ?",
                (user_id, period),
            ).fetchone()
        if row is None:
            return (0, 0)
        return (int(row["search_count"]), int(row["overage_count"]))

    def increment_search_completed(
        self,
        user_id: int | str,
        period: str,
        *,
        counts_as_overage: bool,
    ) -> tuple[int, int]:
        """Increment included or overage counter; returns new (search_count, overage_count)."""
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO usage_monthly (user_id, period, search_count, overage_count)
                VALUES (?, ?, 0, 0)
                ON CONFLICT(user_id, period) DO NOTHING
                """,
                (user_id, period),
            )
            if counts_as_overage:
                c.execute(
                    """
                    UPDATE usage_monthly SET overage_count = overage_count + 1
                    WHERE user_id = ? AND period = ?
                    """,
                    (user_id, period),
                )
            else:
                c.execute(
                    """
                    UPDATE usage_monthly SET search_count = search_count + 1
                    WHERE user_id = ? AND period = ?
                    """,
                    (user_id, period),
                )
            row = c.execute(
                "SELECT search_count, overage_count FROM usage_monthly WHERE user_id = ? AND period = ?",
                (user_id, period),
            ).fetchone()
            c.commit()
        assert row is not None
        return (int(row["search_count"]), int(row["overage_count"]))

    def anon_get(self, anon_key: str) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT search_count FROM anon_usage WHERE anon_key = ?",
                (anon_key,),
            ).fetchone()
        return int(row["search_count"]) if row else 0

    def anon_increment(self, anon_key: str) -> int:
        now = time.time()
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO anon_usage (anon_key, search_count, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(anon_key) DO UPDATE SET
                  search_count = search_count + 1,
                  updated_at = excluded.updated_at
                """,
                (anon_key, now),
            )
            row = c.execute(
                "SELECT search_count FROM anon_usage WHERE anon_key = ?",
                (anon_key,),
            ).fetchone()
            c.commit()
        return int(row["search_count"])

    def rate_tick(self, bucket_key: str, *, window_seconds: int = 60, limit: int) -> bool:
        """Return True if under limit, False if rate limited."""
        window = int(time.time() // window_seconds)
        with self._conn() as c:
            row = c.execute(
                "SELECT count FROM rate_buckets WHERE bucket_key = ? AND window_start = ?",
                (bucket_key, window),
            ).fetchone()
            current = int(row["count"]) if row else 0
            if current + 1 > limit:
                return False
            c.execute(
                """
                INSERT INTO rate_buckets (bucket_key, window_start, count)
                VALUES (?, ?, 1)
                ON CONFLICT(bucket_key, window_start) DO UPDATE SET count = count + 1
                """,
                (bucket_key, window),
            )
            c.commit()
        return True

    def prune_old_rate_buckets(self, *, max_age_windows: int = 5, window_seconds: int = 60) -> None:
        cutoff = int(time.time() // window_seconds) - max_age_windows
        with self._conn() as c:
            c.execute("DELETE FROM rate_buckets WHERE window_start < ?", (cutoff,))
            c.commit()

    def create_alert_subscription(
        self,
        user_id: int | str,
        *,
        name: str,
        criteria: dict[str, Any],
        cadence: str,
        day_of_week: int | None,
        hour_local: int,
        timezone: str,
        deliver_csv: bool,
        next_run_at: float,
    ) -> AlertSubscriptionRecord:
        now = time.time()
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO alert_subscriptions (
                    user_id, name, criteria_json, cadence, day_of_week, hour_local,
                    timezone, deliver_csv, is_active, next_run_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    json.dumps(criteria, separators=(",", ":"), sort_keys=True),
                    cadence,
                    day_of_week,
                    hour_local,
                    timezone,
                    1 if deliver_csv else 0,
                    next_run_at,
                    now,
                    now,
                ),
            )
            subscription_id = int(cur.lastrowid)
            c.commit()
        return self.get_alert_subscription(user_id, subscription_id)  # type: ignore[return-value]

    def list_alert_subscriptions(self, user_id: int | str) -> list[AlertSubscriptionRecord]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM alert_subscriptions
                WHERE user_id = ?
                ORDER BY is_active DESC, next_run_at ASC, created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [_row_to_alert_subscription(row) for row in rows]

    def get_alert_subscription(
        self,
        user_id: int | str,
        subscription_id: int | str,
    ) -> AlertSubscriptionRecord | None:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT *
                FROM alert_subscriptions
                WHERE user_id = ? AND id = ?
                """,
                (user_id, subscription_id),
            ).fetchone()
        return _row_to_alert_subscription(row) if row is not None else None

    def update_alert_subscription(
        self,
        user_id: int | str,
        subscription_id: int | str,
        *,
        name: str | None = None,
        criteria: dict[str, Any] | None = None,
        cadence: str | None = None,
        day_of_week: int | None = None,
        hour_local: int | None = None,
        timezone: str | None = None,
        deliver_csv: bool | None = None,
        is_active: bool | None = None,
        next_run_at: float | None = None,
        last_run_at: float | None = None,
        last_run_status: str | None = None,
        last_result_count: int | None = None,
        last_error: str | None = None,
    ) -> AlertSubscriptionRecord | None:
        fields: list[str] = []
        args: list[Any] = []
        if name is not None:
            fields.append("name = ?")
            args.append(name)
        if criteria is not None:
            fields.append("criteria_json = ?")
            args.append(json.dumps(criteria, separators=(",", ":"), sort_keys=True))
        if cadence is not None:
            fields.append("cadence = ?")
            args.append(cadence)
            fields.append("day_of_week = ?")
            args.append(day_of_week)
        if hour_local is not None:
            fields.append("hour_local = ?")
            args.append(hour_local)
        if timezone is not None:
            fields.append("timezone = ?")
            args.append(timezone)
        if deliver_csv is not None:
            fields.append("deliver_csv = ?")
            args.append(1 if deliver_csv else 0)
        if is_active is not None:
            fields.append("is_active = ?")
            args.append(1 if is_active else 0)
        if next_run_at is not None:
            fields.append("next_run_at = ?")
            args.append(next_run_at)
        if last_run_at is not None:
            fields.append("last_run_at = ?")
            args.append(last_run_at)
        if last_run_status is not None:
            fields.append("last_run_status = ?")
            args.append(last_run_status)
        if last_result_count is not None:
            fields.append("last_result_count = ?")
            args.append(last_result_count)
        if last_error is not None or last_error == "":
            fields.append("last_error = ?")
            args.append(last_error)
        if not fields:
            return self.get_alert_subscription(user_id, subscription_id)
        fields.append("updated_at = ?")
        args.append(time.time())
        args.extend([user_id, subscription_id])
        with self._conn() as c:
            c.execute(
                f"UPDATE alert_subscriptions SET {', '.join(fields)} WHERE user_id = ? AND id = ?",
                args,
            )
            c.commit()
        return self.get_alert_subscription(user_id, subscription_id)

    def delete_alert_subscription(self, user_id: int | str, subscription_id: int | str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM alert_subscriptions WHERE user_id = ? AND id = ?",
                (user_id, subscription_id),
            )
            c.commit()
        return cur.rowcount > 0

    def list_due_alert_subscriptions(
        self,
        *,
        now_ts: float,
        limit: int = 25,
    ) -> list[AlertSubscriptionRecord]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM alert_subscriptions
                WHERE is_active = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (now_ts, limit),
            ).fetchall()
        return [_row_to_alert_subscription(row) for row in rows]

    def create_alert_run(
        self,
        *,
        subscription_id: int | str,
        user_id: int | str,
        trigger_source: str,
        status: str,
        result_count: int,
        emailed: bool,
        csv_attached: bool,
        error_message: str | None,
        summary: dict[str, Any],
        started_at: float,
        completed_at: float | None,
    ) -> AlertRunRecord:
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO alert_runs (
                    subscription_id, user_id, trigger_source, status, result_count,
                    emailed, csv_attached, error_message, summary_json, started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription_id,
                    user_id,
                    trigger_source,
                    status,
                    result_count,
                    1 if emailed else 0,
                    1 if csv_attached else 0,
                    error_message,
                    json.dumps(summary, separators=(",", ":"), sort_keys=True),
                    started_at,
                    completed_at,
                ),
            )
            run_id = int(cur.lastrowid)
            c.commit()
        with self._conn() as c:
            row = c.execute("SELECT * FROM alert_runs WHERE id = ?", (run_id,)).fetchone()
        assert row is not None
        return _row_to_alert_run(row)

    def list_alert_runs(self, user_id: int | str, *, limit: int = 20) -> list[AlertRunRecord]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM alert_runs
                WHERE user_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [_row_to_alert_run(row) for row in rows]

    def create_scrape_run(
        self,
        *,
        correlation_id: str,
        user_id: int | str | None,
        anon_key: str | None,
        trigger_source: str,
        status: str,
        location: str,
        make: str,
        model: str,
        vehicle_category: str,
        vehicle_condition: str,
        inventory_scope: str,
        radius_miles: int,
        requested_max_dealerships: int | None,
        requested_max_pages_per_dealer: int | None,
        started_at: float,
    ) -> ScrapeRunRecord:
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO scrape_runs (
                    correlation_id, user_id, anon_key, trigger_source, status,
                    location, make, model, vehicle_category, vehicle_condition,
                    inventory_scope, radius_miles, requested_max_dealerships,
                    requested_max_pages_per_dealer, started_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correlation_id,
                    user_id,
                    anon_key,
                    trigger_source,
                    status,
                    location,
                    make,
                    model,
                    vehicle_category,
                    vehicle_condition,
                    inventory_scope,
                    radius_miles,
                    requested_max_dealerships,
                    requested_max_pages_per_dealer,
                    started_at,
                ),
            )
            run_id = int(cur.lastrowid)
            c.commit()
        with self._conn() as c:
            row = c.execute("SELECT * FROM scrape_runs WHERE id = ?", (run_id,)).fetchone()
        assert row is not None
        return _row_to_scrape_run(row)

    def finalize_scrape_run(
        self,
        scrape_run_id: int | str,
        *,
        status: str,
        result_count: int,
        dealer_discovery_count: int | None,
        dealer_deduped_count: int | None,
        dealerships_attempted: int,
        dealerships_succeeded: int,
        dealerships_failed: int,
        error_count: int,
        warning_count: int,
        error_message: str | None,
        summary: dict[str, Any],
        economics: dict[str, Any],
        completed_at: float,
    ) -> ScrapeRunRecord:
        with self._conn() as c:
            c.execute(
                """
                UPDATE scrape_runs
                SET status = ?, result_count = ?, dealer_discovery_count = ?, dealer_deduped_count = ?,
                    dealerships_attempted = ?, dealerships_succeeded = ?, dealerships_failed = ?,
                    error_count = ?, warning_count = ?, error_message = ?, summary_json = ?,
                    economics_json = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    result_count,
                    dealer_discovery_count,
                    dealer_deduped_count,
                    dealerships_attempted,
                    dealerships_succeeded,
                    dealerships_failed,
                    error_count,
                    warning_count,
                    error_message,
                    json.dumps(summary, separators=(",", ":"), sort_keys=True),
                    json.dumps(economics, separators=(",", ":"), sort_keys=True),
                    completed_at,
                    scrape_run_id,
                ),
            )
            c.commit()
        with self._conn() as c:
            row = c.execute("SELECT * FROM scrape_runs WHERE id = ?", (scrape_run_id,)).fetchone()
        assert row is not None
        return _row_to_scrape_run(row)

    def add_scrape_event(
        self,
        *,
        scrape_run_id: int | str,
        correlation_id: str,
        sequence_no: int,
        event_type: str,
        phase: str | None,
        level: str,
        message: str,
        dealership_name: str | None,
        dealership_website: str | None,
        payload: dict[str, Any],
        created_at: float,
    ) -> ScrapeEventRecord:
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO scrape_events (
                    scrape_run_id, correlation_id, sequence_no, event_type, phase, level,
                    message, dealership_name, dealership_website, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scrape_run_id,
                    correlation_id,
                    sequence_no,
                    event_type,
                    phase,
                    level,
                    message,
                    dealership_name,
                    dealership_website,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    created_at,
                ),
            )
            event_id = int(cur.lastrowid)
            c.commit()
        with self._conn() as c:
            row = c.execute("SELECT * FROM scrape_events WHERE id = ?", (event_id,)).fetchone()
        assert row is not None
        return _row_to_scrape_event(row)

    def list_scrape_runs(
        self,
        *,
        user_id: int | str | None = None,
        anon_key: str | None = None,
        limit: int = 20,
    ) -> list[ScrapeRunRecord]:
        if user_id is None and not anon_key:
            return []
        with self._conn() as c:
            if user_id is not None:
                rows = c.execute(
                    """
                    SELECT *
                    FROM scrape_runs
                    WHERE user_id = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    """
                    SELECT *
                    FROM scrape_runs
                    WHERE anon_key = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (anon_key, limit),
                ).fetchall()
        return [_row_to_scrape_run(row) for row in rows]

    def get_scrape_run(
        self,
        correlation_id: str,
        *,
        user_id: int | str | None = None,
        anon_key: str | None = None,
    ) -> ScrapeRunRecord | None:
        if user_id is None and not anon_key:
            return None
        with self._conn() as c:
            if user_id is not None:
                row = c.execute(
                    """
                    SELECT *
                    FROM scrape_runs
                    WHERE correlation_id = ? AND user_id = ?
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (correlation_id, user_id),
                ).fetchone()
            else:
                row = c.execute(
                    """
                    SELECT *
                    FROM scrape_runs
                    WHERE correlation_id = ? AND anon_key = ?
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (correlation_id, anon_key),
                ).fetchone()
        return _row_to_scrape_run(row) if row is not None else None

    def list_scrape_events(self, scrape_run_id: int | str, *, limit: int = 200) -> list[ScrapeEventRecord]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM scrape_events
                WHERE scrape_run_id = ?
                ORDER BY sequence_no ASC
                LIMIT ?
                """,
                (scrape_run_id, limit),
            ).fetchall()
        return [_row_to_scrape_event(row) for row in rows]


def _row_to_user(row: sqlite3.Row | None) -> UserRecord | None:
    if row is None:
        return None
    ent_raw = row["entitlements_json"]
    ent: dict[str, Any] = {}
    if ent_raw:
        try:
            ent = dict(json.loads(ent_raw)) if isinstance(ent_raw, str) else {}
        except json.JSONDecodeError:
            ent = {}
    return UserRecord(
        id=str(row["id"]),
        email=str(row["email"]),
        tier=str(row["tier"]),
        stripe_customer_id=row["stripe_customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        stripe_metered_item_id=row["stripe_metered_item_id"],
        entitlements=ent,
    )


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _row_to_alert_subscription(row: sqlite3.Row) -> AlertSubscriptionRecord:
    return AlertSubscriptionRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        criteria=_json_dict(row["criteria_json"]),
        cadence=str(row["cadence"]),
        day_of_week=int(row["day_of_week"]) if row["day_of_week"] is not None else None,
        hour_local=int(row["hour_local"]),
        timezone=str(row["timezone"]),
        deliver_csv=bool(row["deliver_csv"]),
        is_active=bool(row["is_active"]),
        next_run_at=float(row["next_run_at"]),
        last_run_at=float(row["last_run_at"]) if row["last_run_at"] is not None else None,
        last_run_status=str(row["last_run_status"]) if row["last_run_status"] is not None else None,
        last_result_count=int(row["last_result_count"]) if row["last_result_count"] is not None else None,
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _row_to_alert_run(row: sqlite3.Row) -> AlertRunRecord:
    return AlertRunRecord(
        id=str(row["id"]),
        subscription_id=str(row["subscription_id"]),
        user_id=str(row["user_id"]),
        trigger_source=str(row["trigger_source"]),
        status=str(row["status"]),
        result_count=int(row["result_count"]),
        emailed=bool(row["emailed"]),
        csv_attached=bool(row["csv_attached"]),
        error_message=str(row["error_message"]) if row["error_message"] is not None else None,
        summary=_json_dict(row["summary_json"]),
        started_at=float(row["started_at"]),
        completed_at=float(row["completed_at"]) if row["completed_at"] is not None else None,
    )


def _row_to_scrape_run(row: sqlite3.Row) -> ScrapeRunRecord:
    return ScrapeRunRecord(
        id=str(row["id"]),
        correlation_id=str(row["correlation_id"]),
        user_id=str(row["user_id"]) if row["user_id"] is not None else None,
        anon_key=str(row["anon_key"]) if row["anon_key"] is not None else None,
        trigger_source=str(row["trigger_source"]),
        status=str(row["status"]),
        location=str(row["location"]),
        make=str(row["make"]),
        model=str(row["model"]),
        vehicle_category=str(row["vehicle_category"]),
        vehicle_condition=str(row["vehicle_condition"]),
        inventory_scope=str(row["inventory_scope"]),
        radius_miles=int(row["radius_miles"]),
        requested_max_dealerships=(
            int(row["requested_max_dealerships"]) if row["requested_max_dealerships"] is not None else None
        ),
        requested_max_pages_per_dealer=(
            int(row["requested_max_pages_per_dealer"])
            if row["requested_max_pages_per_dealer"] is not None
            else None
        ),
        result_count=int(row["result_count"]),
        dealer_discovery_count=(
            int(row["dealer_discovery_count"]) if row["dealer_discovery_count"] is not None else None
        ),
        dealer_deduped_count=(
            int(row["dealer_deduped_count"]) if row["dealer_deduped_count"] is not None else None
        ),
        dealerships_attempted=int(row["dealerships_attempted"]),
        dealerships_succeeded=int(row["dealerships_succeeded"]),
        dealerships_failed=int(row["dealerships_failed"]),
        error_count=int(row["error_count"]),
        warning_count=int(row["warning_count"]),
        error_message=str(row["error_message"]) if row["error_message"] is not None else None,
        summary=_json_dict(row["summary_json"]),
        economics=_json_dict(row["economics_json"]),
        started_at=float(row["started_at"]),
        completed_at=float(row["completed_at"]) if row["completed_at"] is not None else None,
    )


def _row_to_scrape_event(row: sqlite3.Row) -> ScrapeEventRecord:
    return ScrapeEventRecord(
        id=str(row["id"]),
        scrape_run_id=str(row["scrape_run_id"]),
        correlation_id=str(row["correlation_id"]),
        sequence_no=int(row["sequence_no"]),
        event_type=str(row["event_type"]),
        phase=str(row["phase"]) if row["phase"] is not None else None,
        level=str(row["level"]),
        message=str(row["message"]),
        dealership_name=str(row["dealership_name"]) if row["dealership_name"] is not None else None,
        dealership_website=str(row["dealership_website"]) if row["dealership_website"] is not None else None,
        payload=_json_dict(row["payload_json"]),
        created_at=float(row["created_at"]),
    )


_store: AccountStore | None = None


def get_account_store(path: str) -> AccountStore | Any:
    if settings.supabase_url and settings.supabase_service_key:
        from app.db.supabase_store import get_supabase_store
        return get_supabase_store()
    global _store
    if _store is None or _store.path != path:
        _store = AccountStore(path)
    return _store
