"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { EmailAlertPanel } from "@/components/search/EmailAlertPanel";
import { MultiModelSelect } from "@/components/search/MultiModelSelect";
import { resolveApiUrl } from "@/lib/apiBase";
import {
  kmToMiles,
  MARKET_REGION_STORAGE_KEY,
  milesToKm,
  parseMarketRegion,
  type MarketRegion,
} from "@/lib/marketRegion";
import {
  ENABLED_VEHICLE_CATEGORY_OPTIONS,
  categoryUsesCatalog,
  defaultVehicleCategory,
  getMakesForCategory,
  getModelsForMake,
  vehicleCategoryLabel,
} from "@/lib/vehicleCatalog";
import type { VehicleCategory } from "@/lib/vehicleCatalog";
import type { AccessSummary } from "@/types/access";
import type { AlertDashboardResponse, AlertRun, AlertSubscription } from "@/types/alerts";

const RADIUS_CHOICES = [10, 25, 30, 50, 75, 100, 150, 250] as const;
const DEALER_STEPS = [4, 6, 8, 10, 12, 16, 18, 24, 30] as const;

type Props = {
  authenticated: boolean;
  tier: string;
  access: AccessSummary | null;
};

function dealerChoices(cap: number): number[] {
  const xs = DEALER_STEPS.filter((n) => n <= cap);
  if (xs.length > 0) return [...xs];
  return [Math.max(1, Math.min(cap, 30))];
}

function isPaidTier(tier: string): boolean {
  return ["standard", "premium", "max_pro", "enterprise", "custom"].includes((tier || "").toLowerCase());
}

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}

function criteriaLabel(criteria: AlertSubscription["criteria"]): string {
  const parts = [criteria.vehicle_category, criteria.location, criteria.make, criteria.model].filter(Boolean);
  return parts.join(" · ");
}

