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
});
