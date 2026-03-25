"use client";

import Link from "next/link";

import type { AccessSummary } from "@/types/access";

type Props = {
  access: AccessSummary | null;
};

export function SiteHeader({ access }: Props) {
  return (
    <header className="border-b border-zinc-200 bg-white/80 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link href="/" className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
          Motorscrape
        </Link>
        <nav className="flex flex-wrap items-center justify-end gap-3 text-sm">
          {access?.authenticated ? (
            <>
              <span className="hidden text-zinc-500 sm:inline dark:text-zinc-400" title="Current plan">
                {access.tier}
              </span>
              <Link
                href="/account"
                className="font-medium text-emerald-700 hover:text-emerald-800 dark:text-emerald-400 dark:hover:text-emerald-300"
              >
                Account
              </Link>
            </>
          ) : (
            <>
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
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
