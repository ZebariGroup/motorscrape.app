import { describe, expect, it } from "vitest";

import type { AggregatedListing } from "@/lib/inventoryFormat";
import { listingIdentityKey } from "@/lib/inventoryFormat";

import { buildMarketValuationMap } from "./marketValuation";

describe("market valuation", () => {
  it("flags listings against local comparable medians", () => {
    const listings: AggregatedListing[] = [
      {
        dealership: "A",
        dealership_website: "https://a.example",
        vehicle_category: "car",
        year: 2024,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 23000,
      },
      {
        dealership: "B",
        dealership_website: "https://b.example",
        vehicle_category: "car",
        year: 2024,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 25000,
      },
      {
        dealership: "C",
        dealership_website: "https://c.example",
        vehicle_category: "car",
        year: 2024,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 31000,
      },
    ];

    const valuations = buildMarketValuationMap(listings);
    const cheap = valuations.get(listingIdentityKey(listings[0]));
    const expensive = valuations.get(listingIdentityKey(listings[2]));

    expect(cheap?.label).toBe("Good value");
    expect(expensive?.label).toBe("Overpriced");
    expect(expensive?.comparableCount).toBe(3);
  });

  it("skips valuation when there are too few comparables", () => {
    const listings: AggregatedListing[] = [
      {
        dealership: "A",
        dealership_website: "https://a.example",
        vehicle_category: "car",
        year: 2024,
        make: "BMW",
        model: "X5",
        price: 50000,
      },
      {
        dealership: "B",
        dealership_website: "https://b.example",
        vehicle_category: "car",
        year: 2024,
        make: "BMW",
        model: "X7",
        price: 70000,
      },
    ];

    expect(buildMarketValuationMap(listings).size).toBe(0);
  });

  it("keeps package-heavy listings compared against similarly equipped vehicles", () => {
    const listings: AggregatedListing[] = [
      {
        dealership: "A",
        dealership_website: "https://a.example",
        vehicle_category: "car",
        year: 2025,
        make: "BMW",
        model: "X7",
        trim: "xDrive40i",
        feature_highlights: ["M Sport Professional Package", "Parking Assistance Package"],
        price: 104895,
      },
      {
        dealership: "B",
        dealership_website: "https://b.example",
        vehicle_category: "car",
        year: 2025,
        make: "BMW",
        model: "X7",
        trim: "xDrive40i",
        feature_highlights: ["M Sport Professional Package"],
        price: 103995,
      },
      {
        dealership: "C",
        dealership_website: "https://c.example",
        vehicle_category: "car",
        year: 2025,
        make: "BMW",
        model: "X7",
        trim: "xDrive40i",
        feature_highlights: ["M Sport Professional Package", "Parking Assistance Package"],
        price: 105500,
      },
      {
        dealership: "D",
        dealership_website: "https://d.example",
        vehicle_category: "car",
        year: 2025,
        make: "BMW",
        model: "X7",
        trim: "xDrive40i",
        feature_highlights: [],
        price: 98695,
      },
      {
        dealership: "E",
        dealership_website: "https://e.example",
        vehicle_category: "car",
        year: 2025,
        make: "BMW",
        model: "X7",
        trim: "xDrive40i",
        feature_highlights: [],
        price: 98200,
      },
      {
        dealership: "F",
        dealership_website: "https://f.example",
        vehicle_category: "car",
        year: 2025,
        make: "BMW",
        model: "X7",
        trim: "xDrive40i",
        feature_highlights: [],
        price: 99000,
      },
    ];

    const valuations = buildMarketValuationMap(listings);
    const loadedX7 = valuations.get(listingIdentityKey(listings[0]));

    expect(loadedX7).toBeDefined();
    expect(loadedX7?.baselinePrice).toBeGreaterThan(100000);
    expect(loadedX7?.label === "Fair price" || loadedX7?.label === "Above market").toBe(true);
  });

  it("uses historical comparable prices to stabilize baseline", () => {
    const listings: AggregatedListing[] = [
      {
        dealership: "A",
        dealership_website: "https://a.example",
        vehicle_category: "car",
        year: 2025,
        make: "BMW",
        model: "X7",
        trim: "xDrive40i",
        price: 104500,
        historical_market_prices: [103900, 104200, 105100, 103750],
      },
      {
        dealership: "B",
        dealership_website: "https://b.example",
        vehicle_category: "car",
        year: 2025,
        make: "BMW",
        model: "X7",
        trim: "xDrive40i",
        price: 104900,
      },
      {
        dealership: "C",
        dealership_website: "https://c.example",
        vehicle_category: "car",
        year: 2025,
        make: "BMW",
        model: "X7",
        trim: "xDrive40i",
        price: 105300,
      },
    ];

    const valuations = buildMarketValuationMap(listings);
    const subject = valuations.get(listingIdentityKey(listings[0]));
    expect(subject).toBeDefined();
    expect(subject?.historicalComparableCount).toBeGreaterThan(0);
    expect(subject?.comparableCount).toBeGreaterThan(3);
    expect(subject?.trimPackageConfidenceScore).toBeGreaterThan(0);
  });

  it("weights newer historical prices more heavily", () => {
    const nowSeconds = Math.floor(Date.now() / 1000);
    const listings: AggregatedListing[] = [
      {
        dealership: "A",
        dealership_website: "https://a.example",
        vehicle_category: "car",
        year: 2024,
        make: "Audi",
        model: "Q7",
        trim: "Premium Plus",
        price: 56000,
        historical_market_price_points: [
          { price: 61000, observed_at: nowSeconds - 60 * 60 * 24 * 220 },
          { price: 55000, observed_at: nowSeconds - 60 * 60 * 24 * 7 },
          { price: 54800, observed_at: nowSeconds - 60 * 60 * 24 * 5 },
        ],
      },
      {
        dealership: "B",
        dealership_website: "https://b.example",
        vehicle_category: "car",
        year: 2024,
        make: "Audi",
        model: "Q7",
        trim: "Premium Plus",
        price: 56100,
      },
      {
        dealership: "C",
        dealership_website: "https://c.example",
        vehicle_category: "car",
        year: 2024,
        make: "Audi",
        model: "Q7",
        trim: "Premium Plus",
        price: 56200,
      },
    ];

    const valuations = buildMarketValuationMap(listings);
    const subject = valuations.get(listingIdentityKey(listings[0]));
    expect(subject).toBeDefined();
    expect(subject?.baselinePrice).toBeLessThan(57000);
  });
});
