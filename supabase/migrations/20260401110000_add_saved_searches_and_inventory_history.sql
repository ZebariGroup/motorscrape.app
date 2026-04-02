CREATE TABLE public.saved_searches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    criteria_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.saved_searches ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own saved searches"
    ON public.saved_searches FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own saved searches"
    ON public.saved_searches FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE INDEX idx_saved_searches_user_id
    ON public.saved_searches (user_id, updated_at DESC);

CREATE TRIGGER set_saved_searches_updated_at
    BEFORE UPDATE ON public.saved_searches
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE public.inventory_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    vehicle_key TEXT NOT NULL,
    dealership_key TEXT NOT NULL,
    vin TEXT,
    vehicle_identifier TEXT,
    listing_url TEXT,
    raw_title TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    first_scrape_run_id UUID REFERENCES public.scrape_runs(id) ON DELETE SET NULL,
    latest_scrape_run_id UUID REFERENCES public.scrape_runs(id) ON DELETE SET NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    first_price DOUBLE PRECISION,
    previous_price DOUBLE PRECISION,
    latest_price DOUBLE PRECISION,
    lowest_price DOUBLE PRECISION,
    highest_price DOUBLE PRECISION,
    latest_days_on_lot INTEGER,
    price_history_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, vehicle_key)
);

ALTER TABLE public.inventory_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own inventory history"
    ON public.inventory_history FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own inventory history"
    ON public.inventory_history FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE INDEX idx_inventory_history_user_id
    ON public.inventory_history (user_id, last_seen_at DESC);

CREATE TRIGGER set_inventory_history_updated_at
    BEFORE UPDATE ON public.inventory_history
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
