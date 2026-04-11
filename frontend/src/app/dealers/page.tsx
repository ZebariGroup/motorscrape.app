import Link from "next/link";
import type { Metadata } from "next";

import { DirectoryHeader } from "@/components/DirectoryHeader";
import { fetchDealerList, type DealerCard } from "@/lib/dealerApi";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Car Dealership Directory | Motorscrape",
  description:
    "Browse our directory of local car dealerships verified by Motorscrape. Find dealer hours, contact info, ratings, and search live inventory.",
  alternates: { canonical: "/dealers" },
};

function StarRating({ rating }: { rating: number }) {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  return (
    <span className="flex items-center gap-0.5" aria-label={`${rating} out of 5`}>
      {Array.from({ length: 5 }, (_, i) => {
        const filled = i < full;
        const isHalf = !filled && i === full && half;
        return (
          <svg
            key={i}
            viewBox="0 0 20 20"
            className={`h-3.5 w-3.5 ${filled || isHalf ? "text-amber-400" : "text-zinc-300 dark:text-zinc-600"}`}
            fill="currentColor"
            aria-hidden
          >
            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
          </svg>
        );
      })}
    </span>
  );
}

function DealerCard({ dealer }: { dealer: DealerCard }) {
  const city = dealer.address.split(",")[0]?.trim() ?? dealer.address;
  const stateZip = dealer.address.split(",").slice(1, 3).join(",").trim();

  return (
    <Link
      href={`/dealers/${dealer.slug}`}
      className="group flex flex-col gap-3 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm transition hover:border-emerald-300 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-emerald-700"
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold text-zinc-900 group-hover:text-emerald-700 dark:text-zinc-50 dark:group-hover:text-emerald-400 leading-snug">
          {dealer.name}
        </h2>
        {dealer.enriched && (
          <span className="shrink-0 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-800">
            <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none" aria-hidden>
              <circle cx="6" cy="6" r="5.5" stroke="currentColor" strokeWidth="1" />
              <path d="M3.5 6l1.5 1.5 3.5-3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Verified
          </span>
        )}
      </div>

      <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-snug">
        {city}
        {stateZip ? `, ${stateZip}` : ""}
      </p>

      {dealer.rating != null && (
        <div className="flex items-center gap-1.5">
          <StarRating rating={dealer.rating} />
          <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            {dealer.rating.toFixed(1)}
          </span>
          {dealer.review_count != null && (
            <span className="text-xs text-zinc-400 dark:text-zinc-500">
              ({dealer.review_count.toLocaleString()})
            </span>
          )}
        </div>
      )}

      {dealer.oem_brands.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {dealer.oem_brands.slice(0, 4).map((brand) => (
            <span
              key={brand}
              className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-blue-950/50 dark:text-blue-300"
            >
              {brand}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}

export default async function DealersIndexPage() {
  const { dealers, total } = await fetchDealerList({ limit: 48 });

  return (
    <>
      <DirectoryHeader />
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-8 sm:px-6 sm:py-12">
        <header className="flex flex-col gap-1">
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
            Dealership Directory
          </h1>
          <p className="mt-1 max-w-2xl text-zinc-500 dark:text-zinc-400">
            {total > 0
              ? `${total.toLocaleString()} dealer${total !== 1 ? "s" : ""} indexed by Motorscrape. Click any card to see hours, contact info, ratings, and inventory.`
              : "Dealers appear here after being discovered through inventory searches."}
          </p>
        </header>

        {dealers.length === 0 ? (
          <div className="rounded-2xl border border-zinc-200 bg-zinc-50 p-8 text-center dark:border-zinc-800 dark:bg-zinc-900/40">
            <p className="text-sm font-medium text-zinc-600 dark:text-zinc-400">
              No dealers indexed yet.
            </p>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-500">
              Run a live inventory search to start building the directory.
            </p>
            <Link
              href="/"
              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700"
            >
              Search Inventory
              <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M3 8h10M9 4l4 4-4 4" />
              </svg>
            </Link>
          </div>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {dealers.map((d) => (
                <DealerCard key={d.slug} dealer={d} />
              ))}
            </div>

            {total > 48 && (
              <p className="text-center text-sm text-zinc-400 dark:text-zinc-500">
                Showing 48 of {total.toLocaleString()} dealers.{" "}
                <Link href="/directory" className="text-emerald-600 hover:underline dark:text-emerald-400">
                  Browse by make &amp; location
                </Link>{" "}
                to filter.
              </p>
            )}
          </>
        )}

        <div className="flex flex-wrap gap-4 border-t border-zinc-100 pt-6 dark:border-zinc-800">
          <Link
            href="/directory"
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-5 py-2.5 text-sm font-semibold text-zinc-700 shadow-sm hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
          >
            Browse by Make &amp; Location
          </Link>
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700"
          >
            Search Inventory
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M3 8h10M9 4l4 4-4 4" />
            </svg>
          </Link>
        </div>
      </main>
    </>
  );
}
