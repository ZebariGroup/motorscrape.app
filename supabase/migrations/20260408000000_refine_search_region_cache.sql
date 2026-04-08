ALTER TABLE public.search_regions
    ADD COLUMN IF NOT EXISTS dealership_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE public.search_regions
    ADD COLUMN IF NOT EXISTS coverage_confident BOOLEAN NOT NULL DEFAULT FALSE;

WITH region_counts AS (
    SELECT
        sr.id,
        COUNT(DISTINCT d.id) FILTER (WHERE dm.dealership_id IS NOT NULL) AS dealer_count
    FROM public.search_regions sr
    LEFT JOIN public.dealerships d
        ON extensions.ST_DWithin(d.location, sr.center, sr.radius_meters::double precision)
    LEFT JOIN public.dealership_makes dm
        ON d.id = dm.dealership_id
       AND dm.make = sr.make
       AND dm.vehicle_category = sr.vehicle_category
    GROUP BY sr.id
)
UPDATE public.search_regions sr
SET dealership_count = COALESCE(rc.dealer_count, 0),
    coverage_confident = COALESCE(rc.dealer_count, 0) > 0
FROM region_counts rc
WHERE sr.id = rc.id;

CREATE OR REPLACE FUNCTION public.is_search_covered(
    p_make TEXT,
    p_vehicle_category TEXT,
    p_lat DOUBLE PRECISION,
    p_lng DOUBLE PRECISION,
    p_radius_meters INTEGER,
    p_max_age_days INTEGER DEFAULT 30
) RETURNS BOOLEAN AS $$
DECLARE
    v_new_center extensions.geography(Point, 4326);
    v_is_covered BOOLEAN;
BEGIN
    v_new_center := extensions.ST_SetSRID(extensions.ST_MakePoint(p_lng, p_lat), 4326)::extensions.geography;

    SELECT EXISTS (
        SELECT 1
        FROM public.search_regions
        WHERE make = p_make
          AND vehicle_category = p_vehicle_category
          AND coverage_confident = TRUE
          AND dealership_count > 0
          AND last_searched_at >= (now() - (p_max_age_days || ' days')::interval)
          AND extensions.ST_Distance(center, v_new_center) + p_radius_meters <= radius_meters
    ) INTO v_is_covered;

    RETURN v_is_covered;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
