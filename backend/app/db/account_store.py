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


_store: AccountStore | None = None


def get_account_store(path: str) -> AccountStore | Any:
    if settings.supabase_url and settings.supabase_service_key:
        from app.db.supabase_store import get_supabase_store
        return get_supabase_store()
    global _store
    if _store is None or _store.path != path:
        _store = AccountStore(path)
    return _store
