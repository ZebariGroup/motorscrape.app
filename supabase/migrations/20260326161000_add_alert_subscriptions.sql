CREATE TABLE public.alert_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    criteria_json JSONB NOT NULL,
    cadence TEXT NOT NULL,
    day_of_week INTEGER,
    hour_local INTEGER NOT NULL,
    timezone TEXT NOT NULL,
    deliver_csv BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    next_run_at TIMESTAMPTZ NOT NULL,
    last_run_at TIMESTAMPTZ,
    last_run_status TEXT,
    last_result_count INTEGER,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.alert_subscriptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own alert subscriptions"
    ON public.alert_subscriptions FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own alert subscriptions"
    ON public.alert_subscriptions FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE INDEX idx_alert_subscriptions_user_id
    ON public.alert_subscriptions (user_id, is_active, next_run_at);

CREATE TRIGGER set_alert_subscriptions_updated_at
    BEFORE UPDATE ON public.alert_subscriptions
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE public.alert_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES public.alert_subscriptions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    trigger_source TEXT NOT NULL,
    status TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    emailed BOOLEAN NOT NULL DEFAULT FALSE,
    csv_attached BOOLEAN NOT NULL DEFAULT FALSE,
    error_message TEXT,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

ALTER TABLE public.alert_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own alert runs"
    ON public.alert_runs FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own alert runs"
    ON public.alert_runs FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE INDEX idx_alert_runs_user_id
    ON public.alert_runs (user_id, started_at DESC);
