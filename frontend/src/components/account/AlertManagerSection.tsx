"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { resolveApiUrl } from "@/lib/apiBase";
import type { AlertDashboardResponse, AlertRun, AlertSubscription } from "@/types/alerts";

type Props = {
  authenticated: boolean;
  tier: string;
};

function isPaidTier(tier: string): boolean {
  return ["standard", "premium", "enterprise", "custom"].includes((tier || "").toLowerCase());
}

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}

function criteriaLabel(criteria: AlertSubscription["criteria"]): string {
  const parts = [criteria.location, criteria.make, criteria.model].filter(Boolean);
  return parts.join(" · ");
}

export function AlertManagerSection({ authenticated, tier }: Props) {
  const paid = useMemo(() => isPaidTier(tier), [tier]);
  const [data, setData] = useState<AlertDashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

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
            Create alerts from the search page, then manage or run them here.
          </p>
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
                      <p className="text-sm text-zinc-600 dark:text-zinc-400">
                        {criteriaLabel(subscription.criteria)}
                      </p>
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
