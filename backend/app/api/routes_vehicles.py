"""Public API routes for vehicle sightings (national car database)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.config import settings

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def _get_client() -> Any:
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    try:
        from app.db.supabase_store import get_supabase_store
        return get_supabase_store().client
    except Exception:
        return None


@router.get("/sightings")
async def list_vehicle_sightings(
    make: str = Query(..., min_length=1),
    model: str = Query(""),
    state: str = Query(""),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return recent sightings for a make (and optional model/state) from the national DB."""
    client = _get_client()
    if client is None:
        return {"ok": True, "sightings": [], "total": 0}

    query = (
        client.table("vehicle_sightings")
        .select("make,model,search_location,search_state,result_count,price_min,price_max,price_avg,top_dealerships_json,scraped_at")
        .ilike("make", make.strip())
        .order("scraped_at", desc=True)
        .limit(limit)
    )
    if model.strip():
        query = query.ilike("model", model.strip())
    if state.strip():
        query = query.eq("search_state", state.strip().upper())

    try:
        res = query.execute()
    except Exception:
        return {"ok": True, "sightings": [], "total": 0}

    sightings = [_serialize_sighting(row) for row in (res.data or [])]
    return {"ok": True, "sightings": sightings, "total": len(sightings)}


@router.get("/sightings/summary")
async def vehicle_sightings_summary(
    make: str = Query(..., min_length=1),
    model: str = Query(""),
) -> dict[str, Any]:
    """Return aggregated stats per state for a make/model: sighting count, avg price, last seen."""
    client = _get_client()
    if client is None:
        return {"ok": True, "total_sightings": 0, "total_results": 0, "states": [], "price_min": None, "price_max": None, "price_avg": None}

    query = (
        client.table("vehicle_sightings")
        .select("search_state,search_location,result_count,price_min,price_max,price_avg,scraped_at")
        .ilike("make", make.strip())
        .order("scraped_at", desc=True)
        .limit(1000)
    )
    if model.strip():
        query = query.ilike("model", model.strip())

    try:
        res = query.execute()
    except Exception:
        return {"ok": True, "total_sightings": 0, "total_results": 0, "states": [], "price_min": None, "price_max": None, "price_avg": None}

    rows = res.data or []

    # Aggregate by state
    state_map: dict[str, dict[str, Any]] = {}
    all_prices: list[float] = []

    for row in rows:
        state = str(row.get("search_state") or "")
        if not state:
            state = "Other"
        if state not in state_map:
            state_map[state] = {
                "state": state,
                "sighting_count": 0,
                "total_results": 0,
                "last_scraped_at": None,
                "sample_locations": [],
            }
        bucket = state_map[state]
        bucket["sighting_count"] += 1
        bucket["total_results"] += int(row.get("result_count") or 0)

        scraped_at = str(row.get("scraped_at") or "")
        if bucket["last_scraped_at"] is None or scraped_at > bucket["last_scraped_at"]:
            bucket["last_scraped_at"] = scraped_at

        loc = str(row.get("search_location") or "")
        if loc and loc not in bucket["sample_locations"] and len(bucket["sample_locations"]) < 3:
            bucket["sample_locations"].append(loc)

        p_min = _maybe_float(row.get("price_min"))
        p_max = _maybe_float(row.get("price_max"))
        if p_min is not None:
            all_prices.append(p_min)
        if p_max is not None and p_max != p_min:
            all_prices.append(p_max)

    states = sorted(state_map.values(), key=lambda s: s["sighting_count"], reverse=True)

    price_min = min(all_prices) if all_prices else None
    price_max = max(all_prices) if all_prices else None
    price_avg = sum(all_prices) / len(all_prices) if all_prices else None

    return {
        "ok": True,
        "total_sightings": len(rows),
        "total_results": sum(int(r.get("result_count") or 0) for r in rows),
        "states": states,
        "price_min": price_min,
        "price_max": price_max,
        "price_avg": price_avg,
    }


def _serialize_sighting(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "make": row.get("make"),
        "model": row.get("model"),
        "search_location": row.get("search_location"),
        "search_state": row.get("search_state"),
        "result_count": row.get("result_count"),
        "price_min": row.get("price_min"),
        "price_max": row.get("price_max"),
        "price_avg": row.get("price_avg"),
        "top_dealerships": row.get("top_dealerships_json") or [],
        "scraped_at": row.get("scraped_at"),
    }


def _maybe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
