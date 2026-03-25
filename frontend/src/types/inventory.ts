export type VehicleListing = {
  year?: number;
  make?: string;
  model?: string;
  trim?: string;
  body_style?: string;
  exterior_color?: string;
  price?: number;
  mileage?: number;
  vehicle_condition?: "new" | "used";
  vin?: string;
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
  /** Savings below MSRP in USD */
  dealer_discount?: number;
  incentive_labels?: string[];
  feature_highlights?: string[];
  /** YYYY-MM-DD when the dealer exposes a stock date */
  stock_date?: string;
  days_on_lot?: number;
};

export type DealershipProgress = {
  index: number;
  total: number;
  name: string;
  website: string;
  address?: string;
  status: "scraping" | "parsing" | "done" | "error";
  error?: string;
  info?: string;
  fetch_method?: string;
  /** Parse path: provider route, structured JSON, or LLM */
  extraction?: string;
  /** Detected/cached dealer platform identifier */
  platform_id?: string;
  /** Where the platform routing info came from */
  platform_source?: "hit" | "detected" | "refresh" | "stale" | "none";
  /** Provider strategy currently selected for the dealer */
  strategy_used?: string;
  /** Per-dealer sequence of fetch modes (e.g. direct, zenrows_rendered) */
  fetch_methods?: string[];
  listings_found?: number;
  /** Client-only: when the current status phase started (ms since epoch). */
  phaseSince?: number;
};
