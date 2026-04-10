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
