import { describe, expect, it } from "vitest";

import { clampPercent, formatMoney, listingIdentityKey } from "./inventoryFormat";

describe("inventoryFormat", () => {
  it("formatMoney returns em dash for undefined", () => {
    expect(formatMoney(undefined)).toBe("—");
  });

  it("clampPercent bounds", () => {
    expect(clampPercent(-5)).toBe(0);
    expect(clampPercent(50)).toBe(50);
    expect(clampPercent(150)).toBe(100);
  });

  it("listingIdentityKey uses stable listing identifiers before fallback", () => {
    expect(
      listingIdentityKey({
        dealership: "BMW of Ann Arbor",
        dealership_website: "https://www.bmwofannarbor.com/",
        vehicle_identifier: "WBATEST12345",
        raw_title: "2025 BMW X3 xDrive30",
        price: 52995,
      }, "fallback-1"),
    ).toContain("wbatest12345");
  });

  it("listingIdentityKey falls back when listing is otherwise blank", () => {
    expect(listingIdentityKey({}, "fallback-blank")).toBe("fallback-blank");
  });
});
