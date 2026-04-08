from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import AccessContext, get_access_context
from app.config import settings
from app.db.account_store import ScrapeEventRecord, ScrapeRunRecord, get_account_store
from app.services.search_errors import extract_search_error
from app.services.search_log_summary import build_dealer_outcomes, summarize_dealer_outcomes

router = APIRouter(prefix="/search/logs", tags=["search-logs"])


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _serialize_run(record: ScrapeRunRecord) -> dict[str, Any]:
    snap = record.listings_snapshot
    saved_n = len(snap) if snap else 0
    places_metrics = {}
    if isinstance(record.summary, dict) and isinstance(record.summary.get("places_metrics"), dict):
        places_metrics = dict(record.summary["places_metrics"])
    error = extract_search_error(record.summary)
    return {
        "id": record.id,
        "correlation_id": record.correlation_id,
        "status": record.status,
        "trigger_source": record.trigger_source,
        "location": record.location,
        "make": record.make,
        "model": record.model,
        "vehicle_category": record.vehicle_category,
        "vehicle_condition": record.vehicle_condition,
        "inventory_scope": record.inventory_scope,
        "prefer_small_dealers": record.prefer_small_dealers,
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
        "error_code": error.get("code") if error else None,
        "error_phase": error.get("phase") if error else None,
        "error": error,
        "places_metrics": places_metrics,
        "summary": record.summary,
        "economics": record.economics,
        "started_at": _iso(record.started_at),
        "completed_at": _iso(record.completed_at),
        "has_saved_results": saved_n > 0,
        "saved_listings_count": saved_n,
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


def _actor_filter(ctx: AccessContext) -> dict[str, str | None]:
    return {"user_id": ctx.user_id, "anon_key": ctx.anon_key}


@router.get("")
def list_search_logs(
    ctx: Annotated[AccessContext, Depends(get_access_context)],
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    store = get_account_store(settings.accounts_db_path)
    # Pull extra rows so scheduled alert runs do not crowd out interactive searches.
    raw_limit = min(limit * 8, 200)
    runs = store.list_scrape_runs(limit=raw_limit, **_actor_filter(ctx))
    interactive = [r for r in runs if r.trigger_source == "interactive"][:limit]
    return {"runs": [_serialize_run(record) for record in interactive]}


@router.get("/{correlation_id}")
def get_search_log(
    correlation_id: str,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
    include_events: bool = Query(default=True),
) -> dict[str, Any]:
    store = get_account_store(settings.accounts_db_path)
    run = store.get_scrape_run(correlation_id, **_actor_filter(ctx))
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Search log not found.")
    listings = run.listings_snapshot if run.listings_snapshot else []
    if include_events:
        events = store.list_scrape_events(run.id)
        dealer_outcomes = build_dealer_outcomes(events)
        return {
            "run": _serialize_run(run),
            "events": [_serialize_event(record) for record in events],
            "dealer_outcomes": dealer_outcomes,
            "dealer_summary": summarize_dealer_outcomes(dealer_outcomes),
            "listings": listings,
        }
    return {
        "run": _serialize_run(run),
        "events": [],
        "dealer_outcomes": [],
        "dealer_summary": summarize_dealer_outcomes([]),
        "listings": listings,
    }
