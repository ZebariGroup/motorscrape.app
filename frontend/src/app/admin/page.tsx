"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { useAccessSummary } from "@/hooks/useAccessSummary";
import {
  type AdminUser,
  type AdminAlertRun,
  type AdminAlertSubscription,
  type AdminAuditLog,
  type DealerOutcome,
  type OverviewResponse,
  type RunDetailResponse,
  type RunsResponse,
  type UsersResponse,
  fetchAdminJson,
  formatDateTime,
  formatRunLabel,
} from "@/lib/adminApi";

type UserDraft = {
  tier: string;
  is_admin: boolean;
};

const TIERS = ["free", "standard", "premium", "max_pro", "enterprise", "custom"] as const;
const USERS_PAGE_SIZE = 12;
const RUNS_PAGE_SIZE = 10;

function formatOutcomeLabel(outcome: DealerOutcome): string {
  if (outcome.zero_results_warning === "ford_family_scoped_url_empty") return "Ford scoped URL empty";
  if (outcome.classification === "fetch_failure") return "Fetch failure";
  if (outcome.classification === "parse_failure") return "Parse failure";
  if (outcome.classification === "timeout") return "Timeout";
  if (outcome.classification === "zero_results") return "Zero listings";
  if (outcome.classification === "success") return "Success";
  return outcome.classification.replaceAll("_", " ");
}

function outcomeToneClasses(status: string): string {
  if (status === "success") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  if (status === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300";
  }
  if (status === "failed") {
    return "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300";
  }
  return "border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300";
}

