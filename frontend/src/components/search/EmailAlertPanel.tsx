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

type Props = {
  access: AccessSummary | null;
  criteria: AlertCriteria;
  canSearch: boolean;
  tierOverride?: string;
  title?: string;
  description?: string;
  dismissible?: boolean;
  compact?: boolean;
  onSaved?: () => void | Promise<void>;
};

function isPaidTier(tier: string | null | undefined): boolean {
  return ["standard", "premium", "max_pro", "enterprise", "custom"].includes((tier ?? "").toLowerCase());
}

export function EmailAlertPanel({
  access,
  criteria,
  canSearch,
  tierOverride,
  title = "Scheduled email alerts",
  description = "Save this search as a recurring alert and send results to your account email, with an optional CSV attachment.",
  dismissible = false,
  compact = false,
  onSaved,
}: Props) {
  const paid = isPaidTier(tierOverride ?? access?.tier);
  const [isOpen, setIsOpen] = useState(false);
  const [isDismissed, setIsDismissed] = useState(false);
  const [name, setName] = useState("");
  const [cadence, setCadence] = useState<"daily" | "weekly">("daily");
  const [dayOfWeek, setDayOfWeek] = useState("0");
  const [hourLocal, setHourLocal] = useState("8");
  const [deliverCsv, setDeliverCsv] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const timezone = useMemo(() => {
    if (typeof Intl === "undefined") return "UTC";
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  }, []);

  const defaultName = useMemo(() => {
    const parts = [criteria.vehicle_category, criteria.location, criteria.make, criteria.model].filter(Boolean);
    return parts.join(" · ") || "Scheduled alert";
  }, [criteria.location, criteria.make, criteria.model, criteria.vehicle_category]);
  const radiusLabel = useMemo(() => {
    if ((criteria.market_region ?? "us") === "eu") {
      return `${milesToKm(criteria.radius_miles)} km`;
    }
    return `${criteria.radius_miles} mi`;
  }, [criteria.market_region, criteria.radius_miles]);

  const openModal = () => {
    if (!paid || !canSearch) return;
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
          is_active: true,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Unable to save the email alert.");
        return;
      }
      setMessage("Email alert saved. It will run on schedule and send results to your account email.");
      setIsOpen(false);
      await onSaved?.();
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (dismissible && isDismissed) {
    return (
      <section className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{title} hidden</h2>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              Show this panel again when you want to save the current search as an email alert.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setIsDismissed(false)}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-semibold text-zinc-800 transition hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-100 dark:hover:bg-zinc-900"
          >
            Show email alerts
          </button>
        </div>
      </section>
    );
  }

  if (compact) {
    return (
      <>
        <div className="mt-3 flex flex-col gap-2">
          {paid ? (
            <button
              type="button"
              onClick={openModal}
              disabled={!canSearch}
              className="w-full rounded-lg border border-emerald-300 px-4 py-2 text-sm font-semibold text-emerald-800 transition hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-emerald-950/50"
            >
              Create email alert
            </button>
          ) : (
            <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/70 dark:text-zinc-400">
              <span>Email alerts are included with Standard and above. </span>
              {access?.authenticated ? (
                <Link href="/account" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
                  Upgrade your plan
                </Link>
              ) : (
                <Link href="/signup" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
                  Create an account to upgrade
                </Link>
              )}
            </div>
          )}
          {!canSearch ? (
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Pick a valid search first, then save it as a scheduled alert.
            </p>
          ) : null}
          {message ? <p className="text-sm text-emerald-700 dark:text-emerald-400">{message}</p> : null}
          {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
        </div>

        {isOpen ? (
          <div className="fixed inset-0 z-[100] flex items-center justify-center bg-zinc-900/60 p-4">
            <div className="w-full max-w-lg rounded-2xl border border-zinc-200 bg-white p-5 shadow-lg dark:border-zinc-800 dark:bg-zinc-950">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Create scheduled alert</h3>
                  <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                    Results will be emailed to your signed-in address on the schedule below.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                  aria-label="Close"
                >
                  <span className="text-2xl leading-none">×</span>
                </button>
              </div>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="sm:col-span-2 flex flex-col gap-1 text-sm">
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">Alert name</span>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">Cadence</span>
                  <select
                    value={cadence}
                    onChange={(e) => setCadence(e.target.value as "daily" | "weekly")}
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  >
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">Send hour</span>
                  <select
                    value={hourLocal}
                    onChange={(e) => setHourLocal(e.target.value)}
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  >
                    {Array.from({ length: 24 }, (_, hour) => (
                      <option key={hour} value={String(hour)}>
                        {hour.toString().padStart(2, "0")}:00
                      </option>
                    ))}
                  </select>
                </label>
                {cadence === "weekly" ? (
                  <label className="sm:col-span-2 flex flex-col gap-1 text-sm">
                    <span className="font-medium text-zinc-800 dark:text-zinc-200">Day of week</span>
                    <select
                      value={dayOfWeek}
                      onChange={(e) => setDayOfWeek(e.target.value)}
                      className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                    >
                      {WEEKDAY_OPTIONS.map((option) => (
                        <option key={option.value} value={String(option.value)}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <label className="sm:col-span-2 flex items-start gap-3 rounded-xl border border-zinc-200 px-3 py-3 text-sm dark:border-zinc-800">
                  <input
                    type="checkbox"
                    checked={deliverCsv}
                    onChange={(e) => setDeliverCsv(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span className="text-zinc-700 dark:text-zinc-300">
                    Attach a CSV export to each email when results are sent.
                  </span>
                </label>
              </div>

              <div className="mt-4 rounded-xl bg-zinc-50 px-4 py-3 text-sm text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
                <p>
                  Schedule: {cadence === "daily" ? "Daily" : "Weekly"} at {hourLocal.padStart(2, "0")}:00 in {timezone}
                </p>
                <p className="mt-1">
                  Search: {criteria.vehicle_category} · {criteria.location} · {criteria.make || "Any make"} · {criteria.model || "Any model"} · {radiusLabel}
                </p>
              </div>

              {error ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p> : null}

              <div className="mt-4 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-semibold text-zinc-800 dark:border-zinc-700 dark:text-zinc-100"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void submit()}
                  disabled={submitting}
                  className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {submitting ? "Saving..." : "Save alert"}
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{title}</h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">{description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {paid ? (
            <button
              type="button"
              onClick={openModal}
              disabled={!canSearch}
              className="rounded-lg border border-emerald-300 px-4 py-2 text-sm font-semibold text-emerald-800 transition hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-emerald-950/50"
            >
              Create email alert
            </button>
          ) : (
            <div className="text-sm text-zinc-600 dark:text-zinc-400">
              <span>Email alerts are included with Standard and above. </span>
              {access?.authenticated ? (
                <Link href="/account" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
                  Upgrade your plan
                </Link>
              ) : (
                <Link href="/signup" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
                  Create an account to upgrade
                </Link>
              )}
            </div>
          )}
          {dismissible ? (
            <button
              type="button"
              onClick={() => setIsDismissed(true)}
              className="rounded-lg p-2 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
              aria-label={`Hide ${title.toLowerCase()}`}
            >
              <span className="text-xl leading-none">×</span>
            </button>
          ) : null}
        </div>
      </div>
      {!paid ? (
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
          Free searches stay manual. Paid plans unlock recurring runs, scheduled emails, and CSV delivery.
        </p>
      ) : null}
      {!canSearch ? (
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
          Pick a valid search first, then save it as a scheduled alert.
        </p>
      ) : null}
      {message ? <p className="mt-3 text-sm text-emerald-700 dark:text-emerald-400">{message}</p> : null}
      {error ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p> : null}

      {isOpen ? (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-zinc-900/60 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-zinc-200 bg-white p-5 shadow-lg dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Create scheduled alert</h3>
                <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                  Results will be emailed to your signed-in address on the schedule below.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                aria-label="Close"
              >
                <span className="text-2xl leading-none">×</span>
              </button>
            </div>

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="sm:col-span-2 flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Alert name</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Cadence</span>
                <select
                  value={cadence}
                  onChange={(e) => setCadence(e.target.value as "daily" | "weekly")}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Send hour</span>
                <select
                  value={hourLocal}
                  onChange={(e) => setHourLocal(e.target.value)}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  {Array.from({ length: 24 }, (_, hour) => (
                    <option key={hour} value={String(hour)}>
                      {hour.toString().padStart(2, "0")}:00
                    </option>
                  ))}
                </select>
              </label>
              {cadence === "weekly" ? (
                <label className="sm:col-span-2 flex flex-col gap-1 text-sm">
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">Day of week</span>
                  <select
                    value={dayOfWeek}
                    onChange={(e) => setDayOfWeek(e.target.value)}
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  >
                    {WEEKDAY_OPTIONS.map((option) => (
                      <option key={option.value} value={String(option.value)}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="sm:col-span-2 flex items-start gap-3 rounded-xl border border-zinc-200 px-3 py-3 text-sm dark:border-zinc-800">
                <input
                  type="checkbox"
                  checked={deliverCsv}
                  onChange={(e) => setDeliverCsv(e.target.checked)}
                  className="mt-0.5"
                />
                <span className="text-zinc-700 dark:text-zinc-300">
                  Attach a CSV export to each email when results are sent.
                </span>
              </label>
            </div>

            <div className="mt-4 rounded-xl bg-zinc-50 px-4 py-3 text-sm text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
              <p>
                Schedule: {cadence === "daily" ? "Daily" : "Weekly"} at {hourLocal.padStart(2, "0")}:00 in {timezone}
              </p>
              <p className="mt-1">
                Search: {criteria.location} · {criteria.make || "Any make"} · {criteria.model || "Any model"} · {radiusLabel}
              </p>
            </div>

            {error ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p> : null}

            <div className="mt-4 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-semibold text-zinc-800 dark:border-zinc-700 dark:text-zinc-100"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void submit()}
                disabled={submitting}
                className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? "Saving..." : "Save alert"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