export function AlertManagerSection({ authenticated, tier, access }: Props) {
  const paid = useMemo(() => isPaidTier(tier), [tier]);
  const [data, setData] = useState<AlertDashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [location, setLocation] = useState("");
  const [vehicleCategory, setVehicleCategory] = useState<VehicleCategory>(() => defaultVehicleCategory());
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [vehicleCondition, setVehicleCondition] = useState<AlertSubscription["criteria"]["vehicle_condition"]>("all");
  const [radiusMiles, setRadiusMiles] = useState("25");
  const [inventoryScope, setInventoryScope] = useState<AlertSubscription["criteria"]["inventory_scope"]>("all");
  const [maxDealerships, setMaxDealerships] = useState("8");
  const [marketRegion] = useState<MarketRegion>(() => {
    if (typeof window === "undefined") return "us";
    return parseMarketRegion(localStorage.getItem(MARKET_REGION_STORAGE_KEY));
  });

  const load = useCallback(async () => {
    if (!authenticated || !paid) return;
    try {
      const response = await fetch(resolveApiUrl("/alerts/subscriptions"), { credentials: "include" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Unable to load alerts.");
        return;
      }
      setData(payload as AlertDashboardResponse);
      setError(null);
    } catch {
      setError("Unable to load alerts.");
    }
  }, [authenticated, paid]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxDealersCap = access?.limits?.max_dealerships ?? data?.limits.max_dealerships ?? 30;
  const maxRadiusCap = access?.limits?.max_radius_miles ?? data?.limits.max_radius_miles ?? 250;
  const inventoryScopePremium = access?.limits?.inventory_scope_premium ?? true;
  const allowAnyModel = ["premium", "max_pro", "enterprise", "custom"].includes(tier.toLowerCase());
  const usesCatalog = useMemo(() => categoryUsesCatalog(vehicleCategory), [vehicleCategory]);
  const makeOptions = useMemo(() => getMakesForCategory(vehicleCategory, marketRegion), [marketRegion, vehicleCategory]);
  const modelOptions = useMemo(() => getModelsForMake(vehicleCategory, make, marketRegion), [make, marketRegion, vehicleCategory]);
  const radiusOptions = useMemo(() => RADIUS_CHOICES.filter((miles) => miles <= maxRadiusCap), [maxRadiusCap]);
  const radiusKmOptions = useMemo(() => {
    const capKm = milesToKm(maxRadiusCap);
    return [10, 25, 40, 50, 80, 100, 150, 200].filter((km) => km <= capKm);
  }, [maxRadiusCap]);
  const dealerOptions = useMemo(() => dealerChoices(maxDealersCap), [maxDealersCap]);
  const canCreateAlert = location.trim().length >= 2 && (allowAnyModel || model.trim().length > 0);
  const draftCriteria = {
    location: location.trim(),
    make: make.trim(),
    model: model.trim(),
    vehicle_category: vehicleCategory,
    vehicle_condition: vehicleCondition,
    radius_miles: Number.parseInt(radiusMiles, 10) || 25,
    inventory_scope: inventoryScope,
    max_dealerships: Number.parseInt(maxDealerships, 10) || null,
    max_pages_per_dealer: null,
    market_region: marketRegion,
  };

  useEffect(() => {
    const parsed = Number.parseInt(maxDealerships, 10);
    const next = Number.isFinite(parsed) ? Math.min(parsed, maxDealersCap) : Math.min(8, maxDealersCap);
    if (String(next) !== maxDealerships) {
      setMaxDealerships(String(next));
    }
  }, [maxDealersCap, maxDealerships]);

  useEffect(() => {
    const parsed = Number.parseInt(radiusMiles, 10);
    if (Number.isFinite(parsed) && parsed > maxRadiusCap) {
      setRadiusMiles(String(maxRadiusCap));
    }
  }, [maxRadiusCap, radiusMiles]);

  useEffect(() => {
    if (marketRegion !== "eu") return;
    const mi = Number.parseInt(radiusMiles, 10);
    if (!Number.isFinite(mi)) return;
    const validMiles = new Set(radiusKmOptions.map((km) => kmToMiles(km)));
    if (validMiles.has(mi)) return;
    const nearest = [...validMiles].reduce((a, b) => (Math.abs(b - mi) < Math.abs(a - mi) ? b : a));
    setRadiusMiles(String(nearest));
  }, [marketRegion, radiusKmOptions, radiusMiles]);

  useEffect(() => {
    if (!inventoryScopePremium && inventoryScope !== "all") {
      setInventoryScope("all");
    }
  }, [inventoryScope, inventoryScopePremium]);

  const mutateSubscription = async (subscriptionId: string, body: Record<string, unknown>) => {
    setBusyId(subscriptionId);
    try {
      const response = await fetch(resolveApiUrl(`/alerts/subscriptions/${subscriptionId}`), {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Unable to update the alert.");
        return;
      }
      await load();
    } catch {
      setError("Unable to update the alert.");
    } finally {
      setBusyId(null);
    }
  };

  const runNow = async (subscriptionId: string) => {
    setBusyId(subscriptionId);
    try {
      const response = await fetch(resolveApiUrl(`/alerts/subscriptions/${subscriptionId}/run`), {
        method: "POST",
        credentials: "include",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Unable to run the alert.");
        return;
      }
      await load();
    } catch {
      setError("Unable to run the alert.");
    } finally {
      setBusyId(null);
    }
  };

  const removeSubscription = async (subscriptionId: string) => {
    setBusyId(subscriptionId);
    try {
      const response = await fetch(resolveApiUrl(`/alerts/subscriptions/${subscriptionId}`), {
        method: "DELETE",
        credentials: "include",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Unable to delete the alert.");
        return;
      }
      await load();
    } catch {
      setError("Unable to delete the alert.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Email alerts
      </h2>
      {!authenticated ? (
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          Log in to manage paid email alerts and scheduled runs.
        </p>
      ) : !paid ? (
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          Email alerts, recurring runs, and CSV delivery are available on Standard and above.
        </p>
      ) : (
        <div className="mt-3 space-y-5">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Build alerts here or from the search page, then manage or run them below.
          </p>
          <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
            <div className="space-y-1">
              <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Create alert from settings</h3>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                Choose the inventory search you want emailed to your account on a schedule.
              </p>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Location</span>
                <input
                  value={location}
                  onChange={(event) => setLocation(event.target.value)}
                  placeholder="City or ZIP"
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Vehicle category</span>
                <select
                  value={vehicleCategory}
                  onChange={(event) => {
                    const nextCategory = event.target.value as VehicleCategory;
                    setVehicleCategory(nextCategory);
                    setMake("");
                    setModel("");
                  }}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  {ENABLED_VEHICLE_CATEGORY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Make</span>
                {usesCatalog ? (
                  <select
                    value={make}
                    onChange={(event) => {
                      setMake(event.target.value);
                      setModel("");
                    }}
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  >
                    {allowAnyModel && <option value="">Any make</option>}
                    {!allowAnyModel && !make ? <option value="" disabled>Select make</option> : null}
                    {makeOptions.map((makeOption) => (
                      <option key={makeOption} value={makeOption}>
                        {makeOption}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={make}
                    onChange={(event) => setMake(event.target.value)}
                    placeholder={`${vehicleCategoryLabel(vehicleCategory)} make`}
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  />
                )}
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Model</span>
                {usesCatalog ? (
                  <MultiModelSelect
                    models={modelOptions}
                    selectedModels={model ? model.split(",").filter(Boolean) : []}
                    onChange={(models) => setModel(models.join(","))}
                    disabled={false}
                    allowAnyModel={allowAnyModel}
                  />
                ) : (
                  <input
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                    placeholder="Model or comma-separated models"
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  />
                )}
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Condition</span>
                <select
                  value={vehicleCondition}
                  onChange={(event) =>
                    setVehicleCondition(event.target.value as AlertSubscription["criteria"]["vehicle_condition"])
                  }
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  <option value="all">All</option>
                  <option value="new">New only</option>
                  <option value="used">Used only</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">
                  Radius ({marketRegion === "eu" ? "km" : "miles"})
                </span>
                <select
                  value={radiusMiles}
                  onChange={(event) => setRadiusMiles(event.target.value)}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  {marketRegion === "eu"
                    ? radiusKmOptions.map((km) => (
                        <option key={km} value={String(kmToMiles(km))}>
                          {km} km
                        </option>
                      ))
                    : radiusOptions.map((miles) => (
                        <option key={miles} value={String(miles)}>
                          {miles} miles
                        </option>
                      ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Inventory scope</span>
                <select
                  value={inventoryScope}
                  onChange={(event) =>
                    setInventoryScope(event.target.value as AlertSubscription["criteria"]["inventory_scope"])
                  }
                  disabled={!inventoryScopePremium}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  <option value="all">All listed</option>
                  <option value="on_lot_only" disabled={!inventoryScopePremium}>
                    On lot only
                  </option>
                  <option value="exclude_shared" disabled={!inventoryScopePremium}>
                    Exclude shared/off-site
                  </option>
                  <option value="include_transit" disabled={!inventoryScopePremium}>
                    Include in transit
                  </option>
                </select>
                {!inventoryScopePremium ? (
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    Advanced inventory scope is available on Standard and above.
                  </span>
                ) : null}
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Max dealerships</span>
                <select
                  value={maxDealerships}
                  onChange={(event) => setMaxDealerships(event.target.value)}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  {dealerOptions.map((count) => (
                    <option key={count} value={String(count)}>
                      {count}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="mt-4">
              <EmailAlertPanel
                access={access}
                tierOverride={tier}
                criteria={draftCriteria}
                canSearch={canCreateAlert}
                title="Save this alert"
                description="Use the criteria above to schedule recurring email results to your account address."
                onSaved={load}
              />
            </div>
          </div>
          {!data?.email_configured ? (
            <p className="rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
              Email delivery is not configured yet. Alerts can be saved, but sends will fail until the email provider settings are added.
            </p>
          ) : null}
          {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}

          <div className="space-y-3">
            <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Active subscriptions</h3>
            {data?.subscriptions.length ? (
              data.subscriptions.map((subscription) => (
                <article
                  key={subscription.id}
                  className="rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-800"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="space-y-1">
                      <p className="font-medium text-zinc-900 dark:text-zinc-50">{subscription.name}</p>
                      <p className="text-sm text-zinc-600 dark:text-zinc-400">{criteriaLabel(subscription.criteria)}</p>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">
                        {subscription.cadence === "weekly" ? "Weekly" : "Daily"} at{" "}
                        {subscription.hour_local.toString().padStart(2, "0")}:00 ({subscription.timezone})
                        {" · "}Next run {formatWhen(subscription.next_run_at)}
                      </p>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">
                        Last run: {subscription.last_run_status ?? "never"}{" "}
                        {subscription.last_result_count != null ? `· ${subscription.last_result_count} vehicles` : ""}
                      </p>
                      {subscription.last_error ? (
                        <p className="text-xs text-red-600 dark:text-red-400">{subscription.last_error}</p>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={busyId === subscription.id}
                        onClick={() =>
                          void mutateSubscription(subscription.id, { is_active: !subscription.is_active })
                        }
                        className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-800 dark:border-zinc-700 dark:text-zinc-100 disabled:opacity-50"
                      >
                        {subscription.is_active ? "Pause" : "Resume"}
                      </button>
                      <button
                        type="button"
                        disabled={busyId === subscription.id}
                        onClick={() => void runNow(subscription.id)}
                        className="rounded-lg border border-emerald-300 px-3 py-1.5 text-sm font-medium text-emerald-800 dark:border-emerald-800 dark:text-emerald-300 disabled:opacity-50"
                      >
                        Run now
                      </button>
                      <button
                        type="button"
                        disabled={busyId === subscription.id}
                        onClick={() => void removeSubscription(subscription.id)}
                        className="rounded-lg border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 dark:border-red-900 dark:text-red-300 disabled:opacity-50"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </article>
              ))
            ) : (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">No alert subscriptions yet.</p>
            )}
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Recent runs</h3>
            {data?.runs.length ? (
              data.runs.map((run: AlertRun) => (
                <article key={run.id} className="rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-800">
                  <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                        {run.status} · {run.result_count} vehicles
                      </p>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">
                        {run.trigger_source} · {formatWhen(run.started_at)}
                        {run.emailed ? " · emailed" : " · email not sent"}
                        {run.csv_attached ? " · CSV attached" : ""}
                      </p>
                      {run.error_message ? (
                        <p className="text-xs text-red-600 dark:text-red-400">{run.error_message}</p>
                      ) : null}
                    </div>
                  </div>
                </article>
              ))
            ) : (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">No alert runs yet.</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
