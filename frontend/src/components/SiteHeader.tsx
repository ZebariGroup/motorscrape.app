"use client";

import Link from "next/link";

import type { AccessSummary } from "@/types/access";

type Props = {
  access: AccessSummary | null;
};

export function SiteHeader({ access }: Props) {
  if (access === null) {
    return (
      <header className="border-b border-zinc-200 bg-white/80 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-4">
            <Link href="/" className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
              Motorscrape
            </Link>
            <span className="hidden text-xs text-zinc-500 sm:inline dark:text-zinc-400">We crawl so you can drive.</span>
          </div>
          <nav className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2 text-sm">
            <div className="h-6 w-28 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
          </nav>
        </div>
      </header>
    );
  }

  const anonHint =
    !access.authenticated && access.anonymous
      ? `${access.anonymous.searches_remaining} of ${access.anonymous.signup_required_after} free scrapes left`
      : null;

  const usageHint =
    access?.authenticated && access.usage
      ? `Plan ${access.tier} · ${access.usage.included_used}/${access.usage.included_limit} scrapes this month` +
        (access.usage.overage_used ? ` · ${access.usage.overage_used} overage` : "")
      : null;

  return (
    <header className="border-b border-zinc-200 bg-white/80 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4">
          <Link href="/" className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
            Motorscrape
          </Link>
          <span className="hidden text-xs text-zinc-500 sm:inline dark:text-zinc-400">We crawl so you can drive.</span>
        </div>
        <nav className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2 text-sm">
          <div className="flex flex-col items-end text-xs">
            {anonHint ? (
              <span className="font-medium text-amber-800 dark:text-amber-200">{anonHint}</span>
            ) : null}
            {usageHint ? (
              <span className="text-zinc-600 dark:text-zinc-400">{usageHint}</span>
            ) : null}
          </div>
          {access.authenticated ? (
            <div className="flex items-center gap-3">
              {access.is_admin ? (
                <Link
                  href="/admin"
                  className="font-medium text-zinc-700 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-50"
                >
                  Admin
                </Link>
              ) : null}
              <Link
                href="/account"
                className="font-medium text-emerald-700 hover:text-emerald-800 dark:text-emerald-400 dark:hover:text-emerald-300"
              >
                Account
              </Link>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <Link
                href="/login"
                className="font-medium text-zinc-700 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-50"
              >
                Log in
              </Link>
              <Link
                href="/signup"
                className="rounded-lg bg-emerald-600 px-3 py-1.5 font-semibold text-white hover:bg-emerald-500"
              >
                Sign up
              </Link>
            </div>
          )}
        </nav>
      </div>
    </header>
  );
}
