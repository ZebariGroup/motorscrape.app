import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ScrapeMiniGame } from "./ScrapeMiniGame";

type RafCallback = FrameRequestCallback;

const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");

class MockResizeObserver {
  observe() {}
  disconnect() {}
}

function createMockContext(): CanvasRenderingContext2D {
  const gradient = { addColorStop: vi.fn() };
  return {
    beginPath: vi.fn(),
    createLinearGradient: vi.fn(() => gradient),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    lineTo: vi.fn(),
    measureText: vi.fn((text: string) => ({ width: text.length * 10 })),
    moveTo: vi.fn(),
    restore: vi.fn(),
    save: vi.fn(),
    setTransform: vi.fn(),
    stroke: vi.fn(),
    strokeRect: vi.fn(),
    translate: vi.fn(),
    scale: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    rect: vi.fn(),
    roundRect: vi.fn(),
  } as unknown as CanvasRenderingContext2D;
}

describe("ScrapeMiniGame", () => {
  let now = 0;
  let mockWidth = 480;
  let mockHeight = 224;
  let rafQueue: RafCallback[] = [];

  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get() {
        return mockWidth;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      get() {
        return mockHeight;
      },
    });

    vi.stubGlobal("ResizeObserver", MockResizeObserver);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(createMockContext());
    vi.spyOn(performance, "now").mockImplementation(() => now);

    rafQueue = [];
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((cb: RafCallback) => {
        rafQueue.push(cb);
        return rafQueue.length;
      }),
    );
    vi.stubGlobal(
      "cancelAnimationFrame",
      vi.fn((handle: number) => {
        const idx = handle - 1;
        if (idx >= 0 && idx < rafQueue.length) {
          rafQueue[idx] = () => 0;
        }
      }),
    );
  });

  afterEach(() => {
    cleanup();
    if (originalClientWidth) {
      Object.defineProperty(HTMLElement.prototype, "clientWidth", originalClientWidth);
    }
    if (originalClientHeight) {
      Object.defineProperty(HTMLElement.prototype, "clientHeight", originalClientHeight);
    }
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function runNextFrame(nextNow: number) {
    const cb = rafQueue.shift();
    if (!cb) {
      throw new Error("No animation frame scheduled");
    }
    now = nextNow;
    act(() => {
      cb(nextNow);
    });
  }

  it("keeps the loop alive if the canvas starts with zero size", () => {
    mockWidth = 0;
    mockHeight = 0;

    const { getByRole } = render(<ScrapeMiniGame onClose={() => {}} searchCompletedTick={0} />);

    act(() => {
      fireEvent.pointerDown(getByRole("application"), {
        button: 0,
        pointerType: "mouse",
      });
    });

    expect(rafQueue).toHaveLength(1);

    runNextFrame(16);
    expect(rafQueue).toHaveLength(1);

    mockWidth = 480;
    mockHeight = 224;

    runNextFrame(32);
    expect(rafQueue).toHaveLength(1);
    expect(screen.queryByText("Pick your ride and hit the lane")).toBeNull();
  });

  it("does not turn the first keyboard start into an immediate jump", () => {
    const { container, getByRole } = render(<ScrapeMiniGame onClose={() => {}} searchCompletedTick={0} />);

    const app = getByRole("application");
    act(() => {
      app.focus();
      fireEvent.keyDown(app, { key: " ", code: "Space" });
    });

    expect(rafQueue).toHaveLength(1);

    runNextFrame(16);

    const player = container.querySelector(".will-change-transform") as HTMLDivElement | null;
    expect(player).not.toBeNull();
    expect(player?.style.transform).toContain("translateY(0px)");
  });
});
