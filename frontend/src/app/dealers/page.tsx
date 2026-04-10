import Link from "next/link";
import type { Metadata } from "next";

import { DirectoryHeader } from "@/components/DirectoryHeader";

export const metadata: Metadata = {
  title: "Car Dealership Directory | Motorscrape",
  description:
    "Browse our directory of local car dealerships verified by Motorscrape. Find dealer hours, contact info, ratings, and search live inventory.",
  alternates: { canonical: "/dealers" },
};

export default function DealersIndexPage() {
  return (
    <>
      <DirectoryHeader />
      <main className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 py-8 sm:px-6 sm:py-12">
        <header>
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
            Dealership Directory
          </h1>
          <p className="mt-2 max-w-2xl text-zinc-600 dark:text-zinc-400">
            Every dealership in our directory has been discovered and verified by Motorscrape. Click a
            dealer profile to see hours, contact info, services, ratings, and to search their live
            inventory.
          </p>
        </header>

        <div className="rounded-2xl border border-zinc-200 bg-zinc-50 p-6 dark:border-zinc-800 dark:bg-zinc-900/40">
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
            How to find a dealer
          </h2>
          <ul className="mt-3 space-y-2 text-sm text-zinc-600 dark:text-zinc-400">
            <li>
              <strong className="text-zinc-800 dark:text-zinc-200">Search first</strong> — run a live
              inventory search from the{" "}
              <Link href="/" className="text-emerald-600 hover:underline dark:text-emerald-400">
                home page
              </Link>
              . Dealers discovered during your search are automatically added to this directory.
            </li>
            <li>
              <strong className="text-zinc-800 dark:text-zinc-200">Browse the directory</strong> — as
              we index more dealers over time, you&apos;ll be able to filter by make, state, and city
              here.
            </li>
            <li>
              <strong className="text-zinc-800 dark:text-zinc-200">Deep profiles</strong> — each
              dealer page shows Google ratings, hours, social links, OEM brands, services, and
              inventory price ranges from past scrapes.
            </li>
          </ul>
        </div>

        <div className="flex gap-4">
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700"
          >
            Search Inventory
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M3 8h10M9 4l4 4-4 4" />
            </svg>
          </Link>
          <Link
            href="/directory"
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-5 py-2.5 text-sm font-semibold text-zinc-700 shadow-sm hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
          >
            Browse by Make &amp; Location
          </Link>
        </div>
      </main>
    </>
  );
}
