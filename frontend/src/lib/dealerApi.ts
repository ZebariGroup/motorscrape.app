/**
 * Server-side helpers to fetch dealer data from the FastAPI backend.
 * Used only from Next.js Server Components / generateMetadata.
 */

export type DealerHours = {
  weekdayDescriptions?: string[];
  periods?: Array<{
    open?: { day?: number; hour?: number; minute?: number };
    close?: { day?: number; hour?: number; minute?: number };
  }>;
};

export type DealerStats = {
  scrape_count: number;
  last_scraped_at: string | null;
  avg_listing_count: number | null;
  price_min: number | null;
  price_median: number | null;
  makes_in_inventory: string[];
};

export type DealerMake = {
  make: string;
  category: string;
};

export type DealerSocialLinks = {
  facebook?: string;
  instagram?: string;
  twitter?: string;
  youtube?: string;
  yelp?: string;
  dealerrater?: string;
  carscom?: string;
};

export type DealerProfile = {
  id: string;
  slug: string;
  place_id: string;
  name: string;
  address: string;
  website: string | null;
  lat: number | null;
  lng: number | null;
  phone: string | null;
  rating: number | null;
  review_count: number | null;
  description: string | null;
  hours_json: DealerHours | null;
  photo_refs: Array<{ name: string; widthPx?: number; heightPx?: number }> | null;
  social_links: DealerSocialLinks | null;
  oem_brands: string[];
  services: string[];
  enriched_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  makes: DealerMake[];
  stats: DealerStats;
};

function serverApiBase(): string {
  // In server context, use the explicit origin if set; otherwise fall back to same-host /server prefix.
  const origin = process.env.MOTORSCRAPE_API_ORIGIN?.replace(/\/$/, "");
  if (origin) return origin;
  // On Vercel, requests from SSR to /server are same-host
  const vercelUrl = process.env.VERCEL_URL;
  if (vercelUrl) return `https://${vercelUrl}`;
  return "http://127.0.0.1:8000";
}

export type DealerCard = {
  slug: string;
  name: string;
  address: string;
  website: string | null;
  lat: number | null;
  lng: number | null;
  rating: number | null;
  review_count: number | null;
  oem_brands: string[];
  services: string[];
  enriched: boolean;
};

export type DealerListResponse = {
  dealers: DealerCard[];
  total: number;
  offset: number;
  limit: number;
};

export async function fetchDealerList(params?: {
  q?: string;
  make?: string;
  state?: string;
  city?: string;
  sort?: string;
  lat?: number;
  lng?: number;
  limit?: number;
  offset?: number;
}): Promise<DealerListResponse> {
  const base = serverApiBase();
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.make) qs.set("make", params.make);
  if (params?.state) qs.set("state", params.state);
  if (params?.city) qs.set("city", params.city);
  if (params?.sort) qs.set("sort", params.sort);
  if (params?.lat != null) qs.set("lat", String(params.lat));
  if (params?.lng != null) qs.set("lng", String(params.lng));
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const url = `${base}/server/dealerships${qs.toString() ? `?${qs}` : ""}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      console.error(`fetchDealerList HTTP ${res.status}`);
      return { dealers: [], total: 0, offset: 0, limit: 24 };
    }
    const data = await res.json();
    return {
      dealers: data.dealers ?? [],
      total: data.total ?? 0,
      offset: data.offset ?? 0,
      limit: data.limit ?? 24,
    };
  } catch (err) {
    console.error("fetchDealerList error:", err);
    return { dealers: [], total: 0, offset: 0, limit: 24 };
  }
}

export async function fetchDealerBySlug(slug: string): Promise<DealerProfile | null> {
  const base = serverApiBase();
  const url = `${base}/server/dealerships/${encodeURIComponent(slug)}`;
  try {
    const res = await fetch(url, {
      next: { revalidate: 3600 },
    });
    if (res.status === 404) return null;
    if (!res.ok) {
      console.error(`fetchDealerBySlug HTTP ${res.status} for slug=${slug}`);
      return null;
    }
    const data = await res.json();
    return data.dealer as DealerProfile;
  } catch (err) {
    console.error(`fetchDealerBySlug error for ${slug}:`, err);
    return null;
  }
}
