import { describe, expect, it } from "vitest";

import { getMakesForCategory, getModelsForMake } from "./vehicleCatalog";

describe("vehicleCatalog", () => {
  it("exposes major motorcycle makes", () => {
    expect(getMakesForCategory("motorcycle")).toContain("Honda");
    expect(getMakesForCategory("motorcycle")).toContain("Harley-Davidson");
    expect(getMakesForCategory("motorcycle")).toContain("BMW Motorrad");
  });

  it("exposes major boat models for selected makes", () => {
    expect(getModelsForMake("boat", "Sea Ray")).toContain("SLX 280");
    expect(getModelsForMake("boat", "Yamaha Boats")).toContain("255XD");
  });
});
