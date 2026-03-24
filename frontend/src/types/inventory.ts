export type VehicleListing = {
  year?: number;
  make?: string;
  model?: string;
  trim?: string;
  price?: number;
  mileage?: number;
  vin?: string;
  image_url?: string;
  listing_url?: string;
  raw_title?: string;
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
  /** Last parse path: structured JSON vs LLM */
  extraction?: "structured" | "llm";
  /** Per-dealer sequence of fetch modes (e.g. direct, zenrows_rendered) */
  fetch_methods?: string[];
  listings_found?: number;
  /** Client-only: when the current status phase started (ms since epoch). */
  phaseSince?: number;
};
