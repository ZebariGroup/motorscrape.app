CREATE TABLE public.scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id TEXT NOT NULL,
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    anon_key TEXT,
    trigger_source TEXT NOT NULL,
    status TEXT NOT NULL,
    location TEXT NOT NULL,
    make TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    vehicle_category TEXT NOT NULL,
    vehicle_condition TEXT NOT NULL,
    inventory_scope TEXT NOT NULL,
    radius_miles INTEGER NOT NULL,
    requested_max_dealerships INTEGER,
    requested_max_pages_per_dealer INTEGER,
    result_count INTEGER NOT NULL DEFAULT 0,
    dealer_discovery_count INTEGER,
    dealer_deduped_count INTEGER,
    dealerships_attempted INTEGER NOT NULL DEFAULT 0,
    dealerships_succeeded INTEGER NOT NULL DEFAULT 0,
    dealerships_failed INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    economics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

ALTER TABLE public.scrape_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own scrape runs"
    ON public.scrape_runs FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own scrape runs"
    ON public.scrape_runs FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE INDEX idx_scrape_runs_user_id
    ON public.scrape_runs (user_id, started_at DESC);

CREATE INDEX idx_scrape_runs_anon_key
    ON public.scrape_runs (anon_key, started_at DESC);

CREATE INDEX idx_scrape_runs_correlation_id
    ON public.scrape_runs (correlation_id);

CREATE TABLE public.scrape_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id UUID NOT NULL REFERENCES public.scrape_runs(id) ON DELETE CASCADE,
    correlation_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    phase TEXT,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    dealership_name TEXT,
    dealership_website TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE public.scrape_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own scrape events"
    ON public.scrape_events FOR SELECT
    USING (
        EXISTS (
            SELECT 1
            FROM public.scrape_runs
            WHERE public.scrape_runs.id = public.scrape_events.scrape_run_id
              AND public.scrape_runs.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can manage own scrape events"
    ON public.scrape_events FOR ALL
    USING (
        EXISTS (
            SELECT 1
            FROM public.scrape_runs
            WHERE public.scrape_runs.id = public.scrape_events.scrape_run_id
              AND public.scrape_runs.user_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.scrape_runs
            WHERE public.scrape_runs.id = public.scrape_events.scrape_run_id
              AND public.scrape_runs.user_id = auth.uid()
        )
    );

CREATE INDEX idx_scrape_events_run_id
    ON public.scrape_events (scrape_run_id, sequence_no ASC);
