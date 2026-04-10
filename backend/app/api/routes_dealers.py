"""Public API routes for the dealer directory."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.config import settings

router = APIRouter(prefix="/dealerships", tags=["dealerships"])


def _get_client() -> Any:
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    try:
        from app.db.supabase_store import get_supabase_store
        return get_supabase_store().client
    except Exception:
        return None


def _serialize_dealer(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a dealerships table row for API responses."""
    return {
        "id": row.get("id"),
        "slug": row.get("slug"),
        "place_id": row.get("place_id"),
        "name": row.get("name"),
        "address": row.get("address"),
        "website": row.get("website"),
        "lat": row.get("lat"),
        "lng": row.get("lng"),
        "phone": row.get("phone"),
        "rating": row.get("rating"),
        "review_count": row.get("review_count"),
        "description": row.get("description"),
        "hours_json": row.get("hours_json"),
        "photo_refs": row.get("photo_refs"),
        "social_links": row.get("social_links"),
        "oem_brands": row.get("oem_brands") or [],
        "services": row.get("services") or [],
        "enriched_at": row.get("enriched_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _get_dealer_stats(client: Any, dealership_id: str) -> dict[str, Any]:
    """
    Pull activity stats from scrape_events and inventory_history for a dealer.
    Uses the dealer's website/domain as the join key (dealership_key in inventory_history
    and dealership_website in scrape_events).
    """
    stats: dict[str, Any] = {
        "scrape_count": 0,
        "last_scraped_at": None,
        "avg_listing_count": None,
        "price_min": None,
        "price_median": None,
        "makes_in_inventory": [],
    }
    try:
        # Get website for this dealer to build the dealership_key
        dealer_res = client.table("dealerships").select("website").eq("id", dealership_id).single().execute()
        if not dealer_res.data or not dealer_res.data.get("website"):
            return stats
        website = dealer_res.data["website"]
        # Normalize domain the same way the rest of the system does
        from urllib.parse import urlparse
        domain = urlparse(website).netloc.lower().removeprefix("www.")

        # scrape_events: count successful scrapes and last timestamp
        events_res = (
            client.table("scrape_events")
            .select("created_at, payload_json")
            .ilike("dealership_website", f"%{domain}%")
            .eq("event_type", "dealer_done")
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        events = events_res.data or []
        stats["scrape_count"] = len(events)
        if events:
            stats["last_scraped_at"] = events[0]["created_at"]

        # inventory_history: price and make distribution
        history_res = (
            client.table("inventory_history")
            .select("price, make")
            .ilike("dealership_key", f"%{domain}%")
            .not_.is_("price", "null")
            .order("observed_at", desc=True)
            .limit(500)
            .execute()
        )
        history = history_res.data or []
        prices = [float(r["price"]) for r in history if r.get("price") and float(r["price"]) > 0]
        if prices:
            prices_sorted = sorted(prices)
            stats["price_min"] = prices_sorted[0]
            mid = len(prices_sorted) // 2
            stats["price_median"] = (
                (prices_sorted[mid - 1] + prices_sorted[mid]) / 2
                if len(prices_sorted) % 2 == 0
                else prices_sorted[mid]
            )

        makes: list[str] = sorted({
            r["make"] for r in history if r.get("make")
        })
        stats["makes_in_inventory"] = makes

    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Could not fetch dealer stats for %s: %s", dealership_id, exc)

    return stats


@router.get("")
async def list_dealerships(
    make: str | None = Query(default=None, description="Filter by OEM brand, e.g. Ford"),
    state: str | None = Query(default=None, description="Filter by US state abbreviation, e.g. TX"),
    city: str | None = Query(default=None, description="Filter by city name"),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """
    Paginated dealer directory with optional filters.
    Returns slim dealer cards suitable for directory listings.
    """
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Dealer directory is not available.")

    try:
        q = client.table("dealerships").select(
            "id, slug, name, address, website, lat, lng, rating, review_count, oem_brands, services, enriched_at"
        ).not_.is_("slug", "null")

        if make:
            # Filter via dealership_makes join using RPC is complex; filter by oem_brands array
            q = q.contains("oem_brands", [make])

        if state:
            # Address format: "..., City, ST XXXXX, USA" — simple ilike match
            q = q.ilike("address", f"%, {state.upper()} %")

        if city:
            q = q.ilike("address", f"%{city}%")

        q = q.order("rating", desc=True, nulls_last=True).range(offset, offset + limit - 1)
        res = q.execute()

        dealers = [
            {
                "slug": r.get("slug"),
                "name": r.get("name"),
                "address": r.get("address"),
                "website": r.get("website"),
                "lat": r.get("lat"),
                "lng": r.get("lng"),
                "rating": r.get("rating"),
                "review_count": r.get("review_count"),
                "oem_brands": r.get("oem_brands") or [],
                "services": r.get("services") or [],
                "enriched": r.get("enriched_at") is not None,
            }
            for r in (res.data or [])
        ]

        # Total count for pagination
        count_res = client.table("dealerships").select("id", count="exact").not_.is_("slug", "null").execute()
        total = count_res.count or 0

        return {"ok": True, "dealers": dealers, "total": total, "offset": offset, "limit": limit}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to query dealer directory: {exc}") from exc


@router.get("/{slug}")
async def get_dealership(slug: str) -> dict[str, Any]:
    """
    Full dealer profile page data including enriched details and activity stats.
    """
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Dealer directory is not available.")

    try:
        res = (
            client.table("dealerships")
            .select("*")
            .eq("slug", slug)
            .single()
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    if not res.data:
        raise HTTPException(status_code=404, detail=f"Dealer '{slug}' not found.")

    row = res.data
    dealer = _serialize_dealer(row)

    # Enrich with makes from dealership_makes table
    try:
        makes_res = (
            client.table("dealership_makes")
            .select("make, vehicle_category")
            .eq("dealership_id", row["id"])
            .execute()
        )
        dealer["makes"] = [
            {"make": m["make"], "category": m["vehicle_category"]}
            for m in (makes_res.data or [])
        ]
    except Exception:
        dealer["makes"] = []

    # Activity stats from scrape history
    dealer["stats"] = _get_dealer_stats(client, row["id"])

    return {"ok": True, "dealer": dealer}
