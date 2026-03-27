export type AlertCriteria = {
  location: string;
  make: string;
  model: string;
  vehicle_category: "car" | "motorcycle" | "boat" | "other";
  vehicle_condition: "all" | "new" | "used";
  radius_miles: number;
  inventory_scope: "all" | "on_lot_only" | "exclude_shared" | "include_transit";
  max_dealerships: number | null;
  max_pages_per_dealer: number | null;
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
    top_results?: Array<{
      title?: string;
      dealer?: string;
      price?: number | null;
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
