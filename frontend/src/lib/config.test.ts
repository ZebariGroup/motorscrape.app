import { afterEach, describe, expect, it } from "vitest";

import { getApiBaseUrl } from "./config";

describe("getApiBaseUrl", () => {
  const prev = process.env.NEXT_PUBLIC_API_URL;

  afterEach(() => {
    if (prev === undefined) {
      delete process.env.NEXT_PUBLIC_API_URL;
    } else {
      process.env.NEXT_PUBLIC_API_URL = prev;
    }
  });

  it("uses same-origin server prefix when NEXT_PUBLIC_API_URL is unset", () => {
    delete process.env.NEXT_PUBLIC_API_URL;
    expect(getApiBaseUrl()).toBe("/server");
  });

  it("strips trailing slash from configured base", () => {
    process.env.NEXT_PUBLIC_API_URL = "/server/";
    expect(getApiBaseUrl()).toBe("/server");
  });
});
