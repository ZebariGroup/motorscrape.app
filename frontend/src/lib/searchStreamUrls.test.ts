import { afterEach, describe, expect, it } from "vitest";

import { buildSearchStreamUrl, searchLogUrl, stopSearchUrl } from "./searchStreamUrls";

describe("searchStreamUrls", () => {
  const prev = process.env.NEXT_PUBLIC_API_URL;

  afterEach(() => {
    if (prev === undefined) delete process.env.NEXT_PUBLIC_API_URL;
    else process.env.NEXT_PUBLIC_API_URL = prev;
  });

  it("builds stream URL with encoded query params", () => {
    process.env.NEXT_PUBLIC_API_URL = "http://127.0.0.1:8000";
    const url = buildSearchStreamUrl({
      location: "Austin, TX",
      make: "Toyota",
      model: "Camry",
      correlationId: "srch-abc123",
      vehicleCategory: "car",
      vehicleCondition: "used",
      radiusMiles: "25",
      inventoryScope: "all",
      maxDealerships: "4",
      marketRegion: "us",
      preferSmallDealers: true,
    });

    expect(url).toContain("http://127.0.0.1:8000/search/stream?");
    expect(url).toContain("location=Austin%2C+TX");
    expect(url).toContain("make=Toyota");
    expect(url).toContain("model=Camry");
    expect(url).toContain("correlation_id=srch-abc123");
    expect(url).toContain("prefer_small_dealers=true");
  });

  it("builds logs and stop URLs using encoded correlation id", () => {
    process.env.NEXT_PUBLIC_API_URL = "http://127.0.0.1:8000";
    const correlationId = "srch/test id";
    expect(searchLogUrl(correlationId)).toBe(
      "http://127.0.0.1:8000/search/logs/srch%2Ftest%20id?include_events=false",
    );
    expect(stopSearchUrl(correlationId)).toBe(
      "http://127.0.0.1:8000/search/stop/srch%2Ftest%20id",
    );
  });
});
