import type { MetadataRoute } from "next";
import { getMakesForCategory, getModelsForMake } from "@/lib/vehicleCatalog";
import { TOP_STATES, getCitiesByState } from "@/lib/locations";
import { GUIDES } from "@/lib/guides";

const BASE_URL = "https://www.motorscrape.com";

export default function sitemap(): MetadataRoute.Sitemap {
  const sitemap: MetadataRoute.Sitemap = [
    {
      url: BASE_URL,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 1,
    },
    {
      url: `${BASE_URL}/directory`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.8,
    },
    {
      url: `${BASE_URL}/guides`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.8,
    },
  ];

  // Add Guides URLs
  for (const guide of GUIDES) {
    sitemap.push({
      url: `${BASE_URL}/guides/${guide.slug}`,
      lastModified: new Date(guide.publishedAt),
      changeFrequency: "monthly",
      priority: 0.7,
    });
  }

  // Add Location URLs
  for (const state of TOP_STATES) {
    sitemap.push({
      url: `${BASE_URL}/locations/${state.slug}`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.7,
    });

    const cities = getCitiesByState(state.abbr);
    for (const city of cities) {
      sitemap.push({
        url: `${BASE_URL}/locations/${state.slug}/${city.slug}`,
        lastModified: new Date(),
        changeFrequency: "weekly",
        priority: 0.6,
      });
    }
  }

  // Add Make/Model URLs
  const makes = getMakesForCategory("car", "us");
  for (const make of makes) {
    const makeSlug = encodeURIComponent(make.toLowerCase());
    sitemap.push({
      url: `${BASE_URL}/cars/${makeSlug}`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.7,
    });

    const models = getModelsForMake("car", make, "us");
    for (const model of models) {
      const modelSlug = encodeURIComponent(model.toLowerCase());
      sitemap.push({
        url: `${BASE_URL}/cars/${makeSlug}/${modelSlug}`,
        lastModified: new Date(),
        changeFrequency: "weekly",
        priority: 0.6,
      });
    }
  }

  return sitemap;
}
