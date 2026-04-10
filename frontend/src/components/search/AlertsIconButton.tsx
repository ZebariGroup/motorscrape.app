"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { resolveApiUrl } from "@/lib/apiBase";
import { milesToKm } from "@/lib/marketRegion";
import type { AccessSummary } from "@/types/access";
import type { AlertCriteria } from "@/types/alerts";

const WEEKDAY_OPTIONS = [
  { value: 0, label: "Monday" },
  { value: 1, label: "Tuesday" },
  { value: 2, label: "Wednesday" },
  { value: 3, label: "Thursday" },
  { value: 4, label: "Friday" },
  { value: 5, label: "Saturday" },
  { value: 6, label: "Sunday" },
] as const;

function isPaidTier(tier: string | null | undefined): boolean {
  return ["standard", "premium", "max_pro", "enterprise", "custom"].includes((tier ?? "").toLowerCase());
}

type Props = {
  access: AccessSummary | null;
  criteria: AlertCriteria;
  canSearch: boolean;
};

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3">
      <span className="text-sm text-zinc-700 dark:text-zinc-300">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 ${checked ? "bg-emerald-500" : "bg-zinc-300 dark:bg-zinc-600"}`}
      >
        <span
          className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${checked ? "translate-x-4" : "translate-x-0"}`}
        />
      </button>
    </label>
  );
}

