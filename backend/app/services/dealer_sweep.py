"""
Dealer directory sweep: systematically discover dealers across the US for all
major makes using the existing Google Places + Supabase cache pipeline.

Designed to be called periodically (via cron) in small batches so the total
Places API bill stays manageable.  The search_regions table acts as a ledger —
any (make, metro) pair already covered is skipped with no API call.

Run one batch manually:
    POST /server/admin/dealer-sweep/run?max_pairs=25
    Header: X-Sweep-Secret: <DEALER_SWEEP_SECRET>
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# US metro centers — lat/lng + human label used as the Places text query
# Covers all major population centers; ~30-mile radius each.
# ---------------------------------------------------------------------------
SWEEP_RADIUS_MILES = 30

US_METROS: list[tuple[float, float, str]] = [
    # Northeast
    (40.7128, -74.0060, "New York, NY"),
    (42.3601, -71.0589, "Boston, MA"),
    (39.9526, -75.1652, "Philadelphia, PA"),
    (42.8864, -78.8784, "Buffalo, NY"),
    (43.0481, -76.1474, "Syracuse, NY"),
    (43.1566, -77.6088, "Rochester, NY"),
    (40.7282, -74.0776, "Newark, NJ"),
    (41.7658, -72.6851, "Hartford, CT"),
    (42.7284, -73.6918, "Albany, NY"),
    # Mid-Atlantic / Southeast
    (38.9072, -77.0369, "Washington, DC"),
    (39.2904, -76.6122, "Baltimore, MD"),
    (36.8529, -75.9780, "Virginia Beach, VA"),
    (37.5407, -77.4360, "Richmond, VA"),
    (35.7796, -78.6382, "Raleigh, NC"),
    (35.2271, -80.8431, "Charlotte, NC"),
    (33.7490, -84.3880, "Atlanta, GA"),
    (30.3322, -81.6557, "Jacksonville, FL"),
    (27.9944, -82.4451, "Tampa, FL"),
    (25.7617, -80.1918, "Miami, FL"),
    (28.5383, -81.3792, "Orlando, FL"),
    # Midwest
    (41.8781, -87.6298, "Chicago, IL"),
    (42.3314, -83.0458, "Detroit, MI"),
    (39.9612, -82.9988, "Columbus, OH"),
    (41.4993, -81.6944, "Cleveland, OH"),
    (39.1031, -84.5120, "Cincinnati, OH"),
    (44.9778, -93.2650, "Minneapolis, MN"),
    (38.2527, -85.7585, "Louisville, KY"),
    (36.1627, -86.7816, "Nashville, TN"),
    (35.1495, -90.0490, "Memphis, TN"),
    (39.7684, -86.1581, "Indianapolis, IN"),
    (43.0731, -89.4012, "Madison, WI"),
    (44.5133, -88.0133, "Green Bay, WI"),
    (41.2565, -95.9345, "Omaha, NE"),
    (39.0997, -94.5786, "Kansas City, MO"),
    (38.6270, -90.1994, "St. Louis, MO"),
    # South / Plains
    (35.4676, -97.5164, "Oklahoma City, OK"),
    (36.1540, -95.9928, "Tulsa, OK"),
    (29.7604, -95.3698, "Houston, TX"),
    (32.7767, -96.7970, "Dallas, TX"),
    (30.2672, -97.7431, "Austin, TX"),
    (29.4241, -98.4936, "San Antonio, TX"),
    (31.7619, -106.4850, "El Paso, TX"),
    (32.4487, -99.7331, "Abilene, TX"),
    (44.0805, -103.2310, "Rapid City, SD"),
    # Mountain West
    (39.7392, -104.9903, "Denver, CO"),
    (40.7608, -111.8910, "Salt Lake City, UT"),
    (35.6870, -105.9378, "Santa Fe, NM"),
    (35.0844, -106.6504, "Albuquerque, NM"),
    (33.4484, -112.0740, "Phoenix, AZ"),
    (32.2226, -110.9747, "Tucson, AZ"),
    (36.1699, -115.1398, "Las Vegas, NV"),
    (39.5296, -119.8138, "Reno, NV"),
    (43.6187, -116.2146, "Boise, ID"),
    (46.8772, -113.9961, "Missoula, MT"),
    # Pacific Northwest
    (47.6062, -122.3321, "Seattle, WA"),
    (47.6588, -117.4260, "Spokane, WA"),
    (45.5051, -122.6750, "Portland, OR"),
    (44.0521, -123.0868, "Eugene, OR"),
    # California
    (37.7749, -122.4194, "San Francisco, CA"),
    (34.0522, -118.2437, "Los Angeles, CA"),
    (32.7157, -117.1611, "San Diego, CA"),
    (37.3382, -121.8863, "San Jose, CA"),
    (36.7378, -119.7871, "Fresno, CA"),
    (38.5816, -121.4944, "Sacramento, CA"),
    (33.8366, -117.9143, "Anaheim, CA"),
    (34.1083, -117.2898, "San Bernardino, CA"),
    # Alaska / Hawaii
    (61.2181, -149.9003, "Anchorage, AK"),
    (21.3069, -157.8583, "Honolulu, HI"),
]

# ---------------------------------------------------------------------------
# Makes to sweep — top volume brands for the US market
# ---------------------------------------------------------------------------
SWEEP_MAKES: list[str] = [
    "Toyota",
    "Ford",
    "Chevrolet",
    "Honda",
    "Nissan",
    "Hyundai",
    "Kia",
    "Jeep",
    "GMC",
    "Ram",
    "Subaru",
    "Volkswagen",
    "BMW",
    "Mercedes-Benz",
    "Audi",
    "Lexus",
    "Cadillac",
    "Buick",
    "Dodge",
    "Chrysler",
    "Mazda",
    "Acura",
    "Infiniti",
    "Lincoln",
    "Genesis",
    "Volvo",
    "Mitsubishi",
    "MINI",
    "Porsche",
    "Land Rover",
    "Jaguar",
    "Tesla",
    "Rivian",
]

SWEEP_VEHICLE_CATEGORY = "car"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles between two lat/lng points."""
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _get_supabase_client() -> Any | None:
    from app.config import settings
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    try:
        from app.db.supabase_store import get_supabase_store
        return get_supabase_store().client
    except Exception as exc:
        logger.error("Failed to get Supabase client: %s", exc)
        return None


