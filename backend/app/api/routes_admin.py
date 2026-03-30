"""Administrator-only endpoints for the Phase 1 console."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import AccessContext, get_access_context, require_admin_context
from app.config import settings
from app.db.account_store import (
    AdminAuditLogRecord,
    AlertRunRecord,
    AlertSubscriptionRecord,
    ScrapeEventRecord,
    ScrapeRunRecord,
    UserRecord,
    get_account_store,
)
from app.services.search_log_summary import build_dealer_outcomes, summarize_dealer_outcomes
from app.tiers import TierId, limits_for_tier

router = APIRouter(prefix="/admin", tags=["admin"])


def _period_utc() -> str:
    return time.strftime("%Y-%m", time.gmtime())


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _get_admin_ctx(
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> AccessContext:
    return require_admin_context(ctx)


def _serialize_user(record: UserRecord, *, period: str, store: Any) -> dict[str, Any]:
    included_used, overage_used = store.monthly_usage(record.id, period)
    lim = limits_for_tier(record.tier)
    return {
        "id": record.id,
        "email": record.email,
        "tier": record.tier,
        "is_admin": record.is_admin,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
        "stripe_customer_id": record.stripe_customer_id,
        "stripe_subscription_id": record.stripe_subscription_id,
        "has_metered_item": bool(record.stripe_metered_item_id),
        "usage": {
            "period": period,
            "included_used": included_used,
            "overage_used": overage_used,
            "included_limit": lim.included_searches_per_month,
        },
    }


def _serialize_run(record: ScrapeRunRecord, *, user_email: str | None) -> dict[str, Any]:
    places_metrics = {}
    if isinstance(record.summary, dict) and isinstance(record.summary.get("places_metrics"), dict):
        places_metrics = dict(record.summary["places_metrics"])
    return {
        "id": record.id,
        "correlation_id": record.correlation_id,
        "user_id": record.user_id,
        "user_email": user_email,
        "anon_key": record.anon_key,
        "status": record.status,
        "trigger_source": record.trigger_source,
        "location": record.location,
        "make": record.make,
        "model": record.model,
        "vehicle_category": record.vehicle_category,
        "vehicle_condition": record.vehicle_condition,
        "inventory_scope": record.inventory_scope,
        "radius_miles": record.radius_miles,
        "requested_max_dealerships": record.requested_max_dealerships,
        "requested_max_pages_per_dealer": record.requested_max_pages_per_dealer,
        "result_count": record.result_count,
        "dealer_discovery_count": record.dealer_discovery_count,
        "dealer_deduped_count": record.dealer_deduped_count,
        "dealerships_attempted": record.dealerships_attempted,
        "dealerships_succeeded": record.dealerships_succeeded,
        "dealerships_failed": record.dealerships_failed,
        "error_count": record.error_count,
        "warning_count": record.warning_count,
        "error_message": record.error_message,
        "places_metrics": places_metrics,
        "summary": record.summary,
        "economics": record.economics,
        "saved_listings_count": len(record.listings_snapshot) if record.listings_snapshot else 0,
        "started_at": _iso(record.started_at),
        "completed_at": _iso(record.completed_at),
    }


def _serialize_event(record: ScrapeEventRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "scrape_run_id": record.scrape_run_id,
        "correlation_id": record.correlation_id,
        "sequence_no": record.sequence_no,
        "event_type": record.event_type,
        "phase": record.phase,
        "level": record.level,
        "message": record.message,
        "dealership_name": record.dealership_name,
        "dealership_website": record.dealership_website,
        "payload": record.payload,
        "created_at": _iso(record.created_at),
    }


def _serialize_alert_subscription(record: AlertSubscriptionRecord, *, user_email: str | None) -> dict[str, Any]:
    return {
        "id": record.id,
        "user_id": record.user_id,
        "user_email": user_email,
        "name": record.name,
        "criteria": record.criteria,
        "cadence": record.cadence,
        "day_of_week": record.day_of_week,
        "hour_local": record.hour_local,
        "timezone": record.timezone,
        "deliver_csv": record.deliver_csv,
        "is_active": record.is_active,
        "next_run_at": _iso(record.next_run_at),
        "last_run_at": _iso(record.last_run_at),
        "last_run_status": record.last_run_status,
        "last_result_count": record.last_result_count,
        "last_error": record.last_error,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
    }


def _serialize_alert_run(record: AlertRunRecord, *, user_email: str | None) -> dict[str, Any]:
    return {
        "id": record.id,
        "subscription_id": record.subscription_id,
        "user_id": record.user_id,
        "user_email": user_email,
        "trigger_source": record.trigger_source,
        "status": record.status,
        "result_count": record.result_count,
        "emailed": record.emailed,
        "csv_attached": record.csv_attached,
        "error_message": record.error_message,
        "summary": record.summary,
        "started_at": _iso(record.started_at),
        "completed_at": _iso(record.completed_at),
    }


def _serialize_audit_log(record: AdminAuditLogRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "actor_user_id": record.actor_user_id,
        "actor_email": record.actor_email,
        "action": record.action,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "summary": record.summary,
        "payload": record.payload,
        "created_at": _iso(record.created_at),
    }


def _user_email_map(store: Any, runs: list[ScrapeRunRecord]) -> dict[str, str]:
    out: dict[str, str] = {}
    for user_id in {record.user_id for record in runs if record.user_id}:
        user = store.get_user_by_id(user_id)
        if user:
            out[user.id] = user.email
    return out


def _email_for_user(store: Any, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = store.get_user_by_id(user_id)
    return user.email if user else None


class UpdateAdminUserBody(BaseModel):
    tier: str | None = None
    is_admin: bool | None = None


@router.get("/overview")
def admin_overview(
    _ctx: Annotated[AccessContext, Depends(_get_admin_ctx)],
) -> dict[str, Any]:
    store = get_account_store(settings.accounts_db_path)
    period = _period_utc()
    seven_days_ago = time.time() - (7 * 86400)
    recent_users = store.list_users(limit=5)
    recent_runs = store.admin_list_scrape_runs(limit=5)
    user_email_by_id = _user_email_map(store, recent_runs)
    return {
        "stats": {
            "total_users": sum(store.count_users_by_tier().values()),
            "users_by_tier": store.count_users_by_tier(),
            "searches_this_month": store.total_searches_in_period(period),
            "overage_searches_this_month": store.total_overage_searches_in_period(period),
            "recent_signups_last_7d": store.count_recent_users(since_ts=seven_days_ago),
            "failed_runs_last_7d": store.count_scrape_runs(since_ts=seven_days_ago, status="failed"),
            "active_alerts": store.count_alert_subscriptions(active_only=True),
            "alerts_due_now": store.count_alert_subscriptions(active_only=True, due_before_ts=time.time()),
            "failed_alert_runs_last_7d": store.count_alert_runs(since_ts=seven_days_ago, status="failed"),
        },
        "recent_users": [_serialize_user(record, period=period, store=store) for record in recent_users],
        "recent_runs": [
            _serialize_run(record, user_email=user_email_by_id.get(record.user_id or ""))
            for record in recent_runs
        ],
    }


@router.get("/users")
def admin_list_users(
    _ctx: Annotated[AccessContext, Depends(_get_admin_ctx)],
    query: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    store = get_account_store(settings.accounts_db_path)
    period = _period_utc()
    users = store.list_users(limit=limit, offset=offset, query=query)
    return {
        "users": [_serialize_user(record, period=period, store=store) for record in users],
        "total": store.count_users(query=query),
        "limit": limit,
        "offset": offset,
    }


@router.patch("/users/{user_id}")
def admin_update_user(
    user_id: str,
    body: UpdateAdminUserBody,
    ctx: Annotated[AccessContext, Depends(_get_admin_ctx)],
) -> dict[str, Any]:
    if body.tier is None and body.is_admin is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No updates provided.")
    store = get_account_store(settings.accounts_db_path)
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if body.tier is not None:
        valid_tiers = {tier.value for tier in TierId if tier is not TierId.ANONYMOUS}
        if body.tier not in valid_tiers:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid tier.")
        store.set_tier(user_id, body.tier)
    if body.is_admin is not None:
        store.set_admin(user_id, body.is_admin)
    updated = store.get_user_by_id(user_id)
    assert updated is not None
    store.record_admin_audit_event(
        actor_user_id=ctx.user_id,
        actor_email=ctx.email,
        action="user_updated",
        target_type="user",
        target_id=user_id,
        summary=f"Updated {updated.email}",
        payload={
            "tier": updated.tier,
            "is_admin": updated.is_admin,
        },
    )
    return {"user": _serialize_user(updated, period=_period_utc(), store=store)}


@router.get("/users/{user_id}")
def admin_get_user_detail(
    user_id: str,
    _ctx: Annotated[AccessContext, Depends(_get_admin_ctx)],
) -> dict[str, Any]:
    store = get_account_store(settings.accounts_db_path)
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    period = _period_utc()
    search_runs = store.list_scrape_runs(user_id=user_id, limit=10)
    alert_subscriptions = store.list_alert_subscriptions(user_id)
    alert_runs = store.list_alert_runs(user_id, limit=10)
    audit_logs = [
        record
        for record in store.list_admin_audit_logs(limit=100)
        if record.target_type == "user" and record.target_id == user_id
    ][:20]
    return {
        "user": _serialize_user(user, period=period, store=store),
        "search_runs": [_serialize_run(record, user_email=user.email) for record in search_runs],
        "alert_subscriptions": [
            _serialize_alert_subscription(record, user_email=user.email) for record in alert_subscriptions
        ],
        "alert_runs": [_serialize_alert_run(record, user_email=user.email) for record in alert_runs],
        "audit_logs": [_serialize_audit_log(record) for record in audit_logs],
    }


@router.get("/search-runs")
def admin_list_search_runs(
    _ctx: Annotated[AccessContext, Depends(_get_admin_ctx)],
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
) -> dict[str, Any]:
    store = get_account_store(settings.accounts_db_path)
    runs = store.admin_list_scrape_runs(limit=limit, offset=offset, status=status_filter)
    user_email_by_id = _user_email_map(store, runs)
    return {
        "runs": [_serialize_run(record, user_email=user_email_by_id.get(record.user_id or "")) for record in runs],
        "total": store.count_admin_scrape_runs(status=status_filter),
        "limit": limit,
        "offset": offset,
    }


@router.post("/search-runs/{correlation_id}/close-stuck")
def admin_close_stuck_search_run(
    correlation_id: str,
    ctx: Annotated[AccessContext, Depends(_get_admin_ctx)],
) -> dict[str, Any]:
    """
    Mark a scrape run that is still ``running`` in the database as failed.

    Use when the interactive stream ended without ``finalize`` (e.g. tab closed mid-search,
    serverless timeout, or hung worker). This only updates the database row; it does not cancel
    work on another server instance.
    """
    store = get_account_store(settings.accounts_db_path)
    try:
        updated = store.admin_close_stuck_running_scrape_run(correlation_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Search run not found.")
    except ValueError as exc:
        status_label = str(exc) if exc.args else "unknown"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Run is not in running state (status={status_label}).",
        )
    user_email = None
    if updated.user_id:
        user = store.get_user_by_id(updated.user_id)
        user_email = user.email if user else None
    store.record_admin_audit_event(
        actor_user_id=ctx.user_id,
        actor_email=ctx.email,
        action="close_stuck_scrape_run",
        target_type="scrape_run",
        target_id=updated.correlation_id,
        summary=f"Closed stuck running run {updated.correlation_id}",
        payload={"scrape_run_id": updated.id, "correlation_id": updated.correlation_id},
    )
    return {"run": _serialize_run(updated, user_email=user_email)}


@router.get("/search-runs/{correlation_id}")
def admin_get_search_run(
    correlation_id: str,
    _ctx: Annotated[AccessContext, Depends(_get_admin_ctx)],
) -> dict[str, Any]:
    store = get_account_store(settings.accounts_db_path)
    run = store.admin_get_scrape_run(correlation_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Search log not found.")
    user_email = None
    if run.user_id:
        user = store.get_user_by_id(run.user_id)
        user_email = user.email if user else None
    events = store.list_scrape_events(run.id)
    dealer_outcomes = build_dealer_outcomes(events)
    return {
        "run": _serialize_run(run, user_email=user_email),
        "events": [_serialize_event(record) for record in events],
        "dealer_outcomes": dealer_outcomes,
        "dealer_summary": summarize_dealer_outcomes(dealer_outcomes),
    }


@router.get("/alerts/health")
def admin_alert_health(
    _ctx: Annotated[AccessContext, Depends(_get_admin_ctx)],
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    store = get_account_store(settings.accounts_db_path)
    due_subscriptions = store.admin_list_alert_subscriptions(limit=limit, offset=0, due_only=True)
    recent_alert_runs = store.admin_list_alert_runs(limit=limit, offset=0)
    return {
        "due_subscriptions": [
            _serialize_alert_subscription(record, user_email=_email_for_user(store, record.user_id))
            for record in due_subscriptions
        ],
        "recent_alert_runs": [
            _serialize_alert_run(record, user_email=_email_for_user(store, record.user_id))
            for record in recent_alert_runs
        ],
    }


@router.get("/audit-log")
def admin_audit_log(
    _ctx: Annotated[AccessContext, Depends(_get_admin_ctx)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    store = get_account_store(settings.accounts_db_path)
    logs = store.list_admin_audit_logs(limit=limit, offset=offset)
    return {
        "logs": [_serialize_audit_log(record) for record in logs],
        "limit": limit,
        "offset": offset,
    }
