-- Create profiles table that extends auth.users
CREATE TABLE public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    stripe_metered_item_id TEXT,
    entitlements_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable RLS on profiles
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

-- Users can read their own profile
CREATE POLICY "Users can view own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

-- Users can update their own profile (optional, depending on what you allow them to edit)
CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

-- Function to handle new user signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
    INSERT INTO public.profiles (id, email, tier)
    VALUES (new.id, new.email, 'free');
    RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to call the function on signup
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- Create usage_monthly table
CREATE TABLE public.usage_monthly (
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    period TEXT NOT NULL, -- e.g., '2026-03'
    search_count INTEGER NOT NULL DEFAULT 0,
    overage_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, period)
);

-- Enable RLS on usage_monthly
ALTER TABLE public.usage_monthly ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own usage"
    ON public.usage_monthly FOR SELECT
    USING (auth.uid() = user_id);

-- Create anon_usage table
CREATE TABLE public.anon_usage (
    anon_key TEXT PRIMARY KEY,
    search_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Note: anon_usage doesn't need RLS if it's only accessed via service role (backend API)
-- But we can enable it and restrict to service role just in case
ALTER TABLE public.anon_usage ENABLE ROW LEVEL SECURITY;

-- Create rate_buckets table
CREATE TABLE public.rate_buckets (
    bucket_key TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket_key, window_start)
);

-- Same here, rate_buckets is backend-only
ALTER TABLE public.rate_buckets ENABLE ROW LEVEL SECURITY;

-- Function to automatically update updated_at
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TRIGGER set_anon_usage_updated_at
    BEFORE UPDATE ON public.anon_usage
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- RPC for incrementing usage atomically
CREATE OR REPLACE FUNCTION public.increment_usage(p_user_id UUID, p_period TEXT, p_is_overage BOOLEAN)
RETURNS TABLE(search_count INT, overage_count INT) AS $$
BEGIN
    INSERT INTO public.usage_monthly (user_id, period, search_count, overage_count)
    VALUES (p_user_id, p_period, CASE WHEN p_is_overage THEN 0 ELSE 1 END, CASE WHEN p_is_overage THEN 1 ELSE 0 END)
    ON CONFLICT (user_id, period) DO UPDATE SET
        search_count = public.usage_monthly.search_count + CASE WHEN p_is_overage THEN 0 ELSE 1 END,
        overage_count = public.usage_monthly.overage_count + CASE WHEN p_is_overage THEN 1 ELSE 0 END;
        
    RETURN QUERY SELECT u.search_count, u.overage_count FROM public.usage_monthly u WHERE u.user_id = p_user_id AND u.period = p_period;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- RPC for incrementing anon usage atomically
CREATE OR REPLACE FUNCTION public.increment_anon_usage(p_anon_key TEXT)
RETURNS INT AS $$
DECLARE
    new_count INT;
BEGIN
    INSERT INTO public.anon_usage (anon_key, search_count)
    VALUES (p_anon_key, 1)
    ON CONFLICT (anon_key) DO UPDATE SET
        search_count = public.anon_usage.search_count + 1
    RETURNING search_count INTO new_count;
    
    RETURN new_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- RPC for rate ticking atomically
CREATE OR REPLACE FUNCTION public.rate_tick(p_bucket_key TEXT, p_window_start BIGINT, p_limit INT)
RETURNS BOOLEAN AS $$
DECLARE
    current_count INT;
BEGIN
    SELECT count INTO current_count FROM public.rate_buckets WHERE bucket_key = p_bucket_key AND window_start = p_window_start;
    
    IF current_count IS NULL THEN
        INSERT INTO public.rate_buckets (bucket_key, window_start, count)
        VALUES (p_bucket_key, p_window_start, 1);
        RETURN TRUE;
    ELSIF current_count + 1 > p_limit THEN
        RETURN FALSE;
    ELSE
        UPDATE public.rate_buckets SET count = count + 1 WHERE bucket_key = p_bucket_key AND window_start = p_window_start;
        RETURN TRUE;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

