/**
 * Server-side helpers to fetch vehicle sightings from the national DB.
 * Used only from Next.js Server Components / generateMetadata.
 */

export type VehicleSighting = {
  make: string;
  model: string;
  search_location: string;
  search_state: string;
  result_count: number;
  price_min: number | null;
  price_max: number | null;
  price_avg: number | null;
  top_dealerships: Array<{ domain: string; name: string; count: number }>;
  scraped_at: string;
};

export type StateBucket = {
  state: string;
  sighting_count: number;
  total_results: number;
  last_scraped_at: string | null;
  sample_locations: string[];
};

export type VehicleSightingsSummary = {
  total_sightings: number;
  total_results: number;
  states: StateBucket[];
  price_min: number | null;
  price_max: number | null;
  price_avg: number | null;
};

function serverApiBase(): string {
  const origin = process.env.MOTORSCRAPE_API_ORIGIN?.replace(/\/$/, "");
  if (origin) return origin;
  const vercelUrl = process.env.VERCEL_URL;
  if (vercelUrl) return `https://${vercelUrl}`;
  return "http://127.0.0.1:8000";
}

export async function fetchVehicleSightings(
  make: string,
  model?: string,
  options?: { state?: string; limit?: number },
): Promise<VehicleSighting[]> {
  const base = serverApiBase();
  const params = new URLSearchParams({ make });
  if (model) params.set("model", model);
  if (options?.state) params.set("state", options.state);
  if (options?.limit) params.set("limit", String(options.limit));

  const url = `${base}/server/vehicles/sightings?${params.toString()}`;
  try {
    const res = await fetch(url, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const data = await res.json();
    return (data.sightings as VehicleSighting[]) ?? [];
  } catch {
    return [];
  }
}

export async function fetchVehicleSightingsSummary(
  make: string,
  model?: string,
): Promise<VehicleSightingsSummary> {
  const empty: VehicleSightingsSummary = {
    total_sightings: 0,
    total_results: 0,
    states: [],
    price_min: null,
    price_max: null,
    price_avg: null,
  };

  const base = serverApiBase();
  const params = new URLSearchParams({ make });
  if (model) params.set("model", model);

  const url = `${base}/server/vehicles/sightings/summary?${params.toString()}`;
  try {
    const res = await fetch(url, { next: { revalidate: 3600 } });
    if (!res.ok) return empty;
    const data = await res.json();
    if (!data.ok) return empty;
    return {
      total_sightings: data.total_sightings ?? 0,
      total_results: data.total_results ?? 0,
      states: data.states ?? [],
      price_min: data.price_min ?? null,
      price_max: data.price_max ?? null,
      price_avg: data.price_avg ?? null,
    };
  } catch {
    return empty;
  }
}

export function formatPrice(price: number | null | undefined): string {
  if (price == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(price);
}

export function formatSightingDate(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  try {
    return new Date(isoString).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "—";
  }
}