export function AlertsIconButton({ access, criteria, canSearch }: Props) {
  const paid = isPaidTier(access?.tier);
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState("");
  const [cadence, setCadence] = useState<"daily" | "weekly">("daily");
  const [dayOfWeek, setDayOfWeek] = useState("0");
  const [hourLocal, setHourLocal] = useState("8");
  const [deliverCsv, setDeliverCsv] = useState(true);
  const [onlySendOnChanges, setOnlySendOnChanges] = useState(false);
  const [includeNewListings, setIncludeNewListings] = useState(true);
  const [includePriceDrops, setIncludePriceDrops] = useState(true);
  const [minPriceDropUsd, setMinPriceDropUsd] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const timezone = useMemo(() => {
    if (typeof Intl === "undefined") return "UTC";
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  }, []);

  const defaultName = useMemo(() => {
    const parts = [criteria.location, criteria.make, criteria.model].filter(Boolean);
    return parts.join(" · ") || "Scheduled alert";
  }, [criteria.location, criteria.make, criteria.model]);

  const radiusLabel = useMemo(() => {
    if ((criteria.market_region ?? "us") === "eu") return `${milesToKm(criteria.radius_miles)} km`;
    return `${criteria.radius_miles} mi`;
  }, [criteria.market_region, criteria.radius_miles]);

  const openModal = () => {
    setName((prev) => prev || defaultName);
    setError(null);
    setMessage(null);
    setIsOpen(true);
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(resolveApiUrl("/alerts/subscriptions"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: (name || defaultName).trim(),
          criteria,
          cadence,
          day_of_week: cadence === "weekly" ? Number(dayOfWeek) : null,
          hour_local: Number(hourLocal),
          timezone,
          deliver_csv: deliverCsv,
          only_send_on_changes: onlySendOnChanges,
          include_new_listings: includeNewListings,
          include_price_drops: includePriceDrops,
          min_price_drop_usd: includePriceDrops && minPriceDropUsd.trim() ? Number(minPriceDropUsd) : null,
          is_active: true,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Unable to save the email alert.");
        return;
      }
      setMessage("Alert saved — you'll receive emails on schedule.");
      setIsOpen(false);
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const inputClass =
    "w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50";

  return (
    <>
      {/* Mail icon button */}
      <button
        type="button"
        onClick={openModal}
        title="Email alert settings"
        aria-label="Email alert settings"
        className="relative flex h-8 w-8 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
      >
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
          <rect x="2" y="4" width="16" height="13" rx="2" stroke="currentColor" strokeWidth="1.6" />
          <path d="M2 7l8 5 8-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        {message ? (
          <span className="absolute -right-0.5 -top-0.5 flex h-2 w-2 rounded-full bg-emerald-500" />
        ) : null}
      </button>

      {/* Modal */}
      {isOpen ? (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-zinc-900/60 p-4 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) setIsOpen(false); }}
        >
          <div className="flex w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-800 dark:bg-zinc-950">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-50 dark:bg-emerald-950/60">
                  <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
                    <rect x="2" y="4" width="16" height="13" rx="2" stroke="currentColor" strokeWidth="1.6" className="stroke-emerald-600 dark:stroke-emerald-400" />
                    <path d="M2 7l8 5 8-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" className="stroke-emerald-600 dark:stroke-emerald-400" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Scheduled email alert</h2>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Results emailed to your account on your schedule
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                aria-label="Close"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            {/* Body */}
            <div className="overflow-y-auto px-6 py-5">
              {!paid ? (
                <div className="rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-4 dark:border-zinc-800 dark:bg-zinc-900">
                  <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Email alerts require a paid plan</p>
                  <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                    Standard and above include scheduled email delivery with optional CSV attachments.
                  </p>
                  <div className="mt-3 flex gap-2">
                    {access?.authenticated ? (
                      <Link href="/account" className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500">
                        Upgrade plan
                      </Link>
                    ) : (
                      <Link href="/signup" className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500">
                        Create account
                      </Link>
                    )}
                  </div>
                </div>
              ) : !canSearch ? (
                <div className="rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-4 dark:border-zinc-800 dark:bg-zinc-900">
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    Set a location and vehicle to search first, then configure an alert.
                  </p>
                </div>
              ) : (
                <div className="space-y-5">
                  {/* Alert name */}
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                      Alert name
                    </label>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder={defaultName}
                      className={`mt-1.5 ${inputClass}`}
                    />
                  </div>

                  {/* Schedule */}
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">Schedule</p>
                    <div className="mt-1.5 grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs text-zinc-600 dark:text-zinc-400 mb-1">Frequency</label>
                        <select
                          value={cadence}
                          onChange={(e) => setCadence(e.target.value as "daily" | "weekly")}
                          className={inputClass}
                        >
                          <option value="daily">Daily</option>
                          <option value="weekly">Weekly</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs text-zinc-600 dark:text-zinc-400 mb-1">Send time</label>
                        <select
                          value={hourLocal}
                          onChange={(e) => setHourLocal(e.target.value)}
                          className={inputClass}
                        >
                          {Array.from({ length: 24 }, (_, hour) => (
                            <option key={hour} value={String(hour)}>
                              {hour.toString().padStart(2, "0")}:00
                            </option>
                          ))}
                        </select>
                      </div>
                      {cadence === "weekly" ? (
                        <div className="col-span-2">
                          <label className="block text-xs text-zinc-600 dark:text-zinc-400 mb-1">Day of week</label>
                          <select
                            value={dayOfWeek}
                            onChange={(e) => setDayOfWeek(e.target.value)}
                            className={inputClass}
                          >
                            {WEEKDAY_OPTIONS.map((opt) => (
                              <option key={opt.value} value={String(opt.value)}>{opt.label}</option>
                            ))}
                          </select>
                        </div>
                      ) : null}
                    </div>
                    <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                      Timezone: {timezone}
                    </p>
                  </div>

                  {/* Delivery */}
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-3">Delivery</p>
                    <div className="space-y-3 rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-800">
                      <Toggle checked={deliverCsv} onChange={setDeliverCsv} label="Attach CSV to each email" />
                      <div className="border-t border-zinc-100 dark:border-zinc-800" />
                      <Toggle checked={onlySendOnChanges} onChange={setOnlySendOnChanges} label="Only send when inventory changes" />
                      <div className="border-t border-zinc-100 dark:border-zinc-800" />
                      <Toggle checked={includeNewListings} onChange={setIncludeNewListings} label="Notify on new listings" />
                      <div className="border-t border-zinc-100 dark:border-zinc-800" />
                      <Toggle checked={includePriceDrops} onChange={setIncludePriceDrops} label="Notify on price drops" />
                      {includePriceDrops ? (
                        <div className="pt-1">
                          <label className="block text-xs text-zinc-600 dark:text-zinc-400 mb-1">Min price drop (USD, optional)</label>
                          <input
                            type="number"
                            min="0"
                            step="100"
                            value={minPriceDropUsd}
                            onChange={(e) => setMinPriceDropUsd(e.target.value)}
                            placeholder="Any drop"
                            className={inputClass}
                          />
                        </div>
                      ) : null}
                    </div>
                  </div>

                  {/* Summary */}
                  <div className="rounded-xl bg-zinc-50 px-4 py-3 text-xs text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400 space-y-0.5">
                    <p><span className="font-medium text-zinc-700 dark:text-zinc-300">Search:</span> {criteria.location} · {criteria.make || "Any make"} · {criteria.model || "Any model"} · {radiusLabel}</p>
                    <p><span className="font-medium text-zinc-700 dark:text-zinc-300">Runs:</span> {cadence === "daily" ? "Daily" : "Weekly"} at {hourLocal.padStart(2, "0")}:00</p>
                  </div>
                </div>
              )}

              {error ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
            </div>

            {/* Footer */}
            {paid && canSearch ? (
              <div className="flex items-center justify-end gap-3 border-t border-zinc-200 px-6 py-4 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void submit()}
                  disabled={submitting}
                  className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
                >
                  {submitting ? "Saving…" : "Save alert"}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
