import { describe, expect, it } from "vitest";

import { getMakesForCategory, getModelsForMake } from "./vehicleCatalog";

describe("vehicleCatalog", () => {
  it("exposes major motorcycle makes", () => {
    expect(getMakesForCategory("motorcycle")).toContain("Honda");
    expect(getMakesForCategory("motorcycle")).toContain("Harley-Davidson");
    expect(getMakesForCategory("motorcycle")).toContain("BMW Motorrad");
  });

  it("exposes a broader set of major boat makes", () => {
    expect(getMakesForCategory("boat")).toContain("Axis");
    expect(getMakesForCategory("boat")).toContain("Starcraft");
    expect(getMakesForCategory("boat")).toContain("Key West Boats");
    expect(getMakesForCategory("boat")).toContain("Chris Craft");
  });

  it("exposes major boat models for selected makes", () => {
    expect(getModelsForMake("boat", "Sea Ray")).toContain("SLX 280");
    expect(getModelsForMake("boat", "Yamaha Boats")).toContain("255XD");
    expect(getModelsForMake("boat", "Axis")).toContain("A225");
    expect(getModelsForMake("boat", "Starcraft")).toContain("SVX 191 OB");
  });
});
