import { describe, expect, it } from "vitest";
import { buildSearchWaitFacts, describeVehiclePhrase } from "./vehicleSearchFacts";

describe("describeVehiclePhrase", () => {
  it("combines make and first model when both set", () => {
    expect(describeVehiclePhrase("Ford", "F-150, Maverick")).toBe("Ford F-150");
  });

  it("uses make only when model empty", () => {
    expect(describeVehiclePhrase("Toyota", "")).toBe("Toyota");
  });

  it("falls back when make empty", () => {
    expect(describeVehiclePhrase("", "")).toBe("the vehicles you're searching for");
  });
});

describe("buildSearchWaitFacts", () => {
  it("returns several unique tips for a typical car search", () => {
    const facts = buildSearchWaitFacts({
      make: "Honda",
      model: "Civic",
      vehicleCategory: "car",
      vehicleCondition: "all",
    });
    expect(facts.length).toBeGreaterThanOrEqual(6);
    expect(new Set(facts).size).toBe(facts.length);
    expect(facts.some((f) => f.includes("Honda Civic"))).toBe(true);
  });

  it("includes used-specific guidance when condition is used", () => {
    const facts = buildSearchWaitFacts({
      make: "Subaru",
      model: "Outback",
      vehicleCategory: "car",
      vehicleCondition: "used",
    });
    expect(facts.some((f) => /used/i.test(f) && f.includes("Subaru Outback"))).toBe(true);
  });
});