def _load_covered_regions(client: Any) -> list[dict]:
    """
    Fetch all search_regions rows for sweep makes in a single query.
    Used to avoid calling is_search_covered() N times per batch.
    """
    try:
        makes_lower = [m.lower() for m in SWEEP_MAKES]
        res = (
            client.table("search_regions")
            .select("make,lat,lng,radius_meters,vehicle_category")
            .in_("make", makes_lower)
            .eq("vehicle_category", SWEEP_VEHICLE_CATEGORY)
            .eq("coverage_confident", True)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("Could not load covered search regions: %s", exc)
        return []


def _is_covered(
    make: str,
    lat: float,
    lng: float,
    radius_miles: float,
    covered_regions: list[dict],
) -> bool:
    """
    Return True if any existing search_region already covers this (make, center).
    A region covers our target if the target center is within the region's radius.
    """
    make_lower = make.lower()
    for region in covered_regions:
        if region.get("make") != make_lower:
            continue
        region_radius_miles = (region.get("radius_meters") or 0) / 1609.34
        dist_miles = _haversine_miles(lat, lng, float(region["lat"]), float(region["lng"]))
        if dist_miles <= region_radius_miles:
            return True
    return False


def _all_sweep_pairs() -> list[tuple[str, float, float, str]]:
    """All (make, lat, lng, label) pairs for the sweep grid."""
    return [
        (make, lat, lng, label)
        for make in SWEEP_MAKES
        for lat, lng, label in US_METROS
    ]


def _mark_region_covered(client: Any, make: str, lat: float, lng: float) -> None:
    """
    Explicitly insert a search_regions row for a (make, metro) pair that
    returned 0 dealers from Places.  Without this, the sweep would re-search
    the same empty regions on every run.
    """
    radius_meters = int(SWEEP_RADIUS_MILES * 1609.34)
    make_lower = make.lower()
    try:
        client.table("search_regions").insert({
            "make": make_lower,
            "vehicle_category": SWEEP_VEHICLE_CATEGORY,
            "lat": lat,
            "lng": lng,
            "center": f"SRID=4326;POINT({lng} {lat})",
            "radius_meters": radius_meters,
            "dealership_count": 0,
            "coverage_confident": True,
        }).execute()
        logger.debug("Sweep: marked zero-dealer region covered for %s @ (%.4f, %.4f)", make, lat, lng)
    except Exception as exc:
        logger.warning("Sweep: could not mark region covered for %s: %s", make, exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_sweep_batch(max_pairs: int = 25) -> dict[str, Any]:
    """
    Process up to `max_pairs` uncovered (make, metro) combinations:
      1. Load covered search_regions from Supabase in one query.
      2. Iterate the sweep grid, skipping already-covered pairs.
      3. For uncovered pairs, call Google Places Text Search and save to Supabase.
      4. Enrichment (phone, hours, photos) fires automatically via save_to_supabase_cache.

    Returns a stats dict: processed, dealers_found, skipped_cached, errors, remaining.
    """
    from app.services.places import find_dealerships
    from app.services.places_supabase import check_supabase_cache, save_to_supabase_cache

    stats: dict[str, Any] = {
        "processed": 0,
        "dealers_found": 0,
        "skipped_cached": 0,
        "errors": 0,
        "remaining_pairs": 0,
    }

    client = _get_supabase_client()
    if not client:
        stats["error"] = "Supabase not configured"
        return stats

    covered_regions = _load_covered_regions(client)
    all_pairs = _all_sweep_pairs()

    work_pairs: list[tuple[str, float, float, str]] = []
    remaining = 0
    for make, lat, lng, label in all_pairs:
        if _is_covered(make, lat, lng, SWEEP_RADIUS_MILES, covered_regions):
            continue
        if len(work_pairs) < max_pairs:
            work_pairs.append((make, lat, lng, label))
        else:
            remaining += 1

    stats["remaining_pairs"] = remaining

    for make, lat, lng, label in work_pairs:
        try:
            # Double-check via the live Supabase RPC (catches coverage added mid-batch
            # by enrichment tasks or concurrent sweep calls).
            live_cached = check_supabase_cache(
                make=make,
                vehicle_category=SWEEP_VEHICLE_CATEGORY,
                lat=lat,
                lng=lng,
                radius_miles=SWEEP_RADIUS_MILES,
            )
            if live_cached is not None:
                stats["skipped_cached"] += 1
                # Add to covered_regions so subsequent pairs in this batch benefit too
                covered_regions.append({
                    "make": make.lower(),
                    "lat": lat,
                    "lng": lng,
                    "radius_meters": SWEEP_RADIUS_MILES * 1609.34,
                    "vehicle_category": SWEEP_VEHICLE_CATEGORY,
                })
                continue

            logger.info("Sweep: searching %s dealers near %s", make, label)
            dealerships = await find_dealerships(
                location=label,
                make=make,
                vehicle_category=SWEEP_VEHICLE_CATEGORY,
                limit=20,
                radius_miles=SWEEP_RADIUS_MILES,
                location_center_override=(lat, lng),
            )

            if dealerships:
                save_to_supabase_cache(
                    make=make,
                    vehicle_category=SWEEP_VEHICLE_CATEGORY,
                    lat=lat,
                    lng=lng,
                    radius_miles=SWEEP_RADIUS_MILES,
                    dealerships=dealerships,
                )
                stats["dealers_found"] += len(dealerships)
            else:
                # Places returned 0 dealers for this pair.  save_to_supabase_cache
                # won't insert a search_regions row for empty results, so we do it
                # explicitly to prevent the same pair being re-searched every run.
                _mark_region_covered(client, make, lat, lng)

            # Mark locally so later pairs in this batch skip nearby metros for this make
            covered_regions.append({
                "make": make.lower(),
                "lat": lat,
                "lng": lng,
                "radius_meters": SWEEP_RADIUS_MILES * 1609.34,
                "vehicle_category": SWEEP_VEHICLE_CATEGORY,
            })
            stats["processed"] += 1

        except Exception as exc:
            logger.error("Sweep error for %s @ %s: %s", make, label, exc)
            stats["errors"] += 1

    return stats


def sweep_coverage_summary() -> dict[str, Any]:
    """
    Return a quick coverage report: how many (make, metro) pairs are covered
    vs. total, broken down by make.
    """
    client = _get_supabase_client()
    if not client:
        return {"error": "Supabase not configured"}

    covered_regions = _load_covered_regions(client)
    all_pairs = _all_sweep_pairs()
    total = len(all_pairs)
    covered_count = sum(
        1
        for make, lat, lng, _label in all_pairs
        if _is_covered(make, lat, lng, SWEEP_RADIUS_MILES, covered_regions)
    )

    by_make: dict[str, dict[str, int]] = {}
    for make in SWEEP_MAKES:
        total_for_make = len(US_METROS)
        covered_for_make = sum(
            1
            for lat, lng, _label in US_METROS
            if _is_covered(make, lat, lng, SWEEP_RADIUS_MILES, covered_regions)
        )
        by_make[make] = {"total": total_for_make, "covered": covered_for_make}

    return {
        "total_pairs": total,
        "covered_pairs": covered_count,
        "remaining_pairs": total - covered_count,
        "pct_complete": round(covered_count / total * 100, 1) if total else 0,
        "by_make": by_make,
    }
