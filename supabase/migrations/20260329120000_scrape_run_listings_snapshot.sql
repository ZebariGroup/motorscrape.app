ALTER TABLE public.scrape_runs
    ADD COLUMN IF NOT EXISTS listings_snapshot_json JSONB;

COMMENT ON COLUMN public.scrape_runs.listings_snapshot_json IS
    'Vehicle rows from the completed search (for user history / replay without re-scrape).';
