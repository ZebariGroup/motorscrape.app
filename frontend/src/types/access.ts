export type AccessSummary = {
  authenticated: boolean;
  tier: string;
  is_admin: boolean;
  limits: {
    max_dealerships: number;
    max_pages_per_dealer: number;
    max_radius_miles: number;
    max_concurrent_searches: number;
    csv_export: boolean;
    inventory_scope_premium: boolean;
    minute_rate_limit: number;
  };
  anonymous?: {
    searches_used: number;
    searches_remaining: number;
    signup_required_after: number;
  };
  usage?: {
    period: string;
    included_used: number;
    overage_used: number;
    included_limit: number;
  };
};
