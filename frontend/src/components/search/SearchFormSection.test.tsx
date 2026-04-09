import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchFormSection } from "./SearchFormSection";

vi.mock("./MultiModelSelect", () => ({
  MultiModelSelect: () => <div data-testid="multi-model-select" />,
}));

vi.mock("./PlowTruck", () => ({
  PlowTruck: () => <div data-testid="plow-truck" />,
}));

vi.mock("./ScrapeMiniGame", () => ({
  ScrapeMiniGame: () => <div>Mini game</div>,
}));

vi.mock("./SearchWaitFactsRotator", () => ({
  SearchWaitFactsRotator: () => <div>Wait facts</div>,
}));

vi.mock("./SearchHistoryModal", () => ({
  SearchHistoryModal: () => null,
}));

function stubMatchMedia() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width: 639px"),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

const baseProps = {
  running: false,
  reconnecting: false,
  location: "Seattle, WA",
  setLocation: vi.fn(),
  vehicleCategory: "car" as const,
  make: "Toyota",
  setMake: vi.fn(),
  model: "Tacoma",
  setModel: vi.fn(),
  modelOptions: ["Tacoma"],
  usesCatalog: false,
  vehicleCondition: "used",
  setVehicleCondition: vi.fn(),
  radiusMiles: "25",
  setRadiusMiles: vi.fn(),
  inventoryScope: "all",
  setInventoryScope: vi.fn(),
  maxDealerships: "8",
  setMaxDealerships: vi.fn(),
  onSearch: vi.fn(),
  onStop: vi.fn(),
  canSearch: true,
  searchReadinessHint: null,
  status: null,
  errors: [],
  discoveredDealerPercent: 25,
  completedDealerPercent: 10,
  dealerListLength: 2,
  targetDealerCount: 8,
  doneDealerCount: 1,
  activeDealerSummary: null,
  listingsCount: 4,
  maxDealersCap: 30,
  maxRadiusMilesCap: 250,
  inventoryScopePremium: true,
  allowAnyModel: true,
  applySavedSearchFromHistory: vi.fn(async () => {}),
  applyHistoryCriteriaOnly: vi.fn(async () => {}),
  marketRegion: "us" as const,
};

describe("SearchFormSection", () => {
  beforeEach(() => {
    stubMatchMedia();
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 375,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("keeps the form expanded on mobile while scraping so the consolidated panel stays visible", () => {
    const { rerender } = render(<SearchFormSection {...baseProps} />);

    fireEvent.click(screen.getByRole("button", { name: "Scrape inventory" }));
    expect(baseProps.onSearch).toHaveBeenCalledTimes(1);

    rerender(<SearchFormSection {...baseProps} running />);

    expect(screen.queryByRole("button", { name: "Edit scrape" })).toBeNull();
    expect(screen.getByText("Scraping inventory")).not.toBeNull();
    const section = screen.getByText("Scraping inventory").closest("section");
    expect(section?.className).not.toContain("sticky");
  });

  it("shows status, active dealers, and wait facts in the scrape panel when running expanded", () => {
    const { rerender } = render(<SearchFormSection {...baseProps} />);

    rerender(
      <SearchFormSection
        {...baseProps}
        running
        status="Searching dealers"
        activeDealerSummary="2 dealers queued"
      />,
    );

    expect(screen.getByText("Scraping inventory")).not.toBeNull();
    expect(screen.getByText("Searching dealers")).not.toBeNull();
    expect(screen.getByText("2 dealers queued")).not.toBeNull();
    expect(screen.getByText("Wait facts")).not.toBeNull();
  });
});
