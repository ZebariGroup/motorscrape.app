import { describe, expect, it } from "vitest";

import { clampPercent, formatMoney } from "./inventoryFormat";

describe("inventoryFormat", () => {
  it("formatMoney returns em dash for undefined", () => {
    expect(formatMoney(undefined)).toBe("—");
  });

  it("clampPercent bounds", () => {
    expect(clampPercent(-5)).toBe(0);
    expect(clampPercent(50)).toBe(50);
    expect(clampPercent(150)).toBe(100);
  });
});
