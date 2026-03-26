import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useSearchStream } from "./useSearchStream";

// Mock EventSource
class MockEventSource {
  url: string;
  readyState: number = 0; // CONNECTING
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners: Record<string, ((ev: any) => void)[]> = {};

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (ev: any) => void) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }

  removeEventListener(type: string, listener: (ev: any) => void) {
    if (!this.listeners[type]) return;
    this.listeners[type] = this.listeners[type].filter((l) => l !== listener);
  }

  close() {
    this.readyState = 2; // CLOSED
  }

  // Helpers for tests
  emit(type: string, data: any) {
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
  beforeEach(() => {
    vi.stubGlobal("EventSource", MockEventSource);
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
});
