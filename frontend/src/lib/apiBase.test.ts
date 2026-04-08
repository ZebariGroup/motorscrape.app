import { afterEach, describe, expect, it } from "vitest";

import { getApiBaseUrl, resolveApiUrl } from "./apiBase";

describe("apiBase", () => {
  const prev = process.env.NEXT_PUBLIC_API_URL;

  afterEach(() => {
    if (prev === undefined) delete process.env.NEXT_PUBLIC_API_URL;
    else process.env.NEXT_PUBLIC_API_URL = prev;
  });

  it("getApiBaseUrl falls back to localhost when unset", () => {
    delete process.env.NEXT_PUBLIC_API_URL;
    expect(getApiBaseUrl()).toBe("http://localhost:8000");
  });

  it("resolveApiUrl joins absolute base", () => {
    process.env.NEXT_PUBLIC_API_URL = "http://127.0.0.1:9999";
    expect(resolveApiUrl("/search/stream")).toBe("http://127.0.0.1:9999/search/stream");
  });
});
