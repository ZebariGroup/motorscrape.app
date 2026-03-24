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
  listings_found?: number;
};
