export type AlertCriteria = {
  location: string;
  make: string;
  model: string;
  vehicle_category: "car" | "motorcycle" | "boat" | "other";
  vehicle_condition: "all" | "new" | "used";
  radius_miles: number;
  inventory_scope: "all" | "on_lot_only" | "exclude_shared" | "include_transit";
  prefer_small_dealers: boolean;
  max_dealerships: number | null;
  max_pages_per_dealer: number | null;
  market_region?: "us" | "eu";
};

export type AlertSubscription = {
  id: string;
  name: string;
  criteria: AlertCriteria;
  cadence: "daily" | "weekly";
  day_of_week: number | null;
  hour_local: number;
  timezone: string;
  deliver_csv: boolean;
  only_send_on_changes: boolean;
  include_new_listings: boolean;
  include_price_drops: boolean;
  min_price_drop_usd: number | null;
  is_active: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
  last_result_count: number | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AlertRun = {
  id: string;
  subscription_id: string;
  trigger_source: string;
  status: string;
  result_count: number;
  emailed: boolean;
  csv_attached: boolean;
  error_message: string | null;
  summary: {
    result_count?: number;
    errors?: string[];
    delta?: {
      only_send_on_changes?: boolean;
      include_new_listings?: boolean;
      include_price_drops?: boolean;
      min_price_drop_usd?: number | null;
      matching_change_count?: number;
      total_change_count?: number;
      new_listings_count?: number;
      price_drop_count?: number;
      removed_count?: number;
      largest_price_drop?: number | null;
      email_skipped_no_changes?: boolean;
      sent_due_to_changes?: boolean;
      new_listings?: Array<{
        title?: string;
        dealer?: string;
        price?: number | null;
        url?: string | null;
      }>;
      price_drops?: Array<{
        title?: string;
        dealer?: string;
        price?: number | null;
        history_price_change?: number | null;
        url?: string | null;
      }>;
    };
    top_results?: Array<{
      title?: string;
      dealer?: string;
      price?: number | null;
      history_price_change?: number | null;
      url?: string | null;
    }>;
  };
  started_at: string | null;
  completed_at: string | null;
};

export type AlertDashboardResponse = {
  subscriptions: AlertSubscription[];
  runs: AlertRun[];
  email_configured: boolean;
  limits: {
    tier: string;
    max_dealerships: number;
    max_radius_miles: number;
  };
};
