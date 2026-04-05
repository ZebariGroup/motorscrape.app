import { describe, expect, it } from "vitest";

import { clampPercent, formatMoney, formatObservedAtForDisplay, listingIdentityKey } from "./inventoryFormat";

describe("inventoryFormat", () => {
  it("formatMoney returns em dash for undefined", () => {
    expect(formatMoney(undefined)).toBe("—");
  });

  it("formatMoney supports a custom empty label", () => {
    expect(formatMoney(undefined, "Visit site for price")).toBe("Visit site for price");
  });

  it("formatObservedAtForDisplay treats Unix seconds like backend price_history (not 1970)", () => {
    const unixSeconds = 1_700_000_000;
    expect(formatObservedAtForDisplay(unixSeconds)).toBe(new Date(unixSeconds * 1000).toLocaleDateString());
  });

  it("formatObservedAtForDisplay treats epoch ms when large enough", () => {
    const ms = 1_704_067_200_000;
    expect(formatObservedAtForDisplay(ms)).toBe(new Date(ms).toLocaleDateString());
  });

  it("formatObservedAtForDisplay parses ISO timestamps", () => {
    expect(formatObservedAtForDisplay("2026-04-05T12:00:00.000Z")).toBe(
      new Date("2026-04-05T12:00:00.000Z").toLocaleDateString(),
    );
  });

  it("formatObservedAtForDisplay returns em dash for empty or invalid", () => {
    expect(formatObservedAtForDisplay(undefined)).toBe("—");
    expect(formatObservedAtForDisplay("")).toBe("—");
    expect(formatObservedAtForDisplay(Number.NaN)).toBe("—");
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
