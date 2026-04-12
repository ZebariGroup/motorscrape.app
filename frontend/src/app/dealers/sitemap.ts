import type { MetadataRoute } from "next";
import { fetchAllDealerSlugs } from "@/lib/dealerApi";

const BASE_URL = "https://www.motorscrape.com";

export const revalidate = 3600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const slugs = await fetchAllDealerSlugs();

  return slugs.map((entry) => ({
    url: `${BASE_URL}/dealers/${entry.slug}`,
    lastModified: entry.updated_at ? new Date(entry.updated_at) : new Date(),
    changeFrequency: "weekly" as const,
    priority: 0.6,
  }));
}
