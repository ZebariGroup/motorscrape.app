"""Supabase implementation of AccountStore."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

from app.config import settings
from app.db.account_store import (
    AdminAuditLogRecord,
    AlertRunRecord,
    AlertSubscriptionRecord,
    InventoryHistoryRecord,
    SavedSearchRecord,
    ScrapeEventRecord,
    ScrapeRunRecord,
    UserRecord,
)
from app.services.inventory_tracking import inventory_history_key

logger = logging.getLogger(__name__)


class EmailNotVerifiedError(Exception):
    """Raised when sign_in_with_password fails because the email is not confirmed yet."""


class EmailAlreadyRegisteredError(Exception):
    """Public sign_up rejected because the email is already registered in Supabase Auth."""


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


class SupabaseAccountStore:
    def __init__(self) -> None:
        url = settings.supabase_url
        key = settings.supabase_service_key
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        self.client: Client = create_client(url, key)

    def create_user(self, email: str, password: str, *, tier: str = "free") -> UserRecord:
        email_n = email.strip().lower()
        # Use the public sign-up path so GoTrue sends the confirmation email (admin.create_user does not).
        anon = (settings.supabase_anon_key or "").strip()
        if not anon:
            raise RuntimeError("SUPABASE_ANON_KEY must be set for email verification sign-ups.")

        anon_client = create_client(settings.supabase_url.strip(), anon)
        try:
            res = anon_client.auth.sign_up({"email": email_n, "password": password})
        except Exception as e:
            msg = (getattr(e, "message", None) or str(e)).lower()
            if (
                "already been registered" in msg
                or "user already registered" in msg
                or "already registered" in msg
            ):
                raise EmailAlreadyRegisteredError from e
            raise
        if res.user is None:
            raise RuntimeError("Sign up failed.")

        user_id = res.user.id

        if tier != "free":
            self.client.table("profiles").update({"tier": tier}).eq("id", user_id).execute()

        record = self.get_user_by_id(user_id)
        if record is None:
            raise RuntimeError("Profile not found after sign up; retry shortly.")
        return record

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        res = self.client.table("profiles").select("*").eq("id", user_id).execute()
        if not res.data:
            return None
        return _row_to_user(res.data[0])

    def get_user_by_email(self, email: str) -> UserRecord | None:
        res = self.client.table("profiles").select("*").eq("email", email.strip().lower()).execute()
        if not res.data:
            return None
        return _row_to_user(res.data[0])

    def verify_login(self, email: str, password: str) -> UserRecord | None:
        try:
            res = self.client.auth.sign_in_with_password({"email": email.strip().lower(), "password": password})
            if res.user:
                return self.get_user_by_id(res.user.id)
        except Exception as e:
            msg = (getattr(e, "message", None) or str(e)).lower()
            if "email_not_confirmed" in msg or "email not confirmed" in msg:
                raise EmailNotVerifiedError from e
            return None
        return None

    def update_password(self, user_id: str, new_password: str) -> None:
        self.client.auth.admin.update_user_by_id(user_id, {"password": new_password})

    def set_tier(
        self,
        user_id: str,
        tier: str,
        *,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        stripe_metered_item_id: str | None = None,
    ) -> None:
        updates: dict[str, Any] = {"tier": tier}
        if stripe_customer_id is not None:
            updates["stripe_customer_id"] = stripe_customer_id
        if stripe_subscription_id is not None:
            updates["stripe_subscription_id"] = stripe_subscription_id
        if stripe_metered_item_id is not None:
            updates["stripe_metered_item_id"] = stripe_metered_item_id

        self.client.table("profiles").update(updates).eq("id", user_id).execute()

    def set_metered_item(self, user_id: str, metered_item_id: str | None) -> None:
        self.client.table("profiles").update({"stripe_metered_item_id": metered_item_id}).eq("id", user_id).execute()

    def set_admin(self, user_id: str, is_admin: bool) -> None:
        self.client.table("profiles").update({"is_admin": is_admin}).eq("id", user_id).execute()

    def list_users(self, *, limit: int = 50, offset: int = 0, query: str | None = None) -> list[UserRecord]:
        request = self.client.table("profiles").select("*").order("created_at", desc=True).range(offset, offset + limit - 1)
        if query:
            request = request.ilike("email", f"%{query.strip()}%")
        res = request.execute()
        return [_row_to_user(row) for row in (res.data or [])]

    def count_users(self, *, query: str | None = None) -> int:
        request = self.client.table("profiles").select("id")
        if query:
            request = request.ilike("email", f"%{query.strip()}%")
        res = request.execute()
        return len(res.data or [])

    def count_users_by_tier(self) -> dict[str, int]:
        res = self.client.table("profiles").select("tier").execute()
        counts: dict[str, int] = {}
        for row in res.data or []:
            tier = str(row.get("tier") or "free")
            counts[tier] = counts.get(tier, 0) + 1
        return counts

    def total_searches_in_period(self, period: str) -> int:
        res = self.client.table("usage_monthly").select("search_count, overage_count").eq("period", period).execute()
        return sum(int(row.get("search_count") or 0) + int(row.get("overage_count") or 0) for row in (res.data or []))

    def total_overage_searches_in_period(self, period: str) -> int:
        res = self.client.table("usage_monthly").select("overage_count").eq("period", period).execute()
        return sum(int(row.get("overage_count") or 0) for row in (res.data or []))

    def count_recent_users(self, *, since_ts: float) -> int:
        threshold = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since_ts))
        res = self.client.table("profiles").select("id").gte("created_at", threshold).execute()
        return len(res.data or [])

    def count_scrape_runs(self, *, since_ts: float | None = None, status: str | None = None) -> int:
        request = self.client.table("scrape_runs").select("id")
        if since_ts is not None:
            threshold = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since_ts))
            request = request.gte("started_at", threshold)
        if status:
            request = request.eq("status", status)
        res = request.execute()
        return len(res.data or [])

    def count_alert_subscriptions(self, *, active_only: bool | None = None, due_before_ts: float | None = None) -> int:
        request = self.client.table("alert_subscriptions").select("id")
        if active_only is not None:
            request = request.eq("is_active", active_only)
        if due_before_ts is not None:
            threshold = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(due_before_ts))
            request = request.lte("next_run_at", threshold)
        res = request.execute()
        return len(res.data or [])

    def count_alert_runs(self, *, since_ts: float | None = None, status: str | None = None) -> int:
        request = self.client.table("alert_runs").select("id")
        if since_ts is not None:
            threshold = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since_ts))
            request = request.gte("started_at", threshold)
        if status:
            request = request.eq("status", status)
        res = request.execute()
        return len(res.data or [])

    def monthly_usage(self, user_id: str, period: str) -> tuple[int, int]:
        res = self.client.table("usage_monthly").select("search_count, overage_count").eq("user_id", user_id).eq("period", period).execute()
        if not res.data:
            return (0, 0)
        return (int(res.data[0]["search_count"]), int(res.data[0]["overage_count"]))

    def increment_search_completed(
        self,
        user_id: str,
        period: str,
        *,
        counts_as_overage: bool,
    ) -> tuple[int, int]:
        # Using Supabase RPC for atomic increment
        res = self.client.rpc("increment_usage", {
            "p_user_id": user_id,
            "p_period": period,
            "p_is_overage": counts_as_overage
        }).execute()

        if res.data:
            return (int(res.data[0]["search_count"]), int(res.data[0]["overage_count"]))

        # Fallback if RPC is not created yet
        current = self.monthly_usage(user_id, period)
        updates = {
            "user_id": user_id,
            "period": period,
            "search_count": current[0] + (0 if counts_as_overage else 1),
            "overage_count": current[1] + (1 if counts_as_overage else 0)
        }
        res2 = self.client.table("usage_monthly").upsert(updates).execute()
        return (int(res2.data[0]["search_count"]), int(res2.data[0]["overage_count"]))

    def anon_get(self, anon_key: str) -> int:
        res = self.client.table("anon_usage").select("search_count").eq("anon_key", anon_key).execute()
        if not res.data:
            return 0
        return int(res.data[0]["search_count"])

    def anon_increment(self, anon_key: str) -> int:
        res = self.client.rpc("increment_anon_usage", {"p_anon_key": anon_key}).execute()
        if res.data:
            return int(res.data)

        # Fallback
        current = self.anon_get(anon_key)
        new_count = current + 1
        self.client.table("anon_usage").upsert({"anon_key": anon_key, "search_count": new_count}).execute()
        return new_count

    def rate_tick(self, bucket_key: str, *, window_seconds: int = 60, limit: int) -> bool:
        window = int(time.time() // window_seconds)
        res = self.client.rpc("rate_tick", {
            "p_bucket_key": bucket_key,
            "p_window_start": window,
            "p_limit": limit
        }).execute()
        if res.data is not None:
            return bool(res.data)

        # Fallback
        res2 = self.client.table("rate_buckets").select("count").eq("bucket_key", bucket_key).eq("window_start", window).execute()
        current = int(res2.data[0]["count"]) if res2.data else 0
        if current + 1 > limit:
            return False
        self.client.table("rate_buckets").upsert({
            "bucket_key": bucket_key,
            "window_start": window,
            "count": current + 1
        }).execute()
        return True

    def prune_old_rate_buckets(self, *, max_age_windows: int = 5, window_seconds: int = 60) -> None:
        cutoff = int(time.time() // window_seconds) - max_age_windows
        self.client.table("rate_buckets").delete().lt("window_start", cutoff).execute()

    def create_saved_search(
        self,
        user_id: str,
        *,
        name: str,
        criteria: dict[str, Any],
    ) -> SavedSearchRecord:
        payload = {
            "user_id": user_id,
            "name": name,
            "criteria_json": criteria,
        }
        res = self.client.table("saved_searches").insert(payload).execute()
        return _row_to_saved_search(res.data[0])

    def list_saved_searches(self, user_id: str) -> list[SavedSearchRecord]:
        res = (
            self.client.table("saved_searches")
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        return [_row_to_saved_search(row) for row in (res.data or [])]

    def get_saved_search(self, user_id: str, saved_search_id: str) -> SavedSearchRecord | None:
        res = (
            self.client.table("saved_searches")
            .select("*")
            .eq("user_id", user_id)
            .eq("id", saved_search_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        return _row_to_saved_search(res.data[0])

    def update_saved_search(
        self,
        user_id: str,
        saved_search_id: str,
        *,
        name: str | None = None,
        criteria: dict[str, Any] | None = None,
    ) -> SavedSearchRecord | None:
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if criteria is not None:
            updates["criteria_json"] = criteria
        if not updates:
            return self.get_saved_search(user_id, saved_search_id)
        self.client.table("saved_searches").update(updates).eq("user_id", user_id).eq("id", saved_search_id).execute()
        return self.get_saved_search(user_id, saved_search_id)

    def delete_saved_search(self, user_id: str, saved_search_id: str) -> bool:
        res = self.client.table("saved_searches").delete().eq("user_id", user_id).eq("id", saved_search_id).execute()
        return bool(res.data)

    def get_inventory_history_map(
        self,
        user_id: str,
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
        res = self.client.table("inventory_history").select("*").eq("user_id", user_id).in_("vehicle_key", keys).execute()
        rows = [_row_to_inventory_history(row) for row in (res.data or [])]
        return {row.vehicle_key: row for row in rows}

    def record_inventory_history(
        self,
        user_id: str,
        *,
        scrape_run_id: str,
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
        keys = list(deduped.keys())
        existing_res = (
            self.client.table("inventory_history").select("*").eq("user_id", user_id).in_("vehicle_key", keys).execute()
        )
        existing_map = {
            row.vehicle_key: row for row in (_row_to_inventory_history(item) for item in (existing_res.data or []))
        }
        observed_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(observed_at))
        upserts: list[dict[str, Any]] = []
        for vehicle_key, listing in deduped.items():
            existing = existing_map.get(vehicle_key)
            current_price = _maybe_float(listing.get("price"))
            current_days_on_lot = _maybe_int(listing.get("days_on_lot"))
            if existing is None:
                price_history = [{"observed_at": observed_at, "price": current_price}] if current_price is not None else []
                upserts.append(
                    {
                        "user_id": user_id,
                        "vehicle_key": vehicle_key,
                        "dealership_key": str(listing.get("dealership_website") or ""),
                        "vin": listing.get("vin"),
                        "vehicle_identifier": listing.get("vehicle_identifier"),
                        "listing_url": listing.get("listing_url"),
                        "raw_title": listing.get("raw_title"),
                        "first_seen_at": observed_at_iso,
                        "last_seen_at": observed_at_iso,
                        "first_scrape_run_id": str(scrape_run_id),
                        "latest_scrape_run_id": str(scrape_run_id),
                        "seen_count": 1,
                        "first_price": current_price,
                        "previous_price": None,
                        "latest_price": current_price,
                        "lowest_price": current_price,
                        "highest_price": current_price,
                        "latest_days_on_lot": current_days_on_lot,
                        "price_history_json": price_history,
                        "created_at": observed_at_iso,
                        "updated_at": observed_at_iso,
                    }
                )
                continue

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

            upserts.append(
                {
                    "id": existing.id,
                    "user_id": user_id,
                    "vehicle_key": vehicle_key,
                    "dealership_key": str(listing.get("dealership_website") or existing.dealership_key or ""),
                    "vin": listing.get("vin") or existing.vin,
                    "vehicle_identifier": listing.get("vehicle_identifier") or existing.vehicle_identifier,
                    "listing_url": listing.get("listing_url") or existing.listing_url,
                    "raw_title": listing.get("raw_title") or existing.raw_title,
                    "first_seen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(existing.first_seen_at)),
                    "last_seen_at": observed_at_iso,
                    "first_scrape_run_id": existing.first_scrape_run_id,
                    "latest_scrape_run_id": str(scrape_run_id),
                    "seen_count": existing.seen_count + 1,
                    "first_price": existing.first_price,
                    "previous_price": previous_price,
                    "latest_price": latest_price,
                    "lowest_price": lowest_price,
                    "highest_price": highest_price,
                    "latest_days_on_lot": current_days_on_lot if current_days_on_lot is not None else existing.latest_days_on_lot,
                    "price_history_json": price_history,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(existing.created_at)),
                    "updated_at": observed_at_iso,
                }
            )
        if upserts:
            self.client.table("inventory_history").upsert(upserts, on_conflict="user_id,vehicle_key").execute()

    def create_alert_subscription(
        self,
        user_id: str,
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
        payload = {
            "user_id": user_id,
            "name": name,
            "criteria_json": criteria,
            "cadence": cadence,
            "day_of_week": day_of_week,
            "hour_local": hour_local,
            "timezone": timezone,
            "deliver_csv": deliver_csv,
            "only_send_on_changes": only_send_on_changes,
            "include_new_listings": include_new_listings,
            "include_price_drops": include_price_drops,
            "min_price_drop_usd": min_price_drop_usd,
            "is_active": True,
            "next_run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(next_run_at)),
        }
        res = self.client.table("alert_subscriptions").insert(payload).execute()
        return _row_to_alert_subscription(res.data[0])

    def list_alert_subscriptions(self, user_id: str) -> list[AlertSubscriptionRecord]:
        res = (
            self.client.table("alert_subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .order("is_active", desc=True)
            .order("next_run_at")
            .execute()
        )
        return [_row_to_alert_subscription(row) for row in (res.data or [])]

    def get_alert_subscription(self, user_id: str, subscription_id: str) -> AlertSubscriptionRecord | None:
        res = (
            self.client.table("alert_subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .eq("id", subscription_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        return _row_to_alert_subscription(res.data[0])

    def update_alert_subscription(
        self,
        user_id: str,
        subscription_id: str,
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
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if criteria is not None:
            updates["criteria_json"] = criteria
        if cadence is not None:
            updates["cadence"] = cadence
            updates["day_of_week"] = day_of_week
        if hour_local is not None:
            updates["hour_local"] = hour_local
        if timezone is not None:
            updates["timezone"] = timezone
        if deliver_csv is not None:
            updates["deliver_csv"] = deliver_csv
        if only_send_on_changes is not None:
            updates["only_send_on_changes"] = only_send_on_changes
        if include_new_listings is not None:
            updates["include_new_listings"] = include_new_listings
        if include_price_drops is not None:
            updates["include_price_drops"] = include_price_drops
        if min_price_drop_usd is not None or min_price_drop_usd_provided:
            updates["min_price_drop_usd"] = min_price_drop_usd
        if is_active is not None:
            updates["is_active"] = is_active
        if next_run_at is not None:
            updates["next_run_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(next_run_at))
        if last_run_at is not None:
            updates["last_run_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_run_at))
        if last_run_status is not None:
            updates["last_run_status"] = last_run_status
        if last_result_count is not None:
            updates["last_result_count"] = last_result_count
        if last_error is not None or last_error == "":
            updates["last_error"] = last_error
        if not updates:
            return self.get_alert_subscription(user_id, subscription_id)
        self.client.table("alert_subscriptions").update(updates).eq("user_id", user_id).eq("id", subscription_id).execute()
        return self.get_alert_subscription(user_id, subscription_id)

    def delete_alert_subscription(self, user_id: str, subscription_id: str) -> bool:
        res = self.client.table("alert_subscriptions").delete().eq("user_id", user_id).eq("id", subscription_id).execute()
        return bool(res.data)

    def list_due_alert_subscriptions(self, *, now_ts: float, limit: int = 25) -> list[AlertSubscriptionRecord]:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
        res = (
            self.client.table("alert_subscriptions")
            .select("*")
            .eq("is_active", True)
            .lte("next_run_at", now_iso)
            .order("next_run_at")
            .limit(limit)
            .execute()
        )
        return [_row_to_alert_subscription(row) for row in (res.data or [])]

    def claim_due_alert_subscriptions(
        self,
        *,
        now_ts: float,
        limit: int = 25,
        claim_ttl_seconds: int,
    ) -> list[AlertSubscriptionRecord]:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
        claim_until_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts + max(60, int(claim_ttl_seconds or 0))))
        res = (
            self.client.table("alert_subscriptions")
            .select("*")
            .eq("is_active", True)
            .lte("next_run_at", now_iso)
            .order("next_run_at")
            .limit(limit)
            .execute()
        )
        claimed: list[AlertSubscriptionRecord] = []
        for row in res.data or []:
            update = (
                self.client.table("alert_subscriptions")
                .update(
                    {
                        "next_run_at": claim_until_iso,
                        "last_run_status": "claiming",
                        "updated_at": now_iso,
                    }
                )
                .eq("id", row["id"])
                .eq("user_id", row["user_id"])
                .eq("is_active", True)
                .eq("next_run_at", row["next_run_at"])
                .execute()
            )
            if update.data:
                claimed.append(_row_to_alert_subscription(update.data[0]))
        return claimed

    def admin_list_alert_subscriptions(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        due_only: bool = False,
    ) -> list[AlertSubscriptionRecord]:
        query = (
            self.client.table("alert_subscriptions")
            .select("*")
            .order("next_run_at")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
        )
        if due_only:
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))
            query = query.eq("is_active", True).lte("next_run_at", now_iso)
        res = query.execute()
        return [_row_to_alert_subscription(row) for row in (res.data or [])]

    def create_alert_run(
        self,
        *,
        subscription_id: str,
        user_id: str,
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
        payload = {
            "subscription_id": subscription_id,
            "user_id": user_id,
            "trigger_source": trigger_source,
            "status": status,
            "result_count": result_count,
            "emailed": emailed,
            "csv_attached": csv_attached,
            "error_message": error_message,
            "summary_json": summary,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(completed_at)) if completed_at is not None else None,
        }
        res = self.client.table("alert_runs").insert(payload).execute()
        return _row_to_alert_run(res.data[0])

    def list_alert_runs(self, user_id: str, *, limit: int = 20) -> list[AlertRunRecord]:
        res = (
            self.client.table("alert_runs")
            .select("*")
            .eq("user_id", user_id)
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [_row_to_alert_run(row) for row in (res.data or [])]

    def get_latest_alert_run_for_subscription(
        self,
        user_id: str,
        subscription_id: str,
    ) -> AlertRunRecord | None:
        res = (
            self.client.table("alert_runs")
            .select("*")
            .eq("user_id", user_id)
            .eq("subscription_id", subscription_id)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        return _row_to_alert_run(res.data[0])

    def admin_list_alert_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[AlertRunRecord]:
        query = self.client.table("alert_runs").select("*").order("started_at", desc=True).range(offset, offset + limit - 1)
        if status:
            query = query.eq("status", status)
        res = query.execute()
        return [_row_to_alert_run(row) for row in (res.data or [])]

    def create_scrape_run(
        self,
        *,
        correlation_id: str,
        user_id: str | None,
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
        payload = {
            "correlation_id": correlation_id,
            "user_id": user_id,
            "anon_key": anon_key,
            "trigger_source": trigger_source,
            "status": status,
            "location": location,
            "make": make,
            "model": model,
            "vehicle_category": vehicle_category,
            "vehicle_condition": vehicle_condition,
            "inventory_scope": inventory_scope,
            "radius_miles": radius_miles,
            "requested_max_dealerships": requested_max_dealerships,
            "requested_max_pages_per_dealer": requested_max_pages_per_dealer,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
        }
        res = self.client.table("scrape_runs").insert(payload).execute()
        return _row_to_scrape_run(res.data[0])

    def finalize_scrape_run(
        self,
        scrape_run_id: str,
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
        updates = {
            "status": status,
            "result_count": result_count,
            "dealer_discovery_count": dealer_discovery_count,
            "dealer_deduped_count": dealer_deduped_count,
            "dealerships_attempted": dealerships_attempted,
            "dealerships_succeeded": dealerships_succeeded,
            "dealerships_failed": dealerships_failed,
            "error_count": error_count,
            "warning_count": warning_count,
            "error_message": error_message,
            "summary_json": summary,
            "economics_json": economics,
            "listings_snapshot_json": listings_snapshot if listings_snapshot else None,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(completed_at)),
        }
        self.client.table("scrape_runs").update(updates).eq("id", scrape_run_id).execute()
        res = self.client.table("scrape_runs").select("*").eq("id", scrape_run_id).limit(1).execute()
        return _row_to_scrape_run(res.data[0])

    def add_scrape_event(
        self,
        *,
        scrape_run_id: str,
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
        res = self.client.table("scrape_events").insert(
            {
                "scrape_run_id": scrape_run_id,
                "correlation_id": correlation_id,
                "sequence_no": sequence_no,
                "event_type": event_type,
                "phase": phase,
                "level": level,
                "message": message,
                "dealership_name": dealership_name,
                "dealership_website": dealership_website,
                "payload_json": payload,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(created_at)),
            }
        ).execute()
        return _row_to_scrape_event(res.data[0])

    def list_scrape_runs(
        self,
        *,
        user_id: str | None = None,
        anon_key: str | None = None,
        limit: int = 20,
    ) -> list[ScrapeRunRecord]:
        if user_id is None and not anon_key:
            return []
        query = self.client.table("scrape_runs").select("*").order("started_at", desc=True).limit(limit)
        if user_id is not None:
            query = query.eq("user_id", user_id)
        else:
            query = query.eq("anon_key", anon_key)
        res = query.execute()
        return [_row_to_scrape_run(row) for row in (res.data or [])]

    def count_running_scrape_runs(
        self,
        *,
        user_id: str | None = None,
        anon_key: str | None = None,
        since_ts: float | None = None,
    ) -> int:
        if user_id is None and not anon_key:
            return 0
        query = self.client.table("scrape_runs").select("id").eq("status", "running")
        if user_id is not None:
            query = query.eq("user_id", user_id)
        else:
            query = query.eq("anon_key", anon_key)
        if since_ts is not None:
            threshold = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since_ts))
            query = query.gte("started_at", threshold)
        res = query.execute()
        return len(res.data or [])

    def admin_list_scrape_runs(self, *, limit: int = 20, offset: int = 0, status: str | None = None) -> list[ScrapeRunRecord]:
        query = self.client.table("scrape_runs").select("*").order("started_at", desc=True).range(offset, offset + limit - 1)
        if status:
            query = query.eq("status", status)
        res = query.execute()
        return [_row_to_scrape_run(row) for row in (res.data or [])]

    def count_admin_scrape_runs(self, *, status: str | None = None) -> int:
        query = self.client.table("scrape_runs").select("id")
        if status:
            query = query.eq("status", status)
        res = query.execute()
        return len(res.data or [])

    def get_scrape_run(
        self,
        correlation_id: str,
        *,
        user_id: str | None = None,
        anon_key: str | None = None,
    ) -> ScrapeRunRecord | None:
        if user_id is None and not anon_key:
            return None
        query = (
            self.client.table("scrape_runs")
            .select("*")
            .eq("correlation_id", correlation_id)
            .order("started_at", desc=True)
            .limit(1)
        )
        if user_id is not None:
            query = query.eq("user_id", user_id)
        else:
            query = query.eq("anon_key", anon_key)
        res = query.execute()
        if not res.data:
            return None
        return _row_to_scrape_run(res.data[0])

    def admin_get_scrape_run(self, correlation_id: str) -> ScrapeRunRecord | None:
        res = (
            self.client.table("scrape_runs")
            .select("*")
            .eq("correlation_id", correlation_id)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        return _row_to_scrape_run(res.data[0])

    def admin_close_stuck_running_scrape_run(self, correlation_id: str) -> ScrapeRunRecord:
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

    def list_scrape_events(self, scrape_run_id: str, *, limit: int = 200) -> list[ScrapeEventRecord]:
        res = (
            self.client.table("scrape_events")
            .select("*")
            .eq("scrape_run_id", scrape_run_id)
            .order("sequence_no")
            .limit(limit)
            .execute()
        )
        return [_row_to_scrape_event(row) for row in (res.data or [])]

    def record_admin_audit_event(
        self,
        *,
        actor_user_id: str | None,
        actor_email: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        summary: str,
        payload: dict[str, Any],
    ) -> AdminAuditLogRecord | None:
        try:
            res = self.client.table("admin_audit_logs").insert(
                {
                    "actor_user_id": actor_user_id,
                    "actor_email": actor_email,
                    "action": action,
                    "target_type": target_type,
                    "target_id": target_id,
                    "summary": summary,
                    "payload_json": payload,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time())),
                }
            ).execute()
            if not res.data:
                return None
            return _row_to_admin_audit_log(res.data[0])
        except Exception as exc:
            logger.warning("admin audit logging unavailable: %s", exc)
            return None

    def list_admin_audit_logs(self, *, limit: int = 50, offset: int = 0) -> list[AdminAuditLogRecord]:
        try:
            res = (
                self.client.table("admin_audit_logs")
                .select("*")
                .order("created_at", desc=True)
                .range(offset, offset + limit - 1)
                .execute()
            )
            return [_row_to_admin_audit_log(row) for row in (res.data or [])]
        except Exception as exc:
            logger.warning("admin audit log unavailable: %s", exc)
            return []


def _row_to_user(row: dict[str, Any]) -> UserRecord:
    ent = row.get("entitlements_json") or {}
    return UserRecord(
        id=str(row["id"]),
        email=str(row["email"]),
        tier=str(row["tier"]),
        is_admin=bool(row.get("is_admin") or False),
        stripe_customer_id=row.get("stripe_customer_id"),
        stripe_subscription_id=row.get("stripe_subscription_id"),
        stripe_metered_item_id=row.get("stripe_metered_item_id"),
        entitlements=ent,
        created_at=_ts(row.get("created_at")),
        updated_at=_ts(row.get("updated_at")),
    )


def _row_to_alert_subscription(row: dict[str, Any]) -> AlertSubscriptionRecord:
    return AlertSubscriptionRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        criteria=dict(row.get("criteria_json") or {}),
        cadence=str(row["cadence"]),
        day_of_week=int(row["day_of_week"]) if row.get("day_of_week") is not None else None,
        hour_local=int(row["hour_local"]),
        timezone=str(row["timezone"]),
        deliver_csv=bool(row.get("deliver_csv")),
        only_send_on_changes=bool(row.get("only_send_on_changes")),
        include_new_listings=bool(row.get("include_new_listings", True)),
        include_price_drops=bool(row.get("include_price_drops", True)),
        min_price_drop_usd=_maybe_float(row.get("min_price_drop_usd")),
        is_active=bool(row.get("is_active")),
        next_run_at=_ts(row.get("next_run_at")),
        last_run_at=_ts(row.get("last_run_at")) if row.get("last_run_at") is not None else None,
        last_run_status=str(row["last_run_status"]) if row.get("last_run_status") is not None else None,
        last_result_count=int(row["last_result_count"]) if row.get("last_result_count") is not None else None,
        last_error=str(row["last_error"]) if row.get("last_error") is not None else None,
        created_at=_ts(row.get("created_at")),
        updated_at=_ts(row.get("updated_at")),
    )


def _row_to_alert_run(row: dict[str, Any]) -> AlertRunRecord:
    return AlertRunRecord(
        id=str(row["id"]),
        subscription_id=str(row["subscription_id"]),
        user_id=str(row["user_id"]),
        trigger_source=str(row["trigger_source"]),
        status=str(row["status"]),
        result_count=int(row.get("result_count") or 0),
        emailed=bool(row.get("emailed")),
        csv_attached=bool(row.get("csv_attached")),
        error_message=str(row["error_message"]) if row.get("error_message") is not None else None,
        summary=dict(row.get("summary_json") or {}),
        started_at=_ts(row.get("started_at")),
        completed_at=_ts(row.get("completed_at")) if row.get("completed_at") is not None else None,
    )


def _row_to_saved_search(row: dict[str, Any]) -> SavedSearchRecord:
    return SavedSearchRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        criteria=dict(row.get("criteria_json") or {}),
        created_at=_ts(row.get("created_at")),
        updated_at=_ts(row.get("updated_at")),
    )


def _row_to_inventory_history(row: dict[str, Any]) -> InventoryHistoryRecord:
    return InventoryHistoryRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        vehicle_key=str(row["vehicle_key"]),
        dealership_key=str(row.get("dealership_key") or ""),
        vin=str(row["vin"]) if row.get("vin") is not None else None,
        vehicle_identifier=str(row["vehicle_identifier"]) if row.get("vehicle_identifier") is not None else None,
        listing_url=str(row["listing_url"]) if row.get("listing_url") is not None else None,
        raw_title=str(row["raw_title"]) if row.get("raw_title") is not None else None,
        first_seen_at=_ts(row.get("first_seen_at")),
        last_seen_at=_ts(row.get("last_seen_at")),
        first_scrape_run_id=str(row["first_scrape_run_id"]) if row.get("first_scrape_run_id") is not None else None,
        latest_scrape_run_id=str(row["latest_scrape_run_id"]) if row.get("latest_scrape_run_id") is not None else None,
        seen_count=int(row.get("seen_count") or 0),
        first_price=_maybe_float(row.get("first_price")),
        previous_price=_maybe_float(row.get("previous_price")),
        latest_price=_maybe_float(row.get("latest_price")),
        lowest_price=_maybe_float(row.get("lowest_price")),
        highest_price=_maybe_float(row.get("highest_price")),
        latest_days_on_lot=_maybe_int(row.get("latest_days_on_lot")),
        price_history=_json_list(row.get("price_history_json")),
        created_at=_ts(row.get("created_at")),
        updated_at=_ts(row.get("updated_at")),
    )


def _row_to_scrape_run(row: dict[str, Any]) -> ScrapeRunRecord:
    return ScrapeRunRecord(
        id=str(row["id"]),
        correlation_id=str(row["correlation_id"]),
        user_id=str(row["user_id"]) if row.get("user_id") is not None else None,
        anon_key=str(row["anon_key"]) if row.get("anon_key") is not None else None,
        trigger_source=str(row["trigger_source"]),
        status=str(row["status"]),
        location=str(row["location"]),
        make=str(row["make"]),
        model=str(row["model"]),
        vehicle_category=str(row["vehicle_category"]),
        vehicle_condition=str(row["vehicle_condition"]),
        inventory_scope=str(row["inventory_scope"]),
        radius_miles=int(row.get("radius_miles") or 0),
        requested_max_dealerships=(
            int(row["requested_max_dealerships"]) if row.get("requested_max_dealerships") is not None else None
        ),
        requested_max_pages_per_dealer=(
            int(row["requested_max_pages_per_dealer"])
            if row.get("requested_max_pages_per_dealer") is not None
            else None
        ),
        result_count=int(row.get("result_count") or 0),
        dealer_discovery_count=(
            int(row["dealer_discovery_count"]) if row.get("dealer_discovery_count") is not None else None
        ),
        dealer_deduped_count=(
            int(row["dealer_deduped_count"]) if row.get("dealer_deduped_count") is not None else None
        ),
        dealerships_attempted=int(row.get("dealerships_attempted") or 0),
        dealerships_succeeded=int(row.get("dealerships_succeeded") or 0),
        dealerships_failed=int(row.get("dealerships_failed") or 0),
        error_count=int(row.get("error_count") or 0),
        warning_count=int(row.get("warning_count") or 0),
        error_message=str(row["error_message"]) if row.get("error_message") is not None else None,
        summary=dict(row.get("summary_json") or {}),
        economics=dict(row.get("economics_json") or {}),
        listings_snapshot=_coerce_listings_snapshot(row.get("listings_snapshot_json")),
        started_at=_ts(row.get("started_at")),
        completed_at=_ts(row.get("completed_at")) if row.get("completed_at") is not None else None,
    )


def _row_to_scrape_event(row: dict[str, Any]) -> ScrapeEventRecord:
    return ScrapeEventRecord(
        id=str(row["id"]),
        scrape_run_id=str(row["scrape_run_id"]),
        correlation_id=str(row["correlation_id"]),
        sequence_no=int(row.get("sequence_no") or 0),
        event_type=str(row["event_type"]),
        phase=str(row["phase"]) if row.get("phase") is not None else None,
        level=str(row["level"]),
        message=str(row["message"]),
        dealership_name=str(row["dealership_name"]) if row.get("dealership_name") is not None else None,
        dealership_website=str(row["dealership_website"]) if row.get("dealership_website") is not None else None,
        payload=dict(row.get("payload_json") or {}),
        created_at=_ts(row.get("created_at")),
    )


def _row_to_admin_audit_log(row: dict[str, Any]) -> AdminAuditLogRecord:
    return AdminAuditLogRecord(
        id=str(row["id"]),
        actor_user_id=str(row["actor_user_id"]) if row.get("actor_user_id") is not None else None,
        actor_email=str(row["actor_email"]) if row.get("actor_email") is not None else None,
        action=str(row["action"]),
        target_type=str(row["target_type"]),
        target_id=str(row["target_id"]) if row.get("target_id") is not None else None,
        summary=str(row["summary"]),
        payload=dict(row.get("payload_json") or {}),
        created_at=_ts(row.get("created_at")),
    )


def _coerce_listings_snapshot(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if isinstance(value, list):
        out = [x for x in value if isinstance(x, dict)]
        return out or None
    return None


def _json_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
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


def _ts(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc).timestamp()
    raise TypeError(f"Unsupported timestamp value: {value!r}")


_store: SupabaseAccountStore | None = None

def get_supabase_store() -> SupabaseAccountStore:
    global _store
    if _store is None:
        _store = SupabaseAccountStore()
    return _store
