import { resolveApiUrl } from "@/lib/apiBase";

export type AdminUser = {
  id: string;
  email: string;
  tier: string;
  is_admin: boolean;
  created_at: string | null;
  updated_at: string | null;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  has_metered_item: boolean;
  usage: {
    period: string;
    included_used: number;
    overage_used: number;
    included_limit: number;
  };
};

export type AdminRun = {
  id: string;
  correlation_id: string;
  user_id: string | null;
  user_email: string | null;
  status: string;
  trigger_source: string;
  location: string;
  make: string;
  model: string;
  vehicle_category: string;
  vehicle_condition: string;
  inventory_scope: string;
  result_count: number;
  error_count: number;
  warning_count: number;
  error_message: string | null;
  error_code?: string | null;
  error_phase?: string | null;
  error?: Record<string, unknown> | null;
  summary: Record<string, unknown>;
  economics: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
};

export type AdminEvent = {
  id: string;
  sequence_no: number;
  event_type: string;
  phase: string | null;
  level: string;
  message: string;
  dealership_name: string | null;
  dealership_website: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
};

export type DealerOutcome = {
  dealership_name: string | null;
  dealership_website: string | null;
  status: string;
  classification: string;
  platform_id: string | null;
  platform_source: string | null;
  strategy_used: string | null;
  listings_found: number;
  final_url: string | null;
  fetch_methods: string[];
  ford_recovery_urls: string[];
  zero_results_warning: string | null;
  error_phase: string | null;
  error_message: string | null;
  error_code?: string | null;
};

export type DealerOutcomeSummary = {
  total_dealers: number;
  status_counts: Record<string, number>;
  classification_counts: Record<string, number>;
  error_code_counts?: Record<string, number>;
  failed_platform_counts?: Record<string, number>;
  failed_fetch_method_counts?: Record<string, number>;
  zero_results_warnings: number;
  ford_family_dealers: number;
};

export type AdminAlertSubscription = {
  id: string;
  user_id: string;
  user_email: string | null;
  name: string;
  criteria: Record<string, unknown>;
  cadence: string;
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

export type AdminAlertRun = {
  id: string;
  subscription_id: string;
  user_id: string;
  user_email: string | null;
  trigger_source: string;
  status: string;
  result_count: number;
  emailed: boolean;
  csv_attached: boolean;
  error_message: string | null;
  summary: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
};

export type AdminAuditLog = {
  id: string;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string | null;
};

export type OverviewResponse = {
  stats: {
    total_users: number;
    users_by_tier: Record<string, number>;
    searches_this_month: number;
    overage_searches_this_month: number;
    recent_signups_last_7d: number;
    failed_runs_last_7d: number;
    active_alerts: number;
    alerts_due_now: number;
    failed_alert_runs_last_7d: number;
  };
  recent_users: AdminUser[];
  recent_runs: AdminRun[];
};

export type RunDetailResponse = {
  run: AdminRun;
  events: AdminEvent[];
  dealer_outcomes: DealerOutcome[];
  dealer_summary: DealerOutcomeSummary;
};

export type UsersResponse = {
  users: AdminUser[];
  total: number;
  limit: number;
  offset: number;
};

export type RunsResponse = {
  runs: AdminRun[];
  total: number;
  limit: number;
  offset: number;
};

export type AlertHealthResponse = {
  due_subscriptions: AdminAlertSubscription[];
  recent_alert_runs: AdminAlertRun[];
};

export type AuditLogResponse = {
  logs: AdminAuditLog[];
  limit: number;
  offset: number;
};

export type UserDetailResponse = {
  user: AdminUser;
  search_runs: AdminRun[];
  alert_subscriptions: AdminAlertSubscription[];
  alert_runs: AdminAlertRun[];
  audit_logs: AdminAuditLog[];
};

export async function fetchAdminJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(resolveApiUrl(path), {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = typeof body.detail === "string" ? body.detail : "Request failed.";
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function formatDateTime(value: string | null): string {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleString();
}

export function formatRunLabel(run: AdminRun): string {
  const bits = [run.location, run.make, run.model].filter(Boolean);
  return bits.join(" · ") || run.correlation_id;
}
