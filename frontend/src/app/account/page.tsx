"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { useAccessSummary } from "@/hooks/useAccessSummary";
import { resolveApiUrl } from "@/lib/apiBase";

type MeResponse = {
  id: string;
  email: string;
  tier: string;
  usage: { period: string; included_used: number; overage_used: number; included_limit: number };
  limits: AccessSummary["limits"];
  stripe_customer_id: string | null;
  stripe_metered_item_id: boolean;
};

export default function AccountPage() {
  const router = useRouter();
  const { access } = useAccessSummary();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [isManagingBilling, setIsManagingBilling] = useState(false);
  const [isUpdatingPassword, setIsUpdatingPassword] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [passwordMessage, setPasswordMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const loadMe = useCallback(() => {
    fetch(resolveApiUrl("/auth/me"), { credentials: "include" })
      .then((r) => {
        if (r.status === 401) {
          setMe(null);
          return null;
        }
        return r.json();
      })
      .then((j) => {
        if (j) setMe(j as MeResponse);
      })
      .catch(() => setMe(null));
  }, []);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  const logout = async () => {
    await fetch(resolveApiUrl("/auth/logout"), { method: "POST", credentials: "include" });
    setMe(null);
    router.refresh();
  };

  const checkout = async (tier: "standard" | "premium") => {
    setBillingError(null);
    setIsManagingBilling(true);
    try {
      const r = await fetch(resolveApiUrl("/billing/checkout"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setBillingError(typeof j.detail === "string" ? j.detail : "Checkout unavailable.");
        setIsManagingBilling(false);
        return;
      }
      const { url } = await r.json();
      if (url) window.location.href = url as string;
    } catch {
      setBillingError("Network error. Please try again.");
      setIsManagingBilling(false);
    }
  };

  const manageBilling = async () => {
    setBillingError(null);
    setIsManagingBilling(true);
    try {
      const r = await fetch(resolveApiUrl("/billing/portal"), {
        method: "POST",
        credentials: "include",
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setBillingError(typeof j.detail === "string" ? j.detail : "Billing portal unavailable.");
        setIsManagingBilling(false);
        return;
      }
      const { url } = await r.json();
      if (url) window.location.href = url as string;
    } catch {
      setBillingError("Network error. Please try again.");
      setIsManagingBilling(false);
    }
  };

  const updatePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword.length < 8) return;
    setIsUpdatingPassword(true);
    setPasswordMessage(null);
    try {
      const r = await fetch(resolveApiUrl("/auth/update-password"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: newPassword }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setPasswordMessage({ type: "error", text: typeof j.detail === "string" ? j.detail : "Failed to update password." });
      } else {
        setPasswordMessage({ type: "success", text: "Password updated successfully." });
        setNewPassword("");
      }
    } catch {
      setPasswordMessage({ type: "error", text: "Network error. Please try again." });
    } finally {
      setIsUpdatingPassword(false);
    }
  };

  return (
    <>
      <SiteHeader access={access} />
      <main className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Account</h1>

        {!me ? (
          <p className="mt-6 text-sm text-zinc-600 dark:text-zinc-400">
            <Link href="/login" className="font-medium text-emerald-700 dark:text-emerald-400">
              Log in
            </Link>{" "}
            to view usage and manage your plan.
          </p>
        ) : (
          <div className="mt-8 space-y-8">
            <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Profile
              </h2>
              <p className="mt-2 text-zinc-900 dark:text-zinc-50">{me.email}</p>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                Plan: <span className="font-medium text-zinc-800 dark:text-zinc-200">{me.tier}</span>
              </p>
              <button
                type="button"
                onClick={() => void logout()}
                className="mt-4 text-sm font-medium text-zinc-600 underline hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200"
              >
                Log out
              </button>
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Usage ({me.usage.period})
              </h2>
              <p className="mt-2 text-sm text-zinc-700 dark:text-zinc-300">
                Included searches: {me.usage.included_used} / {me.usage.included_limit}
              </p>
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Billing & Plan
              </h2>
              <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
                {me.stripe_customer_id
                  ? "Manage your active subscription, payment methods, and billing history."
                  : "Subscribe via Stripe Checkout to unlock higher limits and premium features. Enterprise and custom licensing are contracted separately."}
              </p>
              
              {!me.stripe_customer_id && (
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
                    <h3 className="font-medium text-zinc-900 dark:text-zinc-50">Standard</h3>
                    <ul className="mt-2 space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                      <li>• 350 included searches / month</li>
                      <li>• Up to 30 mile radius</li>
                      <li>• Search up to 10 dealerships at once</li>
                    </ul>
                  </div>
                  <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
                    <h3 className="font-medium text-zinc-900 dark:text-zinc-50">Premium</h3>
                    <ul className="mt-2 space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                      <li>• 750 included searches / month</li>
                      <li>• Nationwide search radius</li>
                      <li>• Search up to 20 dealerships at once</li>
                      <li>• Access to premium inventory scope</li>
                    </ul>
                  </div>
                </div>
              )}

              {billingError ? <p className="mt-4 text-sm text-red-600">{billingError}</p> : null}
              <div className="mt-4 flex flex-wrap gap-3">
                {me.stripe_customer_id ? (
                  <button
                    type="button"
                    onClick={() => void manageBilling()}
                    disabled={isManagingBilling}
                    className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isManagingBilling ? "Opening portal..." : "Manage Billing"}
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => void checkout("standard")}
                      disabled={isManagingBilling}
                      className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isManagingBilling ? "Loading..." : "Upgrade to Standard"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void checkout("premium")}
                      disabled={isManagingBilling}
                      className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-semibold text-zinc-900 hover:bg-zinc-50 dark:border-zinc-600 dark:text-zinc-50 dark:hover:bg-zinc-900 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isManagingBilling ? "Loading..." : "Upgrade to Premium"}
                    </button>
                  </>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Security
              </h2>
              <form onSubmit={updatePassword} className="mt-4 flex max-w-sm flex-col gap-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">New Password</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  />
                </label>
                {passwordMessage ? (
                  <p className={`text-sm ${passwordMessage.type === "error" ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
                    {passwordMessage.text}
                  </p>
                ) : null}
                <div>
                  <button
                    type="submit"
                    disabled={isUpdatingPassword || newPassword.length < 8}
                    className="rounded-lg bg-zinc-800 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-not-allowed dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-zinc-300"
                  >
                    {isUpdatingPassword ? "Updating..." : "Update Password"}
                  </button>
                </div>
              </form>
            </section>
          </div>
        )}

        <p className="mt-10 text-sm">
          <Link href="/" className="text-emerald-700 hover:underline dark:text-emerald-400">
            ← Back to search
          </Link>
        </p>
      </main>
    </>
  );
}
