import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/dealers/"],
        disallow: [],
      },
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/*?*"],
      },
    ],
    sitemap: [
      "https://www.motorscrape.com/sitemap.xml",
      "https://www.motorscrape.com/dealers/sitemap.xml",
    ],
  };
}
