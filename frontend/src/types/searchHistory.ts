/** Row from GET /search/logs (user's interactive search history). */
export type SearchHistoryRunRow = {
  correlation_id: string;
  location: string;
  make?: string;
  model?: string;
  vehicle_category: string;
  vehicle_condition: string;
  inventory_scope: string;
  radius_miles: number;
  requested_max_dealerships: number | null;
  requested_max_pages_per_dealer: number | null;
  result_count: number;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  has_saved_results?: boolean;
  saved_listings_count?: number;
};

export type SearchHistoryDetailResponse = {
  run: SearchHistoryRunRow;
  listings: unknown[];
};
