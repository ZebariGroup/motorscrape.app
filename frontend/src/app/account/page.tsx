"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { resolveApiUrl } from "@/lib/apiBase";
import type { AccessSummary } from "@/types/access";

type MeResponse = {
  id: number;
  email: string;
  tier: string;
  usage: { period: string; included_used: number; overage_used: number; included_limit: number };
  limits: AccessSummary["limits"];
  stripe_metered_item_id: boolean;
};

export default function AccountPage() {
  const router = useRouter();
  const [access, setAccess] = useState<AccessSummary | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);

  const loadAccess = useCallback(() => {
    fetch(resolveApiUrl("/auth/access-summary"), { credentials: "include" })
      .then((r) => r.json())
      .then(setAccess)
      .catch(() => setAccess(null));
  }, []);

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
    loadAccess();
    loadMe();
  }, [loadAccess, loadMe]);

  const logout = async () => {
    await fetch(resolveApiUrl("/auth/logout"), { method: "POST", credentials: "include" });
    setMe(null);
    loadAccess();
    router.refresh();
  };

  const checkout = async (tier: "standard" | "premium") => {
    setBillingError(null);
    const r = await fetch(resolveApiUrl("/billing/checkout"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tier }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      setBillingError(typeof j.detail === "string" ? j.detail : "Checkout unavailable.");
      return;
    }
    const { url } = await r.json();
    if (url) window.location.href = url as string;
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
              {me.usage.overage_used > 0 ? (
                <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">
                  Billed overage searches (this period): {me.usage.overage_used}
                </p>
              ) : null}
              <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                Metered billing with Stripe: {me.stripe_metered_item_id ? "on" : "not linked — complete checkout with a metered price"}
              </p>
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Upgrade
              </h2>
              <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
                Subscribe via Stripe Checkout (configure price IDs in the API environment). Enterprise and custom licensing
                are contracted separately — see docs in the repo.
              </p>
              {billingError ? <p className="mt-2 text-sm text-red-600">{billingError}</p> : null}
              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => void checkout("standard")}
                  className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
                >
                  Standard
                </button>
                <button
                  type="button"
                  onClick={() => void checkout("premium")}
                  className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-semibold text-zinc-900 dark:border-zinc-600 dark:text-zinc-50"
                >
                  Premium
                </button>
              </div>
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
