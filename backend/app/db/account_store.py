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
from app.services.inventory_tracking import inventory_history_key

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

_schema = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    is_admin INTEGER NOT NULL DEFAULT 0,
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
    only_send_on_changes INTEGER NOT NULL DEFAULT 0,
    include_new_listings INTEGER NOT NULL DEFAULT 1,
    include_price_drops INTEGER NOT NULL DEFAULT 1,
    min_price_drop_usd REAL,
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

CREATE TABLE IF NOT EXISTS saved_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    criteria_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_saved_searches_user_id
ON saved_searches (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS inventory_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    vehicle_key TEXT NOT NULL,
    dealership_key TEXT NOT NULL,
    vin TEXT,
    vehicle_identifier TEXT,
    listing_url TEXT,
    raw_title TEXT,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    first_scrape_run_id TEXT,
    latest_scrape_run_id TEXT,
    seen_count INTEGER NOT NULL DEFAULT 1,
    first_price REAL,
    previous_price REAL,
    latest_price REAL,
    lowest_price REAL,
    highest_price REAL,
    latest_days_on_lot INTEGER,
    price_history_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, vehicle_key)
);

CREATE INDEX IF NOT EXISTS idx_inventory_history_user_id
ON inventory_history (user_id, last_seen_at DESC);

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
    prefer_small_dealers INTEGER NOT NULL DEFAULT 0,
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
    listings_snapshot_json TEXT,
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

CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER,
    actor_email TEXT,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_created_at
