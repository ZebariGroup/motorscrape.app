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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
        year: 2024,
        make: "BMW",
        model: "X5",
        price: 50000,
      },
      {
        dealership: "B",
        dealership_website: "https://b.example",
        vehicle_category: "car",
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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
        vehicle_condition: "new",
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

  it("skips used listings even when comparable coverage is strong", () => {
    const listings: AggregatedListing[] = [
      {
        dealership: "A",
        dealership_website: "https://a.example",
        vehicle_category: "car",
        vehicle_condition: "used",
        year: 2024,
        make: "Honda",
        model: "Accord",
        trim: "Sport",
        price: 30000,
      },
      {
        dealership: "B",
        dealership_website: "https://b.example",
        vehicle_category: "car",
        vehicle_condition: "used",
        year: 2022,
        make: "Honda",
        model: "Accord",
        trim: "Sport",
        price: 26000,
      },
      {
        dealership: "C",
        dealership_website: "https://c.example",
        vehicle_category: "car",
        vehicle_condition: "used",
        year: 2022,
        make: "Honda",
        model: "Accord",
        trim: "Sport",
        price: 26200,
      },
      {
        dealership: "D",
        dealership_website: "https://d.example",
        vehicle_category: "car",
        vehicle_condition: "used",
        year: 2022,
        make: "Honda",
        model: "Accord",
        trim: "Sport",
        price: 25800,
      },
    ];

    const valuations = buildMarketValuationMap(listings);
    const subject = valuations.get(listingIdentityKey(listings[0]));
    expect(subject).toBeUndefined();
    expect(valuations.size).toBe(0);
  });

  it("only compares new listings against other new inventory", () => {
    const listings: AggregatedListing[] = [
      {
        dealership: "A",
        dealership_website: "https://a.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2025,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 31900,
      },
      {
        dealership: "B",
        dealership_website: "https://b.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2025,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 32500,
      },
      {
        dealership: "C",
        dealership_website: "https://c.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2025,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 32700,
      },
      {
        dealership: "D",
        dealership_website: "https://d.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2025,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 32300,
      },
      {
        dealership: "E",
        dealership_website: "https://e.example",
        vehicle_category: "car",
        vehicle_condition: "used",
        year: 2022,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 22900,
        mileage: 42000,
        usage_value: 42000,
        usage_unit: "miles",
      },
      {
        dealership: "F",
        dealership_website: "https://f.example",
        vehicle_category: "car",
        vehicle_condition: "used",
        year: 2022,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 23100,
        mileage: 39000,
        usage_value: 39000,
        usage_unit: "miles",
      },
      {
        dealership: "G",
        dealership_website: "https://g.example",
        vehicle_category: "car",
        vehicle_condition: "used",
        year: 2022,
        make: "Toyota",
        model: "Camry",
        trim: "SE",
        price: 22800,
        mileage: 41000,
        usage_value: 41000,
        usage_unit: "miles",
      },
    ];

    const valuations = buildMarketValuationMap(listings);
    const subject = valuations.get(listingIdentityKey(listings[0]));
    expect(subject).toBeDefined();
    expect(subject?.baselinePrice).toBeGreaterThan(32000);
    expect(subject?.comparables.every((listing) => listing.vehicle_condition === "new")).toBe(true);
  });

  it("keeps special-edition trims separated from base variants", () => {
    const listings: AggregatedListing[] = [
      {
        dealership: "A",
        dealership_website: "https://a.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2024,
        make: "Cadillac",
        model: "CT5-V",
        trim: "Blackwing",
        raw_title: "2024 Cadillac CT5-V Blackwing",
        price: 94995,
      },
      {
        dealership: "B",
        dealership_website: "https://b.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2024,
        make: "Cadillac",
        model: "CT5-V",
        trim: "Blackwing",
        raw_title: "2024 Cadillac CT5-V Blackwing",
        price: 95995,
      },
      {
        dealership: "C",
        dealership_website: "https://c.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2024,
        make: "Cadillac",
        model: "CT5-V",
        trim: "Blackwing",
        raw_title: "2024 Cadillac CT5-V Blackwing",
        price: 96995,
      },
      {
        dealership: "D",
        dealership_website: "https://d.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2024,
        make: "Cadillac",
        model: "CT5-V",
        trim: "V-Series",
        raw_title: "2024 Cadillac CT5-V",
        price: 75995,
      },
      {
        dealership: "E",
        dealership_website: "https://e.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2024,
        make: "Cadillac",
        model: "CT5-V",
        trim: "V-Series",
        raw_title: "2024 Cadillac CT5-V",
        price: 76995,
      },
      {
        dealership: "F",
        dealership_website: "https://f.example",
        vehicle_category: "car",
        vehicle_condition: "new",
        year: 2024,
        make: "Cadillac",
        model: "CT5-V",
        trim: "V-Series",
        raw_title: "2024 Cadillac CT5-V",
        price: 77995,
      },
    ];

    const valuations = buildMarketValuationMap(listings);
    const blackwing = valuations.get(listingIdentityKey(listings[0]));
    const baseV = valuations.get(listingIdentityKey(listings[3]));

    expect(blackwing).toBeDefined();
    expect(blackwing?.baselinePrice).toBeGreaterThan(94000);
    expect(blackwing?.comparables.every((listing) => listing.trim === "Blackwing")).toBe(true);

    expect(baseV).toBeDefined();
    expect(baseV?.baselinePrice).toBeLessThan(80000);
    expect(baseV?.comparables.every((listing) => listing.trim === "V-Series")).toBe(true);
  });
});
