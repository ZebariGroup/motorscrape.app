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

  beforeEach(() => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({}),
      })),
    );
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
    vi.unstubAllGlobals();
  });

  it("should initialize with default values", () => {
    const { result } = renderHook(() => useSearchStream());
    expect(result.current.search.running).toBe(false);
    expect(result.current.search.reconnecting).toBe(false);
    expect(result.current.form.location).toBe("");
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

  it("should handle reconnecting state", () => {
    const { result } = renderHook(() => useSearchStream());

    act(() => {
      result.current.search.startSearch();
    });

    const es = MockEventSource.instances[0];

    act(() => {
      es.readyState = 0; // CONNECTING
      if (es.onerror) es.onerror();
    });

    expect(result.current.search.reconnecting).toBe(true);
    expect(result.current.search.status).toBe("Connection lost. Reconnecting...");
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

    expect(result.current.listings.listings).toHaveLength(0);

    act(() => {
      const callbacks = [...rafQueue];
      rafQueue = [];
      for (const cb of callbacks) cb(performance.now());
    });

    expect(result.current.listings.listings).toHaveLength(2);
    expect(result.current.listings.listings.map((listing) => listing.model)).toEqual(["F-150", "Bronco"]);
  });
});
