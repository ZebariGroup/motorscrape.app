ALTER TABLE public.scrape_runs
    ADD COLUMN IF NOT EXISTS prefer_small_dealers BOOLEAN NOT NULL DEFAULT FALSE;
