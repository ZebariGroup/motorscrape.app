"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { useAccessSummary } from "@/hooks/useAccessSummary";
import {
  type UserDetailResponse,
  fetchAdminJson,
  formatDateTime,
  formatRunLabel,
} from "@/lib/adminApi";

export default function AdminUserDetailPage() {
  const params = useParams<{ userId: string }>();
  const { access } = useAccessSummary();
  const [detail, setDetail] = useState<UserDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const loadDetail = useCallback(async () => {
    if (!params.userId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAdminJson<UserDetailResponse>(`/admin/users/${encodeURIComponent(params.userId)}`);
      setDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load user details.");
    } finally {
      setLoading(false);
    }
  }, [params.userId]);

  useEffect(() => {
    if (!access?.authenticated || !access.is_admin) return;
    void loadDetail();
  }, [access?.authenticated, access?.is_admin, loadDetail]);

  const entitlementsJson = useMemo(
    () => JSON.stringify(detail?.user ?? {}, null, 2),
    [detail],
  );

  const resetPassword = useCallback(async () => {
    if (!params.userId) return;
    setPasswordBusy(true);
    setPasswordMessage(null);
    try {
      await fetchAdminJson<{ ok: boolean }>(`/admin/users/${encodeURIComponent(params.userId)}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ new_password: newPassword }),
      });
      setPasswordMessage({ type: "success", text: "Password updated." });
      setNewPassword("");
      await loadDetail();
    } catch (err) {
      setPasswordMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to update password.",
      });
    } finally {
      setPasswordBusy(false);
    }
  }, [loadDetail, newPassword, params.userId]);

  return (
    <>
      <SiteHeader access={access} />
      <main className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm">
              <Link href="/admin" className="text-emerald-700 hover:underline dark:text-emerald-400">
                ← Back to admin console
              </Link>
            </p>
            <h1 className="mt-3 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">User Detail</h1>
          </div>
          <button
            type="button"
            onClick={() => void loadDetail()}
            disabled={loading}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>

        {error ? <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p> : null}

        {detail ? (
          <>
            <section className="mt-8 grid gap-4 md:grid-cols-4">
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950 md:col-span-2">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Profile</h2>
                <p className="mt-3 text-xl font-semibold text-zinc-900 dark:text-zinc-50">{detail.user.email}</p>
                <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
                  Tier {detail.user.tier} · admin {detail.user.is_admin ? "yes" : "no"}
                </p>
                <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                  Created {formatDateTime(detail.user.created_at)} · Updated {formatDateTime(detail.user.updated_at)}
                </p>
                <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                  Stripe customer {detail.user.stripe_customer_id ?? "none"} · metered item {detail.user.has_metered_item ? "yes" : "no"}
                </p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Usage</h2>
                <p className="mt-3 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">
                  {detail.user.usage.included_used}
                </p>
                <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
                  of {detail.user.usage.included_limit} included this month
                </p>
                <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                  Overage {detail.user.usage.overage_used}
                </p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Alerts</h2>
                <p className="mt-3 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{detail.alert_subscriptions.length}</p>
                <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
                  {detail.alert_subscriptions.filter((subscription) => subscription.is_active).length} active subscriptions
                </p>
              </div>
            </section>

            <section className="mt-8 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Reset Password</h2>
              <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">
                Set a new password directly for this user. This takes effect immediately.
              </p>
              <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
                <label className="flex-1">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    New password
                  </span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    minLength={8}
                    maxLength={128}
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none transition focus:border-emerald-500 focus:ring-2 focus:ring-emerald-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:focus:border-emerald-500 dark:focus:ring-emerald-900"
                    placeholder="Enter a new password"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void resetPassword()}
                  disabled={passwordBusy || newPassword.trim().length < 8}
                  className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
                >
                  {passwordBusy ? "Updating..." : "Update password"}
                </button>
              </div>
              {passwordMessage ? (
                <p
                  className={`mt-3 text-sm ${
                    passwordMessage.type === "error"
                      ? "text-red-600 dark:text-red-400"
                      : "text-emerald-600 dark:text-emerald-400"
                  }`}
                >
                  {passwordMessage.text}
                </p>
              ) : null}
            </section>

            <section className="mt-8 grid gap-6 xl:grid-cols-2">
              <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Recent Search Runs</h2>
                <div className="mt-4 space-y-3">
                  {detail.search_runs.map((run) => (
                    <div key={run.id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                      <p className="font-medium text-zinc-900 dark:text-zinc-50">{formatRunLabel(run)}</p>
                      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                        {run.status} · {formatDateTime(run.started_at)}
                      </p>
                      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                        results {run.result_count} · errors {run.error_count}
                      </p>
                    </div>
                  ))}
                  {detail.search_runs.length === 0 ? (
                    <p className="text-sm text-zinc-600 dark:text-zinc-400">No search runs recorded yet.</p>
                  ) : null}
                </div>
              </section>

              <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Alert Subscriptions</h2>
                <div className="mt-4 space-y-3">
                  {detail.alert_subscriptions.map((subscription) => (
                    <div key={subscription.id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                      <p className="font-medium text-zinc-900 dark:text-zinc-50">{subscription.name}</p>
                      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                        {subscription.is_active ? "active" : "paused"} · {subscription.cadence} · next {formatDateTime(subscription.next_run_at)}
                      </p>
                    </div>
                  ))}
                  {detail.alert_subscriptions.length === 0 ? (
                    <p className="text-sm text-zinc-600 dark:text-zinc-400">No alert subscriptions for this user.</p>
                  ) : null}
                </div>
              </section>
            </section>

            <section className="mt-8 grid gap-6 xl:grid-cols-2">
              <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Recent Alert Runs</h2>
                <div className="mt-4 space-y-3">
                  {detail.alert_runs.map((run) => (
                    <div key={run.id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                      <p className="font-medium text-zinc-900 dark:text-zinc-50">Subscription {run.subscription_id}</p>
                      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                        {run.status} · {formatDateTime(run.started_at)}
                      </p>
                      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                        results {run.result_count} · emailed {run.emailed ? "yes" : "no"}
                      </p>
                    </div>
                  ))}
                  {detail.alert_runs.length === 0 ? (
                    <p className="text-sm text-zinc-600 dark:text-zinc-400">No alert runs for this user yet.</p>
                  ) : null}
                </div>
              </section>

              <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Admin Audit</h2>
                <div className="mt-4 space-y-3">
                  {detail.audit_logs.map((log) => (
                    <div key={log.id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                      <p className="font-medium text-zinc-900 dark:text-zinc-50">{log.summary}</p>
                      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                        {log.actor_email ?? "unknown"} · {formatDateTime(log.created_at)}
                      </p>
                    </div>
                  ))}
                  {detail.audit_logs.length === 0 ? (
                    <p className="text-sm text-zinc-600 dark:text-zinc-400">No admin audit entries for this user yet.</p>
                  ) : null}
                </div>
              </section>
            </section>

            <section className="mt-8 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Raw User Payload</h2>
              <pre className="mt-4 overflow-x-auto rounded-xl bg-zinc-950 p-3 text-xs text-zinc-100">{entitlementsJson}</pre>
            </section>
          </>
        ) : (
          <p className="mt-6 text-sm text-zinc-600 dark:text-zinc-400">Loading user detail...</p>
        )}
      </main>
    </>
  );
}
