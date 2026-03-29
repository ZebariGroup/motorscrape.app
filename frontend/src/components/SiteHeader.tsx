"use client";

import Link from "next/link";

import type { AccessSummary } from "@/types/access";

type Props = {
  access: AccessSummary | null;
};

const headerPad =
  "px-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] sm:px-[max(1.5rem,env(safe-area-inset-left))] sm:pr-[max(1.5rem,env(safe-area-inset-right))]";

export function SiteHeader({ access }: Props) {
  if (access === null) {
    return (
      <header className="border-b border-zinc-200 bg-white/80 pt-[env(safe-area-inset-top,0px)] backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80">
        <div
          className={`mx-auto flex max-w-6xl flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between ${headerPad}`}
        >
          <div className="flex min-w-0 items-center gap-4">
            <Link href="/" className="shrink-0 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
              Motorscrape
            </Link>
            <span className="hidden text-xs text-zinc-500 sm:inline dark:text-zinc-400">
              We crawl so you can drive.
            </span>
          </div>
          <nav className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs sm:justify-end sm:gap-x-4 sm:text-sm">
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
    <header className="border-b border-zinc-200 bg-white/80 pt-[env(safe-area-inset-top,0px)] backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80">
      <div
        className={`mx-auto flex max-w-6xl flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between ${headerPad}`}
      >
        <div className="flex min-w-0 flex-col gap-1 sm:flex-row sm:items-center sm:gap-4">
          <Link href="/" className="shrink-0 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
            Motorscrape
          </Link>
          <span className="hidden text-xs text-zinc-500 sm:inline dark:text-zinc-400">
            We crawl so you can drive.
          </span>
          {(anonHint || usageHint) ? (
            <div className="flex min-w-0 flex-col gap-0.5 text-[11px] leading-snug sm:hidden">
              {anonHint ? (
                <span
                  title={anonHint}
                  className="truncate font-medium text-amber-800 dark:text-amber-200"
                >
                  {anonHint}
                </span>
              ) : null}
              {usageHint ? (
                <span title={usageHint} className="truncate text-zinc-600 dark:text-zinc-400">
                  {usageHint}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        <nav className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs sm:justify-end sm:gap-x-4 sm:text-sm">
          <div className="hidden min-w-0 max-w-[20rem] flex-col items-end gap-0.5 text-xs leading-snug sm:flex">
            {anonHint ? (
              <span
                title={anonHint}
                className="truncate font-medium text-amber-800 dark:text-amber-200"
              >
                {anonHint}
              </span>
            ) : null}
            {usageHint ? (
              <span title={usageHint} className="truncate text-zinc-600 dark:text-zinc-400">
                {usageHint}
              </span>
            ) : null}
          </div>
          {access.authenticated ? (
            <div className="flex items-center gap-2 sm:gap-3">
              {access.is_admin ? (
                <Link
                  href="/admin"
                  className="shrink-0 font-medium text-zinc-700 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-50"
                >
                  Admin
                </Link>
              ) : null}
              <Link
                href="/account"
                className="shrink-0 font-medium text-emerald-700 hover:text-emerald-800 dark:text-emerald-400 dark:hover:text-emerald-300"
              >
                Account
              </Link>
            </div>
          ) : (
            <div className="flex items-center gap-2 sm:gap-3">
              <Link
                href="/login"
                className="shrink-0 font-medium text-zinc-700 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-50"
              >
                Log in
              </Link>
              <Link
                href="/signup"
                className="shrink-0 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 sm:text-sm"
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
