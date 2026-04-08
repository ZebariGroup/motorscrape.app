import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useSearchStream } from "./useSearchStream";

// Mock EventSource
class MockEventSource {
  url: string;
  readyState: number = 0; // CONNECTING
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners: Record<string, ((ev: MessageEvent) => void)[]> = {};

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (ev: MessageEvent) => void) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }

  removeEventListener(type: string, listener: (ev: MessageEvent) => void) {
    if (!this.listeners[type]) return;
    this.listeners[type] = this.listeners[type].filter((l) => l !== listener);
  }

  close() {
    this.readyState = 2; // CLOSED
  }

  // Helpers for tests
  emit(type: string, data: unknown) {
    const event = new MessageEvent(type, { data: typeof data === "string" ? data : JSON.stringify(data) });
    if (this.listeners[type]) {
      for (const listener of this.listeners[type]) {
        listener(event);
      }
    }
  }

  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  static instances: MockEventSource[] = [];
  static clear() {
    MockEventSource.instances = [];
  }
}

describe("useSearchStream", () => {
  let rafQueue: FrameRequestCallback[] = [];
  let fetchMock: ReturnType<typeof vi.fn>;
  const streamGraceWaitMs = 2150; // 2000ms grace + 150ms buffer
  /** Grace + extended /search/logs polling while the terminal row catches up. */
  const streamFullErrorPathWaitMs = 20_000;

  beforeEach(() => {
    vi.stubGlobal("EventSource", MockEventSource);
    fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({}),
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("requestAnimationFrame", vi.fn((cb: FrameRequestCallback) => {
      rafQueue.push(cb);
      return rafQueue.length;
    }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((handle: number) => {
      const idx = handle - 1;
      if (idx >= 0 && idx < rafQueue.length) {
        rafQueue[idx] = () => 0;
      }
    }));
    rafQueue = [];
    MockEventSource.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("should initialize with default values", () => {
    const { result } = renderHook(() => useSearchStream());
    expect(result.current.search.running).toBe(false);
    expect(result.current.search.reconnecting).toBe(false);
    expect(result.current.form.location).toBe("");
    expect(result.current.form.inventoryScope).toBe("all");
    expect(result.current.form.preferSmallDealers).toBe(false);
  });

  it("should start search and handle events", () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setLocation("Seattle");
      result.current.form.setMake("Ford");
    });

    act(() => {
      result.current.search.startSearch();
    });

    expect(result.current.search.running).toBe(true);
    expect(MockEventSource.instances.length).toBe(1);

    const es = MockEventSource.instances[0];
    
    // Simulate status event
    act(() => {
      es.emit("status", { message: "Finding local dealerships…" });
    });
    expect(result.current.search.status).toBe("Finding local dealerships…");

    // Simulate dealership event
    act(() => {
      es.emit("dealership", { index: 1, name: "Ford Seattle", status: "scraping" });
    });
    expect(result.current.dealers.dealerList.length).toBe(1);
    expect(result.current.dealers.dealerList[0].name).toBe("Ford Seattle");

    // Simulate done event
    act(() => {
      es.emit("done", { ok: true, dealer_deduped_count: 1, dealer_discovery_count: 1 });
    });
    expect(result.current.search.running).toBe(false);
    expect(result.current.search.status).toBe("Search finished · 1 dealerships searched");
  });

  it("should retain structured search errors for quota and upgrade flows", () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setLocation("Seattle");
      result.current.search.startSearch();
    });

    const es = MockEventSource.instances[0];

    act(() => {
      es.emit("search_error", {
        message: "Monthly free search limit reached.",
        code: "quota.monthly_limit_free",
        phase: "quota",
        status: "quota_blocked",
        upgrade_required: true,
        upgrade_tier: "standard",
      });
    });

    expect(result.current.search.errors).toContain("Monthly free search limit reached.");
    expect(result.current.search.errorEvents).toContainEqual(
      expect.objectContaining({
        code: "quota.monthly_limit_free",
        phase: "quota",
        upgrade_required: true,
        upgrade_tier: "standard",
      }),
    );
  });

  it("should surface stream error when the connection drops before done", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSearchStream());

    try {
      act(() => {
        result.current.form.setLocation("Seattle");
        result.current.search.startSearch();
      });

      const es = MockEventSource.instances[0];

      act(() => {
        es.readyState = 0; // CONNECTING (browser would try to reconnect)
        if (es.onerror) es.onerror();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(streamFullErrorPathWaitMs);
      });

      expect(es.readyState).toBe(MockEventSource.CLOSED);
      expect(result.current.search.reconnecting).toBe(false);
      expect(result.current.search.errors).toContain("Connection to search stream lost or failed.");
      expect(result.current.search.running).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("should not surface an error if done arrives before stream error grace period", async () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setLocation("Seattle");
      result.current.search.startSearch();
    });

    const es = MockEventSource.instances[0];

    act(() => {
      if (es.onerror) es.onerror();
      es.emit("done", { ok: true, dealer_deduped_count: 1, dealer_discovery_count: 1 });
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, streamGraceWaitMs));
    });

    expect(result.current.search.running).toBe(false);
    expect(result.current.search.errors).toHaveLength(0);
    expect(result.current.search.status).toBe("Search finished · 1 dealerships searched");
  });

  it("should not treat as failure when error fires before done in the same turn (stream close race)", async () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setLocation("Seattle");
      result.current.search.startSearch();
    });

    const es = MockEventSource.instances[0];

    act(() => {
      es.readyState = 2; // CLOSED — not CONNECTING, so the deferred handler would normally error
      if (es.onerror) es.onerror();
      es.emit("done", { ok: true, dealer_deduped_count: 1, dealer_discovery_count: 1 });
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.search.running).toBe(false);
    expect(result.current.search.errors).toHaveLength(0);
    expect(result.current.search.status).toBe("Search finished · 1 dealerships searched");
  });

  it("should treat as finished when all dealers are terminal even if done SSE is missed", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSearchStream());

    try {
      act(() => {
        result.current.form.setLocation("Seattle");
        result.current.search.startSearch();
      });

      const es = MockEventSource.instances[0];

      act(() => {
        es.emit("dealership", {
          index: 1,
          total: 2,
          name: "Ford Seattle",
          website: "https://ford.example",
          status: "done",
        });
        es.emit("dealership", {
          index: 2,
          total: 2,
          name: "Toyota Seattle",
          website: "https://toyota.example",
          status: "error",
        });
        es.readyState = MockEventSource.CONNECTING;
        if (es.onerror) es.onerror();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(streamFullErrorPathWaitMs);
      });

      expect(result.current.search.running).toBe(false);
      expect(result.current.search.reconnecting).toBe(false);
      expect(result.current.search.errors).toHaveLength(0);
      expect(result.current.search.status).toBe("Search finished · 2 dealerships searched");
    } finally {
      vi.useRealTimers();
    }
  });

  it("should recover a closed stream from the persisted terminal run status", async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/search/logs/")) {
        return {
          ok: true,
          json: async () => ({
            run: {
              correlation_id: "srch-test1234",
              location: "Seattle",
              make: "Ford",
              model: "",
              vehicle_category: "car",
              vehicle_condition: "all",
              inventory_scope: "all",
              radius_miles: 25,
              requested_max_dealerships: 1,
              requested_max_pages_per_dealer: 1,
              result_count: 24,
              status: "success",
              dealer_discovery_count: 1,
              dealer_deduped_count: 1,
              started_at: "2026-03-29T00:00:00Z",
              completed_at: "2026-03-29T00:00:05Z",
            },
          }),
        };
      }
      return {
        ok: true,
        json: async () => ({}),
      };
    });

    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setLocation("Seattle");
      result.current.form.setMake("Ford");
      result.current.search.startSearch();
    });

    const es = MockEventSource.instances[0];

    act(() => {
      es.readyState = 2; // CLOSED after the server ended the one-shot SSE response
      if (es.onerror) es.onerror();
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, streamGraceWaitMs));
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/search/logs/"),
      expect.objectContaining({
        credentials: "include",
      }),
    );
    expect(result.current.search.running).toBe(false);
    expect(result.current.search.errors).toHaveLength(0);
    expect(result.current.search.status).toBe("Search finished · 1 dealerships searched");
  });

  it("should keep polling until a delayed terminal run is persisted", async () => {
    vi.useFakeTimers();
    let logPollCount = 0;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/search/logs/")) {
        logPollCount += 1;
        if (logPollCount < 10) {
          return {
            ok: true,
            json: async () => ({
              run: {
                correlation_id: "srch-test1234",
                status: "running",
              },
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            run: {
              correlation_id: "srch-test1234",
              location: "Seattle",
              make: "Ford",
              model: "",
              vehicle_category: "car",
              vehicle_condition: "all",
              inventory_scope: "all",
              radius_miles: 25,
              requested_max_dealerships: 1,
              requested_max_pages_per_dealer: 1,
              result_count: 24,
              status: "success",
              dealer_discovery_count: 1,
              dealer_deduped_count: 1,
              started_at: "2026-03-29T00:00:00Z",
              completed_at: "2026-03-29T00:00:05Z",
            },
          }),
        };
      }
      return {
        ok: true,
        json: async () => ({}),
      };
    });

    const { result } = renderHook(() => useSearchStream());

    try {
      act(() => {
        result.current.form.setLocation("Seattle");
        result.current.form.setMake("Ford");
        result.current.search.startSearch();
      });

      const es = MockEventSource.instances[0];

      act(() => {
        es.readyState = MockEventSource.CONNECTING;
        if (es.onerror) es.onerror();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(streamFullErrorPathWaitMs);
      });

      expect(logPollCount).toBeGreaterThanOrEqual(10);
      expect(es.readyState).toBe(MockEventSource.CLOSED);
      expect(result.current.search.running).toBe(false);
      expect(result.current.search.errors).toHaveLength(0);
      expect(result.current.search.status).toBe("Search finished · 1 dealerships searched");
    } finally {
      vi.useRealTimers();
    }
  });

  it("should include vehicle category in the stream URL", () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setVehicleCategory("boat");
      result.current.form.setLocation("Seattle");
    });

    act(() => {
      result.current.search.startSearch();
    });

    expect(MockEventSource.instances.length).toBe(1);
    expect(MockEventSource.instances[0].url).toContain("vehicle_category=boat");
  });

  it("should include smaller-dealer bias in the stream URL when enabled", () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setLocation("Seattle");
      result.current.form.setPreferSmallDealers(true);
    });

    act(() => {
      result.current.search.startSearch();
    });

    expect(MockEventSource.instances.length).toBe(1);
    expect(MockEventSource.instances[0].url).toContain("prefer_small_dealers=true");
  });

  it("should stop the backend search by correlation id", async () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setLocation("Seattle");
      result.current.search.startSearch();
    });

    const es = MockEventSource.instances[0];
    const cid = new URL(es.url).searchParams.get("correlation_id");
    expect(cid).toMatch(/^srch-/);

    await act(async () => {
      await result.current.search.stopStream();
    });

    expect(result.current.search.running).toBe(false);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining(`/search/stop/${cid}`),
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      }),
    );
  });

  it("should batch vehicle events until the scheduled flush runs", () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setLocation("Seattle");
      result.current.search.startSearch();
    });

    const es = MockEventSource.instances[0];

    act(() => {
      es.emit("vehicles", {
        dealership: "Ford Seattle",
        website: "https://ford.example",
        listings: [{ model: "F-150", year: 2024 }],
      });
      es.emit("vehicles", {
        dealership: "Ford Seattle",
        website: "https://ford.example",
        listings: [{ model: "Bronco", year: 2025 }],
      });
    });

    expect(result.current.listings.listings).toHaveLength(1);

    act(() => {
      const callbacks = [...rafQueue];
      rafQueue = [];
      for (const cb of callbacks) cb(performance.now());
    });

    expect(result.current.listings.listings).toHaveLength(2);
    expect(result.current.listings.listings.map((listing) => listing.model)).toEqual(["F-150", "Bronco"]);
  });

  it("should summarize queued dealers before scraping starts", () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.form.setLocation("Seattle");
      result.current.search.startSearch();
    });

    const es = MockEventSource.instances[0];

    act(() => {
      es.emit("dealership", {
        index: 1,
        total: 2,
        name: "Ford Seattle",
        website: "https://ford.example",
        status: "queued",
      });
      es.emit("dealership", {
        index: 2,
        total: 2,
        name: "Toyota Seattle",
        website: "https://toyota.example",
        status: "queued",
      });
    });

    expect(result.current.dealers.queuedDealerCount).toBe(2);
    expect(result.current.dealers.activeDealerSummary).toBe("2 dealers queued");
  });
});
