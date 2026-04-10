-- Public aggregated vehicle sightings table.
-- Written by the backend (service role) whenever a scrape run completes with results.
-- Publicly readable (no auth required) — no PII stored here.

CREATE TABLE public.vehicle_sightings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    search_location TEXT NOT NULL,
    search_state TEXT NOT NULL DEFAULT '',
    result_count INTEGER NOT NULL DEFAULT 0,
    price_min DOUBLE PRECISION,
    price_max DOUBLE PRECISION,
    price_avg DOUBLE PRECISION,
    top_dealerships_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    scraped_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for the queries we'll run: by make+model (with model optional) and by state
CREATE INDEX idx_vehicle_sightings_make_model
    ON public.vehicle_sightings (make, model, scraped_at DESC);

CREATE INDEX idx_vehicle_sightings_make
    ON public.vehicle_sightings (make, scraped_at DESC);

CREATE INDEX idx_vehicle_sightings_state
    ON public.vehicle_sightings (search_state, make, model);

-- Public read — no auth needed. Only the service role can write.
ALTER TABLE public.vehicle_sightings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read vehicle_sightings"
    ON public.vehicle_sightings FOR SELECT
    USING (true);
