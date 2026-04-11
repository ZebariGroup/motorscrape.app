-- Extend the dealerships table with rich profile fields for the dealer directory.
-- These are populated asynchronously by the enrichment job on first dealer encounter.

ALTER TABLE public.dealerships
    ADD COLUMN IF NOT EXISTS slug TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS phone TEXT,
    ADD COLUMN IF NOT EXISTS hours_json JSONB,
    ADD COLUMN IF NOT EXISTS rating NUMERIC(3,1),
    ADD COLUMN IF NOT EXISTS review_count INTEGER,
    ADD COLUMN IF NOT EXISTS photo_refs JSONB,
    ADD COLUMN IF NOT EXISTS social_links JSONB,
    ADD COLUMN IF NOT EXISTS oem_brands TEXT[],
    ADD COLUMN IF NOT EXISTS services TEXT[],
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS google_details_json JSONB,
    ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enrichment_version INTEGER NOT NULL DEFAULT 0;

-- Index for slug lookups (dealer profile page)
CREATE UNIQUE INDEX IF NOT EXISTS dealerships_slug_idx ON public.dealerships (slug) WHERE slug IS NOT NULL;

-- Index to find un-enriched dealerships efficiently
CREATE INDEX IF NOT EXISTS dealerships_needs_enrichment_idx ON public.dealerships (id) WHERE enriched_at IS NULL;

-- Dealer reviews scraped from external sources (Google, Yelp, DealerRater, etc.)
CREATE TABLE IF NOT EXISTS public.dealer_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dealership_id UUID NOT NULL REFERENCES public.dealerships(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    author_name TEXT,
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    review_text TEXT,
    published_at TIMESTAMPTZ,
    source_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS dealer_reviews_dealership_idx ON public.dealer_reviews (dealership_id);
CREATE INDEX IF NOT EXISTS dealer_reviews_source_idx ON public.dealer_reviews (source);

-- RLS: dealer_reviews are public readable (same pattern as dealerships)
ALTER TABLE public.dealer_reviews ENABLE ROW LEVEL SECURITY;
CREATE POLICY "dealer_reviews_public_read" ON public.dealer_reviews FOR SELECT USING (true);

-- Update find_cached_dealerships to also return slug, rating, review_count for directory cards
-- Must DROP first because the return type is changing (adding slug, rating, review_count, lat, lng)
DROP FUNCTION IF EXISTS public.find_cached_dealerships(TEXT, TEXT, DOUBLE PRECISION, DOUBLE PRECISION, INTEGER);
CREATE OR REPLACE FUNCTION public.find_cached_dealerships(
    p_make TEXT,
    p_vehicle_category TEXT,
    p_lat DOUBLE PRECISION,
    p_lng DOUBLE PRECISION,
    p_radius_meters INTEGER
) RETURNS TABLE (
    place_id TEXT,
    name TEXT,
    address TEXT,
    website TEXT,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    distance_meters DOUBLE PRECISION,
    slug TEXT,
    rating NUMERIC,
    review_count INTEGER
) AS $$
DECLARE
    v_center extensions.geography(Point, 4326);
BEGIN
    v_center := ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)::extensions.geography;

    RETURN QUERY
    SELECT
        d.place_id,
        d.name,
        d.address,
        d.website,
        d.lat,
        d.lng,
        ST_Distance(d.location, v_center) as distance_meters,
        d.slug,
        d.rating,
        d.review_count
    FROM public.dealerships d
    JOIN public.dealership_makes dm ON d.id = dm.dealership_id
    WHERE dm.make = p_make
      AND dm.vehicle_category = p_vehicle_category
      AND ST_DWithin(d.location, v_center, p_radius_meters)
    ORDER BY distance_meters ASC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
