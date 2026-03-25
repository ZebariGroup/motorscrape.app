import { describe, expect, it } from "vitest";

import { buildLocationLabelFromNominatimAddress } from "./reverseGeocodeLabel";

describe("buildLocationLabelFromNominatimAddress", () => {
  it("prefers city and state for US", () => {
    expect(
      buildLocationLabelFromNominatimAddress({
        city: "Ann Arbor",
        state: "Michigan",
        postcode: "48103",
        country_code: "us",
      }),
    ).toBe("Ann Arbor, Michigan");
  });

  it("falls back to postcode and state", () => {
    expect(
      buildLocationLabelFromNominatimAddress({
        state: "MI",
        postcode: "48103",
        country_code: "us",
      }),
    ).toBe("48103, MI");
  });

  it("returns null when empty", () => {
    expect(buildLocationLabelFromNominatimAddress({})).toBeNull();
  });
});
