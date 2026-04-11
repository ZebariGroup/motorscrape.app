import asyncio
import logging

from app.config import settings
from app.schemas import DealershipFound

logger = logging.getLogger(__name__)

def _get_client():
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    try:
        from app.db.supabase_store import get_supabase_store
        return get_supabase_store().client
    except Exception as e:
        logger.error(f"Failed to get Supabase client: {e}")
        return None

def check_supabase_cache(
    make: str,
    vehicle_category: str,
    lat: float,
    lng: float,
    radius_miles: int,
) -> list[DealershipFound] | None:
    client = _get_client()
    if not client:
        return None

    # Only cache searches that have a make
    if not make:
        return None

    radius_meters = int(radius_miles * 1609.34)

    try:
        # Check if search is covered
        is_covered_res = client.rpc(
            "is_search_covered",
            {
                "p_make": make.strip().lower(),
                "p_vehicle_category": vehicle_category.strip().lower(),
                "p_lat": lat,
                "p_lng": lng,
                "p_radius_meters": radius_meters,
                "p_max_age_days": max(
                    1,
                    int(getattr(settings, "places_supabase_region_cache_max_age_days", 30) or 0),
                ),
            }
        ).execute()

        if not is_covered_res.data:
            return None

        # It is covered, fetch the dealerships
        dealerships_res = client.rpc(
            "find_cached_dealerships",
            {
                "p_make": make.strip().lower(),
                "p_vehicle_category": vehicle_category.strip().lower(),
                "p_lat": lat,
                "p_lng": lng,
                "p_radius_meters": radius_meters
            }
        ).execute()

        results = []
        for row in dealerships_res.data or []:
            results.append(
                DealershipFound(
                    place_id=row["place_id"],
                    name=row["name"],
                    address=row["address"],
                    website=row["website"] or "",
                    lat=row.get("lat"),
                    lng=row.get("lng"),
                    discovery_source="supabase_cache",
                    slug=row.get("slug"),
                )
            )
        return results or None

    except Exception as e:
        logger.error(f"Supabase cache check failed: {e}")
        return None

def save_to_supabase_cache(
    make: str,
    vehicle_category: str,
    lat: float,
    lng: float,
    radius_miles: int,
    dealerships: list[DealershipFound]
) -> None:
    client = _get_client()
    if not client:
        return

    # Only cache searches that have a make
    if not make:
        return

    radius_meters = int(radius_miles * 1609.34)
    make_q = make.strip().lower()
    cat_q = vehicle_category.strip().lower()

    try:
        from app.services.dealer_enrichment import generate_slug

        # 1. Insert dealerships
        persisted_count = 0
        for d in dealerships:
            if d.lat is None or d.lng is None:
                continue

            # Upsert dealership and get id + slug
            d_res = client.table("dealerships").upsert({
                "place_id": d.place_id,
                "name": d.name,
                "address": d.address,
                "website": d.website,
                "lat": d.lat,
                "lng": d.lng,
                "location": f"SRID=4326;POINT({d.lng} {d.lat})"
            }, on_conflict="place_id").execute()

            if d_res.data and len(d_res.data) > 0:
                persisted_count += 1
                d_row = d_res.data[0]
                d_id = d_row["id"]

                # Set a provisional slug and seed oem_brands immediately if the
                # row has none. The directory query filters by slug IS NOT NULL,
                # so without this new dealers are invisible until async enrichment
                # completes — which may never happen if the process exits first.
                if not d_row.get("slug"):
                    provisional_slug = generate_slug(d.name, d.address)
                    # Also seed oem_brands with the search make so the brand
                    # filter in the directory works before full enrichment.
                    existing_brands: list[str] = d_row.get("oem_brands") or []
                    make_display = make.strip()
                    seed_brands = (
                        list({*existing_brands, make_display})
                        if make_display and make_display not in existing_brands
                        else existing_brands or [make_display]
                    )
                    try:
                        slug_res = client.table("dealerships").update(
                            {"slug": provisional_slug, "oem_brands": seed_brands}
                        ).eq("id", d_id).execute()
                        if slug_res.data:
                            d_row["slug"] = provisional_slug
                            logger.info(
                                "Set provisional slug '%s' and brands %s for new dealer %s",
                                provisional_slug,
                                seed_brands,
                                d.name,
                            )
                    except Exception as slug_exc:
                        logger.warning(
                            "Could not set provisional slug for %s: %s", d.name, slug_exc
                        )

                # Propagate slug so SSE events can link to the dealer profile page
                if d_row.get("slug"):
                    d.slug = d_row["slug"]

                # Fire enrichment for dealers that haven't been enriched yet.
                # This is non-blocking: the search continues while enrichment runs.
                # Enrichment refines the slug (collision resolution), adds rating,
                # photos, phone, social links, and OEM brands from the homepage.
                if not d_row.get("enriched_at"):
                    try:
                        from app.services.dealer_enrichment import enrich_dealer
                        asyncio.create_task(
                            enrich_dealer(
                                dealership_id=d_id,
                                place_id=d.place_id,
                                name=d.name,
                                address=d.address,
                                website=d.website,
                            )
                        )
                    except RuntimeError:
                        # No running event loop (e.g. sync tests) — skip silently
                        pass
                    except Exception as enrich_exc:
                        logger.warning("Could not schedule dealer enrichment for %s: %s", d.name, enrich_exc)

                # Link make in the junction table
                client.table("dealership_makes").upsert({
                    "dealership_id": d_id,
                    "make": make_q,
                    "vehicle_category": cat_q
                }, on_conflict="dealership_id,make,vehicle_category").execute()

                # Also keep oem_brands column in sync so the directory brand filter works.
                # The column stores display-cased make names; add the search make if missing.
                make_display = make.strip()
                existing_brands: list[str] = d_row.get("oem_brands") or []
                if make_display and make_display not in existing_brands:
                    updated_brands = list({*existing_brands, make_display})
                    try:
                        client.table("dealerships").update(
                            {"oem_brands": updated_brands}
                        ).eq("id", d_id).execute()
                    except Exception as brands_exc:
                        logger.warning(
                            "Could not sync oem_brands for %s: %s", d.name, brands_exc
                        )

        coverage_confident = persisted_count > 0 and persisted_count == len(dealerships)
        if not coverage_confident:
            if persisted_count > 0:
                logger.debug(
                    "Skipping Supabase region coverage write for %s/%s: persisted %s of %s dealerships",
                    make_q,
                    cat_q,
                    persisted_count,
                    len(dealerships),
                )
            return

        # 2. Record the search region
        client.table("search_regions").insert({
            "make": make_q,
            "vehicle_category": cat_q,
            "lat": lat,
            "lng": lng,
            "center": f"SRID=4326;POINT({lng} {lat})",
            "radius_meters": radius_meters,
            "dealership_count": persisted_count,
            "coverage_confident": True,
        }).execute()

    except Exception as e:
        logger.error(f"Supabase cache save failed: {e}")

