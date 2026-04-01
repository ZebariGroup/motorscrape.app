-- Drop the old function first
DROP FUNCTION IF EXISTS public.find_cached_dealerships(TEXT, TEXT, DOUBLE PRECISION, DOUBLE PRECISION, INTEGER);

-- Update function to return lat and lng
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
        d.lat,
        d.lng,
        ST_Distance(d.location, v_center) as distance_meters
    FROM public.dealerships d
    JOIN public.dealership_makes dm ON d.id = dm.dealership_id
    WHERE dm.make = p_make 
      AND dm.vehicle_category = p_vehicle_category
      AND ST_DWithin(d.location, v_center, p_radius_meters)
    ORDER BY distance_meters ASC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
