-- Enable PostGIS extension if not already enabled
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;

-- Dealerships table
CREATE TABLE IF NOT EXISTS public.dealerships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    place_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    website TEXT,
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    location extensions.geography(Point, 4326) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

-- Index for spatial queries
CREATE INDEX IF NOT EXISTS dealerships_location_idx ON public.dealerships USING GIST (location);

-- Dealership makes (many-to-many relationship)
CREATE TABLE IF NOT EXISTS public.dealership_makes (
    dealership_id UUID REFERENCES public.dealerships(id) ON DELETE CASCADE,
    make TEXT NOT NULL,
    vehicle_category TEXT NOT NULL DEFAULT 'car',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (dealership_id, make, vehicle_category)
);

-- Search regions cache
CREATE TABLE IF NOT EXISTS public.search_regions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    make TEXT NOT NULL,
    vehicle_category TEXT NOT NULL DEFAULT 'car',
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    center extensions.geography(Point, 4326) NOT NULL,
    radius_meters INTEGER NOT NULL,
    last_searched_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

-- Index for spatial queries on search regions
CREATE INDEX IF NOT EXISTS search_regions_center_idx ON public.search_regions USING GIST (center);

-- Function to check if a new search is covered by an existing search
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
    v_new_center := ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)::extensions.geography;
    
    SELECT EXISTS (
        SELECT 1 
        FROM public.search_regions
        WHERE make = p_make 
          AND vehicle_category = p_vehicle_category
          AND last_searched_at >= (now() - (p_max_age_days || ' days')::interval)
          -- The distance between the old center and new center, plus the new radius, 
          -- must be less than or equal to the old radius to be fully covered.
          AND ST_Distance(center, v_new_center) + p_radius_meters <= radius_meters
    ) INTO v_is_covered;
    
    RETURN v_is_covered;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to find dealerships for a specific make within a radius
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
    distance_meters DOUBLE PRECISION
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
        ST_Distance(d.location, v_center) as distance_meters
    FROM public.dealerships d
    JOIN public.dealership_makes dm ON d.id = dm.dealership_id
    WHERE dm.make = p_make 
      AND dm.vehicle_category = p_vehicle_category
      AND ST_DWithin(d.location, v_center, p_radius_meters)
    ORDER BY distance_meters ASC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
