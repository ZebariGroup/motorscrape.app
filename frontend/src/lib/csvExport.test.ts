import { describe, expect, it } from "vitest";

import type { AggregatedListing } from "@/lib/inventoryFormat";

import { escapeCsvField, listingsToCsv } from "./csvExport";

describe("escapeCsvField", () => {
  it("wraps fields with quotes and commas", () => {
    expect(escapeCsvField('say "hi"')).toBe(`"say ""hi"""`);
    expect(escapeCsvField("a,b")).toBe(`"a,b"`);
  });
});

describe("listingsToCsv", () => {
  it("includes header and one row", () => {
    const rows: AggregatedListing[] = [
      {
        dealership: "Test Motors",
        dealership_website: "https://test.example",
        vehicle_category: "boat",
        year: 2024,
        make: "Honda",
        model: "Civic",
        price: 25000,
        vin: "1HGCM82633A004352",
        vehicle_identifier: "BOAT-77",
        usage_value: 120,
        usage_unit: "hours",
      },
    ];
    const csv = listingsToCsv(rows);
    expect(csv.split("\n")).toHaveLength(2);
    expect(csv).toContain("Test Motors");
    expect(csv).toContain("BOAT-77");
    expect(csv).toContain("vehicle_category");
  });
});