export default function AdminPage() {
  const { access, loading: accessLoading, refresh: refreshAccess } = useAccessSummary();
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [users, setUsers] = useState<UsersResponse["users"]>([]);
  const [runs, setRuns] = useState<RunsResponse["runs"]>([]);
  const [alertHealth, setAlertHealth] = useState<{
    due_subscriptions: AdminAlertSubscription[];
    recent_alert_runs: AdminAlertRun[];
  } | null>(null);
  const [auditLogs, setAuditLogs] = useState<AdminAuditLog[]>([]);
  const [selectedRun, setSelectedRun] = useState<RunDetailResponse | null>(null);
  const [userQuery, setUserQuery] = useState("");
  const [runStatus, setRunStatus] = useState("all");
  const [usersOffset, setUsersOffset] = useState(0);
  const [runsOffset, setRunsOffset] = useState(0);
  const [usersTotal, setUsersTotal] = useState(0);
  const [runsTotal, setRunsTotal] = useState(0);
  const [userDrafts, setUserDrafts] = useState<Record<string, UserDraft>>({});
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [savingUserId, setSavingUserId] = useState<string | null>(null);
  const [closingRunId, setClosingRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const syncUserDrafts = useCallback((incomingUsers: AdminUser[]) => {
    setUserDrafts((current) => {
      const next: Record<string, UserDraft> = {};
      for (const user of incomingUsers) {
        next[user.id] = current[user.id] ?? { tier: user.tier, is_admin: user.is_admin };
      }
      return next;
    });
  }, []);

  const loadOverview = useCallback(async () => {
    const data = await fetchAdminJson<OverviewResponse>("/admin/overview");
    setOverview(data);
  }, []);

  const loadAlertHealth = useCallback(async () => {
    const data = await fetchAdminJson<{
      due_subscriptions: AdminAlertSubscription[];
      recent_alert_runs: AdminAlertRun[];
    }>("/admin/alerts/health?limit=8");
    setAlertHealth(data);
  }, []);

  const loadAuditLogs = useCallback(async () => {
    const data = await fetchAdminJson<{ logs: AdminAuditLog[] }>("/admin/audit-log?limit=8");
    setAuditLogs(data.logs);
  }, []);

  const loadUsers = useCallback(
    async (query: string, offset: number) => {
      const search = query.trim();
      const params = new URLSearchParams({
        limit: String(USERS_PAGE_SIZE),
        offset: String(offset),
      });
      if (search) params.set("query", search);
      const data = await fetchAdminJson<UsersResponse>(`/admin/users?${params.toString()}`);
      setUsers(data.users);
      setUsersTotal(data.total);
      syncUserDrafts(data.users);
    },
    [syncUserDrafts],
  );

  const loadRuns = useCallback(async (status: string, offset: number) => {
    const params = new URLSearchParams({
      limit: String(RUNS_PAGE_SIZE),
      offset: String(offset),
    });
    if (status !== "all") params.set("status", status);
    const data = await fetchAdminJson<RunsResponse>(`/admin/search-runs?${params.toString()}`);
    setRuns(data.runs);
    setRunsTotal(data.total);
  }, []);

  const loadRunDetail = useCallback(async (correlationId: string) => {
    setDetailLoading(true);
    setError(null);
    try {
      const data = await fetchAdminJson<RunDetailResponse>(`/admin/search-runs/${encodeURIComponent(correlationId)}`);
      setSelectedRun(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run details.");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeStuckRun = useCallback(
    async (correlationId: string) => {
      setClosingRunId(correlationId);
      setError(null);
      try {
        await fetchAdminJson<{ run: RunsResponse["runs"][number] }>(
          `/admin/search-runs/${encodeURIComponent(correlationId)}/close-stuck`,
          { method: "POST" },
        );
        await Promise.all([loadOverview(), loadAuditLogs(), loadRuns(runStatus, runsOffset)]);
        if (selectedRun?.run.correlation_id === correlationId) {
          await loadRunDetail(correlationId);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to close stuck run.");
      } finally {
        setClosingRunId(null);
      }
    },
    [loadAuditLogs, loadOverview, loadRunDetail, loadRuns, runStatus, runsOffset, selectedRun?.run.correlation_id],
  );

  const reloadDashboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([
        refreshAccess(),
        loadOverview(),
        loadAlertHealth(),
        loadAuditLogs(),
        loadUsers(userQuery, usersOffset),
        loadRuns(runStatus, runsOffset),
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load administrator console.");
    } finally {
      setLoading(false);
    }
  }, [loadAlertHealth, loadAuditLogs, loadOverview, loadRuns, loadUsers, refreshAccess, runStatus, runsOffset, userQuery, usersOffset]);

  useEffect(() => {
    if (!access?.authenticated || !access.is_admin) return;
    void reloadDashboard();
  }, [access?.authenticated, access?.is_admin, reloadDashboard]);

  const selectedRunPrettySummary = useMemo(
    () => (selectedRun ? JSON.stringify(selectedRun.run.summary, null, 2) : ""),
    [selectedRun],
  );
  const selectedRunPrettyEconomics = useMemo(
    () => (selectedRun ? JSON.stringify(selectedRun.run.economics, null, 2) : ""),
    [selectedRun],
  );

  const updateDraft = (userId: string, patch: Partial<UserDraft>) => {
    setUserDrafts((current) => ({
      ...current,
      [userId]: {
        tier: current[userId]?.tier ?? users.find((user) => user.id === userId)?.tier ?? "free",
        is_admin: current[userId]?.is_admin ?? users.find((user) => user.id === userId)?.is_admin ?? false,
        ...patch,
      },
    }));
  };

  const saveUser = async (user: AdminUser) => {
    const draft = userDrafts[user.id] ?? { tier: user.tier, is_admin: user.is_admin };
    setSavingUserId(user.id);
    setError(null);
    try {
      await fetchAdminJson<{ user: UsersResponse["users"][number] }>(`/admin/users/${encodeURIComponent(user.id)}`, {
        method: "PATCH",
        body: JSON.stringify(draft),
      });
      await Promise.all([refreshAccess(), loadOverview(), loadAuditLogs(), loadUsers(userQuery, usersOffset)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update user.");
    } finally {
      setSavingUserId(null);
    }
  };

  const usersPageStart = usersTotal === 0 ? 0 : usersOffset + 1;
  const usersPageEnd = Math.min(usersOffset + users.length, usersTotal);
  const runsPageStart = runsTotal === 0 ? 0 : runsOffset + 1;
  const runsPageEnd = Math.min(runsOffset + runs.length, runsTotal);

  if (accessLoading && access === null) {
    return (
      <>
        <SiteHeader access={access} />
        <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Loading administrator console...</p>
        </main>
      </>
    );
  }

  if (!access?.authenticated) {
    return (
      <>
        <SiteHeader access={access} />
        <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Administrator Console</h1>
          <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
            <Link href="/login" className="font-medium text-emerald-700 dark:text-emerald-400">
              Log in
            </Link>{" "}
            with an administrator account to access this console.
          </p>
        </main>
      </>
    );
  }

  if (!access.is_admin) {
    return (
      <>
        <SiteHeader access={access} />
        <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Administrator Console</h1>
          <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
            Your account is signed in, but it does not currently have administrator access.
          </p>
          <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">
            Configure `ADMIN_EMAILS` to bootstrap an administrator, or promote a user through the database.
          </p>
        </main>
      </>
    );
  }

  return (
    <>
      <SiteHeader access={access} />
      <main className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Administrator Console</h1>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              Manage users, monitor search activity, and inspect recent system health signals.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void reloadDashboard()}
            disabled={loading}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>

        {error ? <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p> : null}

        {overview ? (
          <>
            <section className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Users</p>
                <p className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{overview.stats.total_users}</p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Searches This Month</p>
                <p className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{overview.stats.searches_this_month}</p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Recent Signups</p>
                <p className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{overview.stats.recent_signups_last_7d}</p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Failed Runs (7d)</p>
                <p className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{overview.stats.failed_runs_last_7d}</p>
              </div>
            </section>

            <section className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Overage Searches</p>
                <p className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{overview.stats.overage_searches_this_month}</p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Active Alerts</p>
                <p className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{overview.stats.active_alerts}</p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Alerts Due Now</p>
                <p className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{overview.stats.alerts_due_now}</p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Failed Alert Runs (7d)</p>
                <p className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{overview.stats.failed_alert_runs_last_7d}</p>
              </div>
            </section>

            <section className="mt-4 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Users By Tier</h2>
              <div className="mt-3 flex flex-wrap gap-3">
                {Object.entries(overview.stats.users_by_tier).map(([tier, count]) => (
                  <span
                    key={tier}
                    className="rounded-full border border-zinc-200 px-3 py-1 text-sm text-zinc-700 dark:border-zinc-700 dark:text-zinc-300"
                  >
                    {tier}: {count}
                  </span>
                ))}
              </div>
            </section>
          </>
        ) : null}

        <section className="mt-8 grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Users</h2>
              <form
                className="flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  setUsersOffset(0);
                  void loadUsers(userQuery, 0);
                }}
              >
                <input
                  value={userQuery}
                  onChange={(event) => setUserQuery(event.target.value)}
                  placeholder="Search by email"
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                />
                <button
                  type="submit"
                  className="rounded-lg border border-zinc-300 px-3 py-2 text-sm font-medium text-zinc-900 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900"
                >
                  Search
                </button>
              </form>
            </div>
            <div className="mt-3 flex items-center justify-between gap-3 text-sm text-zinc-600 dark:text-zinc-400">
              <span>
                Showing {usersPageStart}-{usersPageEnd} of {usersTotal}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    const nextOffset = Math.max(0, usersOffset - USERS_PAGE_SIZE);
                    setUsersOffset(nextOffset);
                    void loadUsers(userQuery, nextOffset);
                  }}
                  disabled={usersOffset === 0}
                  className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-900 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900"
                >
                  Previous
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const nextOffset = usersOffset + USERS_PAGE_SIZE;
                    setUsersOffset(nextOffset);
                    void loadUsers(userQuery, nextOffset);
                  }}
                  disabled={usersOffset + USERS_PAGE_SIZE >= usersTotal}
                  className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-900 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900"
                >
                  Next
                </button>
              </div>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-zinc-500 dark:text-zinc-400">
                  <tr>
                    <th className="pb-3 pr-4 font-medium">User</th>
                    <th className="pb-3 pr-4 font-medium">Tier</th>
                    <th className="pb-3 pr-4 font-medium">Admin</th>
                    <th className="pb-3 pr-4 font-medium">Usage</th>
                    <th className="pb-3 pr-4 font-medium">Created</th>
                    <th className="pb-3 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => {
                    const draft = userDrafts[user.id] ?? { tier: user.tier, is_admin: user.is_admin };
                    return (
                      <tr key={user.id} className="border-t border-zinc-200 align-top dark:border-zinc-800">
                        <td className="py-3 pr-4">
                          <Link href={`/admin/users/${user.id}`} className="font-medium text-zinc-900 hover:underline dark:text-zinc-50">
                            {user.email}
                          </Link>
                          <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">id {user.id}</div>
                          {user.stripe_customer_id ? (
                            <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">Stripe linked</div>
                          ) : null}
                        </td>
                        <td className="py-3 pr-4">
                          <select
                            value={draft.tier}
                            onChange={(event) => updateDraft(user.id, { tier: event.target.value })}
                            className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                          >
                            {TIERS.map((tier) => (
                              <option key={tier} value={tier}>
                                {tier}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="py-3 pr-4">
                          <label className="inline-flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
                            <input
                              type="checkbox"
                              checked={draft.is_admin}
                              onChange={(event) => updateDraft(user.id, { is_admin: event.target.checked })}
                            />
                            Admin
                          </label>
                        </td>
                        <td className="py-3 pr-4 text-zinc-600 dark:text-zinc-400">
                          {user.usage.included_used} / {user.usage.included_limit}
                          {user.usage.overage_used ? ` + ${user.usage.overage_used} overage` : ""}
                        </td>
                        <td className="py-3 pr-4 text-zinc-600 dark:text-zinc-400">{formatDateTime(user.created_at)}</td>
                        <td className="py-3">
                          <button
                            type="button"
                            onClick={() => void saveUser(user)}
                            disabled={savingUserId === user.id}
                            className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {savingUserId === user.id ? "Saving..." : "Save"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="space-y-6">
            <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Recent Users</h2>
              <div className="mt-4 space-y-3">
                {(overview?.recent_users ?? []).map((user) => (
                  <div key={user.id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                    <Link href={`/admin/users/${user.id}`} className="font-medium text-zinc-900 hover:underline dark:text-zinc-50">
                      {user.email}
                    </Link>
                    <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                      {user.tier} · {formatDateTime(user.created_at)}
                    </p>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Recent Search Runs</h2>
                <select
                  value={runStatus}
                  onChange={(event) => {
                    const nextStatus = event.target.value;
                    setRunStatus(nextStatus);
                    setRunsOffset(0);
                    void loadRuns(nextStatus, 0);
                  }}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  <option value="all">All</option>
                  <option value="running">Running</option>
                  <option value="success">Success</option>
                  <option value="partial_failure">Partial failure</option>
                  <option value="failed">Failed</option>
                  <option value="quota_blocked">Quota blocked</option>
                </select>
              </div>
              <div className="mt-3 flex items-center justify-between gap-3 text-sm text-zinc-600 dark:text-zinc-400">
                <span>
                  Showing {runsPageStart}-{runsPageEnd} of {runsTotal}
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      const nextOffset = Math.max(0, runsOffset - RUNS_PAGE_SIZE);
                      setRunsOffset(nextOffset);
                      void loadRuns(runStatus, nextOffset);
                    }}
                    disabled={runsOffset === 0}
                    className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-900 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900"
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const nextOffset = runsOffset + RUNS_PAGE_SIZE;
                      setRunsOffset(nextOffset);
                      void loadRuns(runStatus, nextOffset);
                    }}
                    disabled={runsOffset + RUNS_PAGE_SIZE >= runsTotal}
                    className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-900 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-50 dark:hover:bg-zinc-900"
                  >
                    Next
                  </button>
                </div>
              </div>
              <div className="mt-4 space-y-3">
                {runs.map((run) => (
                  <div
                    key={run.id}
                    className="flex w-full gap-2 rounded-xl border border-zinc-200 p-3 dark:border-zinc-800"
                  >
                    <button
                      type="button"
                      onClick={() => void loadRunDetail(run.correlation_id)}
                      className="min-w-0 flex-1 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-medium text-zinc-900 dark:text-zinc-50">{formatRunLabel(run)}</p>
                        <span className="text-xs uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{run.status}</span>
                      </div>
                      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                        {run.user_email ?? "anonymous"} · {formatDateTime(run.started_at)}
                      </p>
                      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                        results {run.result_count} · errors {run.error_count} · warnings {run.warning_count}
                      </p>
                    </button>
                    {run.status === "running" ? (
                      <button
                        type="button"
                        title="Mark this run as failed in the database if the stream died without finishing"
                        onClick={() => void closeStuckRun(run.correlation_id)}
                        disabled={closingRunId === run.correlation_id}
                        className="shrink-0 self-center rounded-lg border border-amber-300 bg-amber-50 px-2.5 py-2 text-xs font-semibold text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-200 dark:hover:bg-amber-900/50"
                      >
                        {closingRunId === run.correlation_id ? "…" : "Close"}
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>
          </div>
        </section>

        <section className="mt-8 grid gap-6 xl:grid-cols-2">
          <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Alert Health</h2>
            <div className="mt-4 grid gap-6 xl:grid-cols-2">
              <div>
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Due Subscriptions</p>
                <div className="mt-3 space-y-3">
                  {(alertHealth?.due_subscriptions ?? []).map((subscription) => (
                    <div key={subscription.id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                      <p className="font-medium text-zinc-900 dark:text-zinc-50">{subscription.name}</p>
                      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                        {subscription.user_email ?? subscription.user_id} · due {formatDateTime(subscription.next_run_at)}
                      </p>
                    </div>
                  ))}
                  {(alertHealth?.due_subscriptions.length ?? 0) === 0 ? (
                    <p className="text-sm text-zinc-600 dark:text-zinc-400">No alerts are currently due.</p>
                  ) : null}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Recent Alert Runs</p>
                <div className="mt-3 space-y-3">
                  {(alertHealth?.recent_alert_runs ?? []).map((run) => (
                    <div key={run.id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                      <p className="font-medium text-zinc-900 dark:text-zinc-50">{run.user_email ?? run.user_id}</p>
                      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                        {run.status} · {formatDateTime(run.started_at)}
                      </p>
                      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                        results {run.result_count} · emailed {run.emailed ? "yes" : "no"}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Recent Admin Actions</h2>
            <div className="mt-4 space-y-3">
              {auditLogs.map((log) => (
                <div key={log.id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                  <p className="font-medium text-zinc-900 dark:text-zinc-50">{log.summary}</p>
                  <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                    {log.actor_email ?? "unknown"} · {formatDateTime(log.created_at)}
                  </p>
                  <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                    {log.action} · {log.target_type} {log.target_id ?? "n/a"}
                  </p>
                </div>
              ))}
              {auditLogs.length === 0 ? (
                <p className="text-sm text-zinc-600 dark:text-zinc-400">No admin changes recorded yet.</p>
              ) : null}
            </div>
          </section>
        </section>

        <section className="mt-8 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Run Details</h2>
            <div className="flex items-center gap-2">
              {selectedRun?.run.status === "running" ? (
                <button
                  type="button"
                  title="Mark this run as failed in the database if the stream died without finishing"
                  onClick={() => void closeStuckRun(selectedRun.run.correlation_id)}
                  disabled={closingRunId === selectedRun.run.correlation_id}
                  className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-200 dark:hover:bg-amber-900/50"
                >
                  {closingRunId === selectedRun.run.correlation_id ? "Closing…" : "Close stuck run"}
                </button>
              ) : null}
              {detailLoading ? <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading...</p> : null}
            </div>
          </div>

          {!selectedRun ? (
            <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">Choose a recent search run to inspect its events and summary.</p>
          ) : (
            <div className="mt-4 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
              <div className="space-y-4">
                <div>
                  <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{formatRunLabel(selectedRun.run)}</p>
                  <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                    {selectedRun.run.user_email ?? "anonymous"} · {selectedRun.run.correlation_id}
                  </p>
                </div>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-zinc-500 dark:text-zinc-400">Status</dt>
                    <dd className="text-zinc-900 dark:text-zinc-50">{selectedRun.run.status}</dd>
                  </div>
                  <div>
                    <dt className="text-zinc-500 dark:text-zinc-400">Started</dt>
                    <dd className="text-zinc-900 dark:text-zinc-50">{formatDateTime(selectedRun.run.started_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-zinc-500 dark:text-zinc-400">Completed</dt>
                    <dd className="text-zinc-900 dark:text-zinc-50">{formatDateTime(selectedRun.run.completed_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-zinc-500 dark:text-zinc-400">Results</dt>
                    <dd className="text-zinc-900 dark:text-zinc-50">{selectedRun.run.result_count}</dd>
                  </div>
                </dl>
                <div>
                  <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Summary</p>
                  <pre className="mt-2 overflow-x-auto rounded-xl bg-zinc-950 p-3 text-xs text-zinc-100">
                    {selectedRunPrettySummary}
                  </pre>
                </div>
                <div>
                  <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Economics</p>
                  <pre className="mt-2 overflow-x-auto rounded-xl bg-zinc-950 p-3 text-xs text-zinc-100">
                    {selectedRunPrettyEconomics}
                  </pre>
                </div>
                <div>
                  <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Dealer Outcome Matrix</p>
                  <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                    dealers {selectedRun.dealer_summary.total_dealers} · ford family {selectedRun.dealer_summary.ford_family_dealers} · zero-result warnings{" "}
                    {selectedRun.dealer_summary.zero_results_warnings}
                  </p>
                  {selectedRun.dealer_summary.error_code_counts && Object.keys(selectedRun.dealer_summary.error_code_counts).length > 0 ? (
                    <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                      failure codes{" "}
                      {Object.entries(selectedRun.dealer_summary.error_code_counts)
                        .map(([code, count]) => `${code} (${count})`)
                        .join(" · ")}
                    </p>
                  ) : null}
                  <div className="mt-3 space-y-3">
                    {selectedRun.dealer_outcomes.map((outcome) => (
                      <div key={`${outcome.dealership_website ?? outcome.dealership_name ?? "dealer"}-${outcome.final_url ?? outcome.classification}`} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                              {outcome.dealership_name ?? outcome.dealership_website ?? "Unknown dealer"}
                            </p>
                            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                              {outcome.dealership_website ?? "n/a"}
                            </p>
                          </div>
                          <span className={`rounded-full border px-2 py-1 text-xs font-medium capitalize ${outcomeToneClasses(outcome.status)}`}>
                            {formatOutcomeLabel(outcome)}
                          </span>
                        </div>
                        <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">
                          listings {outcome.listings_found} · platform {outcome.platform_id ?? "n/a"} · source {outcome.platform_source ?? "n/a"}
                        </p>
                        <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
                          strategy {outcome.strategy_used ?? "n/a"} · fetch {outcome.fetch_methods.join(", ") || "n/a"}
                        </p>
                        {outcome.final_url ? (
                          <p className="mt-1 break-all text-xs text-zinc-600 dark:text-zinc-400">{outcome.final_url}</p>
                        ) : null}
                        {outcome.ford_recovery_urls.length > 0 ? (
                          <p className="mt-1 break-all text-xs text-zinc-600 dark:text-zinc-400">
                            recovery {outcome.ford_recovery_urls.join(" | ")}
                          </p>
                        ) : null}
                        {outcome.error_message ? (
                          <p className="mt-2 text-xs text-red-600 dark:text-red-400">
                            {outcome.error_phase ?? "scrape"}{outcome.error_code ? ` · ${outcome.error_code}` : ""}: {outcome.error_message}
                          </p>
                        ) : null}
                      </div>
                    ))}
                    {selectedRun.dealer_outcomes.length === 0 ? (
                      <p className="text-sm text-zinc-600 dark:text-zinc-400">No dealer outcome rows were derived from this run yet.</p>
                    ) : null}
                  </div>
                </div>
              </div>

              <div>
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Events</p>
                <div className="mt-3 max-h-[42rem] space-y-3 overflow-y-auto pr-1">
                  {selectedRun.events.map((event) => (
                    <div key={event.id} className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                          {event.sequence_no}. {event.event_type}
                        </p>
                        <span className="text-xs uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                          {event.level}
                        </span>
                      </div>
                      <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">{event.message}</p>
                      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                        {event.phase ?? "n/a"} · {formatDateTime(event.created_at)}
                      </p>
                      {event.dealership_name || event.dealership_website ? (
                        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                          {event.dealership_name ?? "Unknown dealer"} · {event.dealership_website ?? "n/a"}
                        </p>
                      ) : null}
                      {Object.keys(event.payload).length > 0 ? (
                        <pre className="mt-2 overflow-x-auto rounded-lg bg-zinc-950 p-3 text-xs text-zinc-100">
                          {JSON.stringify(event.payload, null, 2)}
                        </pre>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </section>
      </main>
    </>
  );
}
