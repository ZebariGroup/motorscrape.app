export type VehicleListing = {
  vehicle_category?: "car" | "motorcycle" | "boat" | "other";
  year?: number;
  make?: string;
  model?: string;
  trim?: string;
  body_style?: string;
  drivetrain?: string;
  engine?: string;
  transmission?: string;
  fuel_type?: string;
  exterior_color?: string;
  price?: number;
  mileage?: number;
  usage_value?: number;
  usage_unit?: "miles" | "hours";
  vehicle_condition?: "new" | "used";
  vin?: string;
  vehicle_identifier?: string;
  image_url?: string;
  listing_url?: string;
  raw_title?: string;
  inventory_location?: string;
  availability_status?: string;
  is_offsite?: boolean;
  is_in_transit?: boolean;
  is_in_stock?: boolean;
  is_shared_inventory?: boolean;
  /** List / sticker MSRP when shown separately from sale price */
  msrp?: number;
  /** Advertised monthly lease payment when the dealer exposes it */
  lease_monthly_payment?: number;
  /** Lease term paired with the advertised monthly payment */
  lease_term_months?: number;
  /** Savings below MSRP in USD */
  dealer_discount?: number;
  incentive_labels?: string[];
  feature_highlights?: string[];
  /** YYYY-MM-DD when the dealer exposes a stock date */
  stock_date?: string;
  days_on_lot?: number;
  history_seen_count?: number;
  history_first_seen_at?: string;
  history_last_seen_at?: string;
  history_days_tracked?: number;
  history_previous_price?: number;
  history_lowest_price?: number;
  history_highest_price?: number;
  history_price_change?: number;
  history_price_change_since_first?: number;
  price_history?: Array<{ observed_at?: string; price?: number }>;
};

export type DealershipProgress = {
  index: number;
  total: number;
  name: string;
  website: string;
  address?: string;
  status: "queued" | "scraping" | "parsing" | "done" | "error";
  error?: string;
  info?: string;
  current_url?: string;
  fetch_method?: string;
  /** Parse path: provider route, structured JSON, or LLM */
  extraction?: string;
  /** Detected/cached dealer platform identifier */
  platform_id?: string;
  /** Where the platform routing info came from */
  platform_source?: "hit" | "detected" | "refresh" | "stale" | "none" | "cache";
  /** Provider strategy currently selected for the dealer */
  strategy_used?: string;
  /** Per-dealer sequence of fetch modes (e.g. direct, zenrows_rendered) */
  fetch_methods?: string[];
  listings_found?: number;
  pages_scraped?: number;
  current_page_number?: number;
  reported_total_pages?: number;
  reported_total_results?: number;
  reported_page_size?: number;
  pagination_source?: string;
  from_cache?: boolean;
  /** Client-only: when the current status phase started (ms since epoch). */
  phaseSince?: number;
};
