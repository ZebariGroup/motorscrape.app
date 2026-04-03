import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AccessSummary } from "@/types/access";

import { EmailAlertPanel } from "./EmailAlertPanel";

const access: AccessSummary = {
  authenticated: true,
  tier: "standard",
  is_admin: false,
  limits: {
    max_dealerships: 8,
    max_pages_per_dealer: 3,
    max_radius_miles: 100,
    csv_export: true,
    inventory_scope_premium: true,
    minute_rate_limit: 10,
  },
};

describe("EmailAlertPanel", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("submits change-aware delivery settings", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ subscription: { id: "sub_123" } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <EmailAlertPanel
        access={access}
        criteria={{
          location: "Seattle, WA",
          make: "Toyota",
          model: "Tacoma",
          vehicle_category: "car",
          vehicle_condition: "used",
          radius_miles: 25,
          inventory_scope: "all",
          max_dealerships: 8,
          max_pages_per_dealer: 3,
          market_region: "us",
        }}
        canSearch
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Create email alert" }));
    fireEvent.change(screen.getByLabelText("Alert name"), { target: { value: "Tacoma drops" } });
    fireEvent.click(screen.getByLabelText("Only send this alert when meaningful changes are detected."));
    fireEvent.click(screen.getByLabelText("Include newly seen listings as changes."));
    fireEvent.change(screen.getByLabelText("Minimum price drop (USD)"), { target: { value: "750" } });
    fireEvent.click(screen.getByRole("button", { name: "Save alert" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const payload = JSON.parse(String(requestInit.body));

    expect(payload.only_send_on_changes).toBe(true);
    expect(payload.include_new_listings).toBe(false);
    expect(payload.include_price_drops).toBe(true);
    expect(payload.min_price_drop_usd).toBe(750);
  });
});