ON admin_audit_logs (created_at DESC);
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
            columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "is_admin" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            alert_columns = {
                str(row["name"]) for row in conn.execute("PRAGMA table_info(alert_subscriptions)").fetchall()
            }
            if "only_send_on_changes" not in alert_columns:
                conn.execute("ALTER TABLE alert_subscriptions ADD COLUMN only_send_on_changes INTEGER NOT NULL DEFAULT 0")
            if "include_new_listings" not in alert_columns:
                conn.execute("ALTER TABLE alert_subscriptions ADD COLUMN include_new_listings INTEGER NOT NULL DEFAULT 1")
            if "include_price_drops" not in alert_columns:
                conn.execute("ALTER TABLE alert_subscriptions ADD COLUMN include_price_drops INTEGER NOT NULL DEFAULT 1")
            if "min_price_drop_usd" not in alert_columns:
                conn.execute("ALTER TABLE alert_subscriptions ADD COLUMN min_price_drop_usd REAL")
            scrape_cols = {str(row["name"]) for row in conn.execute("PRAGMA table_info(scrape_runs)").fetchall()}
            if "listings_snapshot_json" not in scrape_cols:
                conn.execute("ALTER TABLE scrape_runs ADD COLUMN listings_snapshot_json TEXT")
            if "prefer_small_dealers" not in scrape_cols:
                conn.execute("ALTER TABLE scrape_runs ADD COLUMN prefer_small_dealers INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        finally:
            conn.close()


@dataclass(slots=True)
class UserRecord:
    id: str
    email: str
    tier: str
    is_admin: bool
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_metered_item_id: str | None
    entitlements: dict[str, Any]
    created_at: float
    updated_at: float


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
    only_send_on_changes: bool
    include_new_listings: bool
    include_price_drops: bool
    min_price_drop_usd: float | None
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
class SavedSearchRecord:
    id: str
    user_id: str
    name: str
    criteria: dict[str, Any]
    created_at: float
    updated_at: float


@dataclass(slots=True)
class InventoryHistoryRecord:
    id: str
    user_id: str
    vehicle_key: str
    dealership_key: str
    vin: str | None
    vehicle_identifier: str | None
    listing_url: str | None
    raw_title: str | None
    first_seen_at: float
    last_seen_at: float
    first_scrape_run_id: str | None
    latest_scrape_run_id: str | None
    seen_count: int
    first_price: float | None
    previous_price: float | None
    latest_price: float | None
    lowest_price: float | None
    highest_price: float | None
    latest_days_on_lot: int | None
    price_history: list[dict[str, Any]]
    created_at: float
    updated_at: float


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
    prefer_small_dealers: bool
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
    listings_snapshot: list[dict[str, Any]] | None
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


@dataclass(slots=True)
class AdminAuditLogRecord:
    id: str
    actor_user_id: str | None
    actor_email: str | None
    action: str
    target_type: str
    target_id: str | None
    summary: str
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
                SELECT id, email, tier, is_admin, stripe_customer_id, stripe_subscription_id,
                       stripe_metered_item_id, entitlements_json, created_at, updated_at
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return _row_to_user(row)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT id, email, tier, is_admin, stripe_customer_id, stripe_subscription_id,
                       stripe_metered_item_id, entitlements_json, created_at, updated_at
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

    def set_admin(self, user_id: int | str, is_admin: bool) -> None:
        now = time.time()
        with self._conn() as c:
            c.execute(
                "UPDATE users SET is_admin = ?, updated_at = ? WHERE id = ?",
                (1 if is_admin else 0, now, user_id),
            )
            c.commit()

    def list_users(self, *, limit: int = 50, offset: int = 0, query: str | None = None) -> list[UserRecord]:
        with self._conn() as c:
            if query:
                rows = c.execute(
                    """
                    SELECT id, email, tier, is_admin, stripe_customer_id, stripe_subscription_id,
                           stripe_metered_item_id, entitlements_json, created_at, updated_at
                    FROM users
                    WHERE email LIKE ? COLLATE NOCASE
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (f"%{query.strip()}%", limit, offset),
                ).fetchall()
            else:
                rows = c.execute(
                    """
                    SELECT id, email, tier, is_admin, stripe_customer_id, stripe_subscription_id,
                           stripe_metered_item_id, entitlements_json, created_at, updated_at
                    FROM users
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
        return [user for row in rows if (user := _row_to_user(row)) is not None]

    def count_users(self, *, query: str | None = None) -> int:
        with self._conn() as c:
            if query:
                row = c.execute(
                    "SELECT COUNT(*) AS count FROM users WHERE email LIKE ? COLLATE NOCASE",
                    (f"%{query.strip()}%",),
                ).fetchone()
            else:
                row = c.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"]) if row is not None else 0

    def count_users_by_tier(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT tier, COUNT(*) AS count
                FROM users
                GROUP BY tier
                """
            ).fetchall()
        return {str(row["tier"]): int(row["count"]) for row in rows}

    def total_searches_in_period(self, period: str) -> int:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT COALESCE(SUM(search_count + overage_count), 0) AS total
                FROM usage_monthly
                WHERE period = ?
                """,
                (period,),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def total_overage_searches_in_period(self, period: str) -> int:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT COALESCE(SUM(overage_count), 0) AS total
                FROM usage_monthly
                WHERE period = ?
                """,
                (period,),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def count_recent_users(self, *, since_ts: float) -> int:
        with self._conn() as c:
            row = c.execute("SELECT COUNT(*) AS count FROM users WHERE created_at >= ?", (since_ts,)).fetchone()
        return int(row["count"]) if row is not None else 0

    def count_scrape_runs(self, *, since_ts: float | None = None, status: str | None = None) -> int:
        clauses: list[str] = []
        args: list[Any] = []
        if since_ts is not None:
            clauses.append("started_at >= ?")
            args.append(since_ts)
        if status:
            clauses.append("status = ?")
            args.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as c:
            row = c.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM scrape_runs
                {where_sql}
                """,
                args,
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def count_alert_subscriptions(self, *, active_only: bool | None = None, due_before_ts: float | None = None) -> int:
        clauses: list[str] = []
        args: list[Any] = []
        if active_only is not None:
            clauses.append("is_active = ?")
            args.append(1 if active_only else 0)
        if due_before_ts is not None:
            clauses.append("next_run_at <= ?")
            args.append(due_before_ts)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as c:
            row = c.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM alert_subscriptions
                {where_sql}
                """,
                args,
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def count_alert_runs(self, *, since_ts: float | None = None, status: str | None = None) -> int:
        clauses: list[str] = []
        args: list[Any] = []
        if since_ts is not None:
            clauses.append("started_at >= ?")
            args.append(since_ts)
        if status:
            clauses.append("status = ?")
            args.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as c:
            row = c.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM alert_runs
                {where_sql}
                """,
                args,
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def create_saved_search(
        self,
        user_id: int | str,
        *,
        name: str,
        criteria: dict[str, Any],
    ) -> SavedSearchRecord:
        now = time.time()
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO saved_searches (
                    user_id, name, criteria_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    json.dumps(criteria, separators=(",", ":"), sort_keys=True),
                    now,
                    now,
                ),
            )
            saved_search_id = int(cur.lastrowid)
            c.commit()
        return self.get_saved_search(user_id, saved_search_id)  # type: ignore[return-value]

    def list_saved_searches(self, user_id: int | str) -> list[SavedSearchRecord]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM saved_searches
                WHERE user_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [_row_to_saved_search(row) for row in rows]

    def get_saved_search(self, user_id: int | str, saved_search_id: int | str) -> SavedSearchRecord | None:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT *
                FROM saved_searches
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, saved_search_id),
            ).fetchone()
        return _row_to_saved_search(row) if row is not None else None

    def update_saved_search(
        self,
        user_id: int | str,
        saved_search_id: int | str,
        *,
        name: str | None = None,
        criteria: dict[str, Any] | None = None,
    ) -> SavedSearchRecord | None:
        fields: list[str] = []
        args: list[Any] = []
        if name is not None:
            fields.append("name = ?")
            args.append(name)
        if criteria is not None:
            fields.append("criteria_json = ?")
            args.append(json.dumps(criteria, separators=(",", ":"), sort_keys=True))
        if not fields:
            return self.get_saved_search(user_id, saved_search_id)
        fields.append("updated_at = ?")
        args.append(time.time())
        args.extend((user_id, saved_search_id))
        with self._conn() as c:
            c.execute(
                f"UPDATE saved_searches SET {', '.join(fields)} WHERE user_id = ? AND id = ?",
                args,
            )
            c.commit()
        return self.get_saved_search(user_id, saved_search_id)

    def delete_saved_search(self, user_id: int | str, saved_search_id: int | str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM saved_searches WHERE user_id = ? AND id = ?",
                (user_id, saved_search_id),
            )
            c.commit()
        return (cur.rowcount or 0) > 0

    def get_inventory_history_map(
        self,
        user_id: int | str,
        listings: list[Any],
    ) -> dict[str, InventoryHistoryRecord]:
        keys_set: set[str] = set()
        for listing in listings:
            target = _ListingProxy(listing) if isinstance(listing, dict) else listing
            key = inventory_history_key(target)
            if key:
                keys_set.add(key)
        keys = sorted(keys_set)
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        with self._conn() as c:
            rows = c.execute(
                f"""
                SELECT *
                FROM inventory_history
                WHERE user_id = ? AND vehicle_key IN ({placeholders})
                """,
                [user_id, *keys],
            ).fetchall()
        return {record.vehicle_key: record for record in (_row_to_inventory_history(row) for row in rows)}

    def record_inventory_history(
        self,
        user_id: int | str,
        *,
        scrape_run_id: int | str,
        listings: list[dict[str, Any]],
        observed_at: float,
    ) -> None:
        deduped: dict[str, dict[str, Any]] = {}
        for listing in listings:
            key = inventory_history_key(_ListingProxy(listing))
            if key:
                deduped[key] = listing
        if not deduped:
            return

        with self._conn() as c:
            for vehicle_key, listing in deduped.items():
                current_price = _maybe_float(listing.get("price"))
                current_days_on_lot = _maybe_int(listing.get("days_on_lot"))
                current_history_entry = (
                    {"observed_at": observed_at, "price": current_price}
                    if current_price is not None
                    else None
                )
                existing_row = c.execute(
                    """
                    SELECT *
                    FROM inventory_history
                    WHERE user_id = ? AND vehicle_key = ?
                    LIMIT 1
                    """,
                    (user_id, vehicle_key),
                ).fetchone()
                if existing_row is None:
                    price_history = [current_history_entry] if current_history_entry is not None else []
                    c.execute(
                        """
                        INSERT INTO inventory_history (
                            user_id, vehicle_key, dealership_key, vin, vehicle_identifier, listing_url, raw_title,
                            first_seen_at, last_seen_at, first_scrape_run_id, latest_scrape_run_id, seen_count,
                            first_price, previous_price, latest_price, lowest_price, highest_price, latest_days_on_lot,
                            price_history_json, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            vehicle_key,
                            str(listing.get("dealership_website") or ""),
                            listing.get("vin"),
                            listing.get("vehicle_identifier"),
                            listing.get("listing_url"),
                            listing.get("raw_title"),
                            observed_at,
                            observed_at,
                            str(scrape_run_id),
                            str(scrape_run_id),
                            1,
                            current_price,
                            None,
                            current_price,
                            current_price,
                            current_price,
                            current_days_on_lot,
                            json.dumps(price_history, separators=(",", ":"), sort_keys=True),
                            observed_at,
                            observed_at,
                        ),
                    )
                    continue

                existing = _row_to_inventory_history(existing_row)
                price_history = list(existing.price_history)
                previous_price = existing.previous_price
                latest_price = existing.latest_price
                lowest_price = existing.lowest_price
                highest_price = existing.highest_price
                if current_price is not None:
                    previous_price = latest_price if latest_price is not None else previous_price
                    latest_price = current_price
                    lowest_price = current_price if lowest_price is None else min(lowest_price, current_price)
                    highest_price = current_price if highest_price is None else max(highest_price, current_price)
                    price_history.append({"observed_at": observed_at, "price": current_price})
                    price_history = price_history[-12:]

                c.execute(
                    """
                    UPDATE inventory_history
                    SET dealership_key = ?, vin = ?, vehicle_identifier = ?, listing_url = ?, raw_title = ?,
                        last_seen_at = ?, latest_scrape_run_id = ?, seen_count = ?, previous_price = ?, latest_price = ?,
                        lowest_price = ?, highest_price = ?, latest_days_on_lot = ?, price_history_json = ?, updated_at = ?
                    WHERE user_id = ? AND vehicle_key = ?
                    """,
                    (
                        str(listing.get("dealership_website") or existing.dealership_key or ""),
                        listing.get("vin") or existing.vin,
                        listing.get("vehicle_identifier") or existing.vehicle_identifier,
                        listing.get("listing_url") or existing.listing_url,
                        listing.get("raw_title") or existing.raw_title,
                        observed_at,
                        str(scrape_run_id),
                        existing.seen_count + 1,
                        previous_price,
                        latest_price,
                        lowest_price,
                        highest_price,
                        current_days_on_lot if current_days_on_lot is not None else existing.latest_days_on_lot,
                        json.dumps(price_history, separators=(",", ":"), sort_keys=True),
                        observed_at,
                        user_id,
                        vehicle_key,
                    ),
                )
            c.commit()

    def admin_list_scrape_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[ScrapeRunRecord]:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        with self._conn() as c:
            rows = c.execute(
                f"""
                SELECT *
                FROM scrape_runs
                {where_sql}
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                args,
            ).fetchall()
        return [_row_to_scrape_run(row) for row in rows]

    def count_admin_scrape_runs(self, *, status: str | None = None) -> int:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as c:
            row = c.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM scrape_runs
                {where_sql}
                """,
                args,
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def admin_get_scrape_run(self, correlation_id: str) -> ScrapeRunRecord | None:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT *
                FROM scrape_runs
                WHERE correlation_id = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (correlation_id,),
            ).fetchone()
        return _row_to_scrape_run(row) if row is not None else None

    def admin_close_stuck_running_scrape_run(self, correlation_id: str) -> ScrapeRunRecord:
        """
        Mark the latest scrape run for ``correlation_id`` as failed if it is still ``running``.

        Used when the interactive stream died without calling ``finalize`` (e.g. serverless kill,
        hung worker, or client disconnect without cleanup). Raises ``LookupError`` if no row exists,
        ``ValueError(status)`` if the run is not ``running``.
        """
        run = self.admin_get_scrape_run(correlation_id)
        if run is None:
            raise LookupError
        if run.status != "running":
            raise ValueError(run.status)
        msg = "Run left in running state; closed administratively."
        summary = dict(run.summary) if isinstance(run.summary, dict) else {}
        summary.update(
            {
                "ok": False,
                "status": "failed",
                "correlation_id": run.correlation_id,
                "admin_closed": True,
                "error_message": msg,
            }
        )
        economics = dict(run.economics) if isinstance(run.economics, dict) else {}
        return self.finalize_scrape_run(
            run.id,
            status="failed",
            result_count=run.result_count,
            dealer_discovery_count=run.dealer_discovery_count,
            dealer_deduped_count=run.dealer_deduped_count,
            dealerships_attempted=run.dealerships_attempted,
            dealerships_succeeded=run.dealerships_succeeded,
            dealerships_failed=run.dealerships_failed,
            error_count=run.error_count,
            warning_count=run.warning_count,
            error_message=msg,
            summary=summary,
            economics=economics,
            completed_at=time.time(),
            listings_snapshot=run.listings_snapshot,
        )

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
        only_send_on_changes: bool,
        include_new_listings: bool,
        include_price_drops: bool,
        min_price_drop_usd: float | None,
        next_run_at: float,
    ) -> AlertSubscriptionRecord:
        now = time.time()
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO alert_subscriptions (
                    user_id, name, criteria_json, cadence, day_of_week, hour_local,
                    timezone, deliver_csv, only_send_on_changes, include_new_listings,
                    include_price_drops, min_price_drop_usd, is_active, next_run_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
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
                    1 if only_send_on_changes else 0,
                    1 if include_new_listings else 0,
                    1 if include_price_drops else 0,
                    min_price_drop_usd,
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
        only_send_on_changes: bool | None = None,
        include_new_listings: bool | None = None,
        include_price_drops: bool | None = None,
        min_price_drop_usd: float | None = None,
        min_price_drop_usd_provided: bool = False,
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
        if only_send_on_changes is not None:
            fields.append("only_send_on_changes = ?")
            args.append(1 if only_send_on_changes else 0)
        if include_new_listings is not None:
            fields.append("include_new_listings = ?")
            args.append(1 if include_new_listings else 0)
        if include_price_drops is not None:
            fields.append("include_price_drops = ?")
            args.append(1 if include_price_drops else 0)
        if min_price_drop_usd is not None or min_price_drop_usd_provided:
            fields.append("min_price_drop_usd = ?")
            args.append(min_price_drop_usd)
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

    def claim_due_alert_subscriptions(
        self,
        *,
        now_ts: float,
        limit: int = 25,
        claim_ttl_seconds: int,
    ) -> list[AlertSubscriptionRecord]:
        claim_until_ts = now_ts + max(60, int(claim_ttl_seconds or 0))
        claimed_keys: list[tuple[Any, Any]] = []
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
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
            for row in rows:
                updated = c.execute(
                    """
                    UPDATE alert_subscriptions
                    SET next_run_at = ?, last_run_status = ?, updated_at = ?
                    WHERE id = ? AND user_id = ? AND is_active = 1 AND next_run_at <= ?
                    """,
                    (claim_until_ts, "claiming", now_ts, row["id"], row["user_id"], now_ts),
                )
                if updated.rowcount:
                    claimed_keys.append((row["user_id"], row["id"]))
            c.commit()
        claimed: list[AlertSubscriptionRecord] = []
        for user_id, subscription_id in claimed_keys:
            record = self.get_alert_subscription(user_id, subscription_id)
            if record is not None:
                claimed.append(record)
        return claimed

    def admin_list_alert_subscriptions(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        due_only: bool = False,
    ) -> list[AlertSubscriptionRecord]:
        clauses: list[str] = []
        args: list[Any] = []
        if due_only:
            clauses.append("is_active = 1 AND next_run_at <= ?")
            args.append(time.time())
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        with self._conn() as c:
            rows = c.execute(
                f"""
                SELECT *
                FROM alert_subscriptions
                {where_sql}
                ORDER BY next_run_at ASC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                args,
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

    def get_latest_alert_run_for_subscription(
        self,
        user_id: int | str,
        subscription_id: int | str,
    ) -> AlertRunRecord | None:
        with self._conn() as c:
            row = c.execute(
                """
                SELECT *
                FROM alert_runs
                WHERE user_id = ? AND subscription_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                (user_id, subscription_id),
            ).fetchone()
        return _row_to_alert_run(row) if row is not None else None

    def admin_list_alert_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[AlertRunRecord]:
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("status = ?")
            args.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.extend([limit, offset])
        with self._conn() as c:
            rows = c.execute(
                f"""
                SELECT *
                FROM alert_runs
                {where_sql}
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                args,
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
        prefer_small_dealers: bool = False,
    ) -> ScrapeRunRecord:
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO scrape_runs (
                    correlation_id, user_id, anon_key, trigger_source, status,
                    location, make, model, vehicle_category, vehicle_condition,
                    inventory_scope, prefer_small_dealers, radius_miles,
                    requested_max_dealerships, requested_max_pages_per_dealer, started_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    1 if prefer_small_dealers else 0,
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
        listings_snapshot: list[dict[str, Any]] | None = None,
    ) -> ScrapeRunRecord:
        snapshot_json: str | None
        if listings_snapshot:
            snapshot_json = json.dumps(listings_snapshot, separators=(",", ":"))
        else:
            snapshot_json = None
        with self._conn() as c:
            c.execute(
                """
                UPDATE scrape_runs
                SET status = ?, result_count = ?, dealer_discovery_count = ?, dealer_deduped_count = ?,
                    dealerships_attempted = ?, dealerships_succeeded = ?, dealerships_failed = ?,
                    error_count = ?, warning_count = ?, error_message = ?, summary_json = ?,
                    economics_json = ?, listings_snapshot_json = ?, completed_at = ?
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
                    snapshot_json,
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

    def count_running_scrape_runs(
        self,
        *,
        user_id: int | str | None = None,
        anon_key: str | None = None,
        since_ts: float | None = None,
    ) -> int:
        if user_id is None and not anon_key:
            return 0
        clauses = ["status = ?"]
        args: list[Any] = ["running"]
        if user_id is not None:
            clauses.append("user_id = ?")
            args.append(user_id)
        else:
            clauses.append("anon_key = ?")
            args.append(anon_key)
        if since_ts is not None:
            clauses.append("started_at >= ?")
            args.append(since_ts)
        with self._conn() as c:
            row = c.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM scrape_runs
                WHERE {' AND '.join(clauses)}
                """,
                args,
            ).fetchone()
        return int(row["count"]) if row is not None else 0

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

    def record_admin_audit_event(
        self,
        *,
        actor_user_id: int | str | None,
        actor_email: str | None,
        action: str,
        target_type: str,
        target_id: int | str | None,
        summary: str,
        payload: dict[str, Any],
    ) -> AdminAuditLogRecord:
        created_at = time.time()
        with self._conn() as c:
            cur = c.execute(
                """
                INSERT INTO admin_audit_logs (
                    actor_user_id, actor_email, action, target_type, target_id, summary, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    actor_user_id,
                    actor_email,
                    action,
                    target_type,
                    str(target_id) if target_id is not None else None,
                    summary,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    created_at,
                ),
            )
            audit_id = int(cur.lastrowid)
            c.commit()
        with self._conn() as c:
            row = c.execute("SELECT * FROM admin_audit_logs WHERE id = ?", (audit_id,)).fetchone()
        assert row is not None
        return _row_to_admin_audit_log(row)

    def list_admin_audit_logs(self, *, limit: int = 50, offset: int = 0) -> list[AdminAuditLogRecord]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM admin_audit_logs
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [_row_to_admin_audit_log(row) for row in rows]


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
        is_admin=bool(row["is_admin"]),
        stripe_customer_id=row["stripe_customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        stripe_metered_item_id=row["stripe_metered_item_id"],
        entitlements=ent,
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


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


class _ListingProxy:
    def __init__(self, data: dict[str, Any]) -> None:
        self.dealership_website = data.get("dealership_website")
        self.vin = data.get("vin")
        self.vehicle_identifier = data.get("vehicle_identifier")
        self.listing_url = data.get("listing_url")
        self.year = data.get("year")
        self.make = data.get("make")
        self.model = data.get("model")
        self.trim = data.get("trim")
        self.raw_title = data.get("raw_title")


def _json_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [dict(item) for item in parsed if isinstance(item, dict)]
    return []


def _maybe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_to_alert_subscription(row: sqlite3.Row) -> AlertSubscriptionRecord:
    return AlertSubscriptionRecord(
        id=str(_row_value(row, "id")),
        user_id=str(_row_value(row, "user_id")),
        name=str(_row_value(row, "name")),
        criteria=_json_dict(_row_value(row, "criteria_json")),
        cadence=str(_row_value(row, "cadence")),
        day_of_week=(
            int(_row_value(row, "day_of_week")) if _row_value(row, "day_of_week") is not None else None
        ),
        hour_local=int(_row_value(row, "hour_local", 8)),
        timezone=str(_row_value(row, "timezone", "UTC")),
        deliver_csv=bool(_row_value(row, "deliver_csv", 0)),
        only_send_on_changes=bool(_row_value(row, "only_send_on_changes", 0)),
        include_new_listings=bool(_row_value(row, "include_new_listings", 1)),
        include_price_drops=bool(_row_value(row, "include_price_drops", 1)),
        min_price_drop_usd=_maybe_float(_row_value(row, "min_price_drop_usd")),
        is_active=bool(_row_value(row, "is_active", 1)),
        next_run_at=float(_row_value(row, "next_run_at", 0.0)),
        last_run_at=(
            float(_row_value(row, "last_run_at")) if _row_value(row, "last_run_at") is not None else None
        ),
        last_run_status=(
            str(_row_value(row, "last_run_status")) if _row_value(row, "last_run_status") is not None else None
        ),
        last_result_count=(
            int(_row_value(row, "last_result_count"))
            if _row_value(row, "last_result_count") is not None
            else None
        ),
        last_error=str(_row_value(row, "last_error")) if _row_value(row, "last_error") is not None else None,
        created_at=float(_row_value(row, "created_at", 0.0)),
        updated_at=float(_row_value(row, "updated_at", 0.0)),
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


def _row_to_saved_search(row: sqlite3.Row) -> SavedSearchRecord:
    return SavedSearchRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        criteria=_json_dict(row["criteria_json"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _row_to_inventory_history(row: sqlite3.Row) -> InventoryHistoryRecord:
    return InventoryHistoryRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        vehicle_key=str(row["vehicle_key"]),
        dealership_key=str(row["dealership_key"]),
        vin=str(row["vin"]) if row["vin"] is not None else None,
        vehicle_identifier=str(row["vehicle_identifier"]) if row["vehicle_identifier"] is not None else None,
        listing_url=str(row["listing_url"]) if row["listing_url"] is not None else None,
        raw_title=str(row["raw_title"]) if row["raw_title"] is not None else None,
        first_seen_at=float(row["first_seen_at"]),
        last_seen_at=float(row["last_seen_at"]),
        first_scrape_run_id=str(row["first_scrape_run_id"]) if row["first_scrape_run_id"] is not None else None,
        latest_scrape_run_id=str(row["latest_scrape_run_id"]) if row["latest_scrape_run_id"] is not None else None,
        seen_count=int(row["seen_count"]),
        first_price=_maybe_float(row["first_price"]),
        previous_price=_maybe_float(row["previous_price"]),
        latest_price=_maybe_float(row["latest_price"]),
        lowest_price=_maybe_float(row["lowest_price"]),
        highest_price=_maybe_float(row["highest_price"]),
        latest_days_on_lot=_maybe_int(row["latest_days_on_lot"]),
        price_history=_json_list(row["price_history_json"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
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
        prefer_small_dealers=bool(row["prefer_small_dealers"]),
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
        listings_snapshot=_parse_listings_snapshot(row["listings_snapshot_json"]),
        started_at=float(row["started_at"]),
        completed_at=float(row["completed_at"]) if row["completed_at"] is not None else None,
    )


def _parse_listings_snapshot(raw: str | None) -> list[dict[str, Any]] | None:
    if raw is None or raw == "":
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    out = [x for x in data if isinstance(x, dict)]
    return out or None


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


def _row_to_admin_audit_log(row: sqlite3.Row) -> AdminAuditLogRecord:
    return AdminAuditLogRecord(
        id=str(row["id"]),
        actor_user_id=str(row["actor_user_id"]) if row["actor_user_id"] is not None else None,
        actor_email=str(row["actor_email"]) if row["actor_email"] is not None else None,
        action=str(row["action"]),
        target_type=str(row["target_type"]),
        target_id=str(row["target_id"]) if row["target_id"] is not None else None,
        summary=str(row["summary"]),
        payload=_json_dict(row["payload_json"]),
        created_at=float(row["created_at"]),
    )


_store: AccountStore | None = None


def get_account_store(path: str) -> AccountStore | Any:
    if settings.supabase_url and settings.supabase_service_key:
        from app.db.supabase_store import get_supabase_store
        return get_supabase_store()
    global _store
    init_db(path)
    if _store is None or _store.path != path:
        _store = AccountStore(path)
    return _store
