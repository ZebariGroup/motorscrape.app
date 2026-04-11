import Link from "next/link";
import type { Metadata } from "next";

import { DirectoryHeader } from "@/components/DirectoryHeader";
import { fetchDealerList, type DealerCard } from "@/lib/dealerApi";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Car Dealership Directory | Motorscrape",
  description:
    "Search thousands of car dealerships by brand, state, or name. Find dealer ratings, contact info, hours, and live inventory.",
  alternates: { canonical: "/dealers" },
};

// ─── Constants ───────────────────────────────────────────────────────────────

const ALL_STATES = [
  { abbr: "AL", name: "Alabama" },
  { abbr: "AK", name: "Alaska" },
  { abbr: "AZ", name: "Arizona" },
  { abbr: "AR", name: "Arkansas" },
  { abbr: "CA", name: "California" },
  { abbr: "CO", name: "Colorado" },
  { abbr: "CT", name: "Connecticut" },
  { abbr: "DE", name: "Delaware" },
  { abbr: "FL", name: "Florida" },
  { abbr: "GA", name: "Georgia" },
  { abbr: "HI", name: "Hawaii" },
  { abbr: "ID", name: "Idaho" },
  { abbr: "IL", name: "Illinois" },
  { abbr: "IN", name: "Indiana" },
  { abbr: "IA", name: "Iowa" },
  { abbr: "KS", name: "Kansas" },
  { abbr: "KY", name: "Kentucky" },
  { abbr: "LA", name: "Louisiana" },
  { abbr: "ME", name: "Maine" },
  { abbr: "MD", name: "Maryland" },
  { abbr: "MA", name: "Massachusetts" },
  { abbr: "MI", name: "Michigan" },
  { abbr: "MN", name: "Minnesota" },
  { abbr: "MS", name: "Mississippi" },
  { abbr: "MO", name: "Missouri" },
  { abbr: "MT", name: "Montana" },
  { abbr: "NE", name: "Nebraska" },
  { abbr: "NV", name: "Nevada" },
  { abbr: "NH", name: "New Hampshire" },
  { abbr: "NJ", name: "New Jersey" },
  { abbr: "NM", name: "New Mexico" },
  { abbr: "NY", name: "New York" },
  { abbr: "NC", name: "North Carolina" },
  { abbr: "ND", name: "North Dakota" },
  { abbr: "OH", name: "Ohio" },
  { abbr: "OK", name: "Oklahoma" },
  { abbr: "OR", name: "Oregon" },
  { abbr: "PA", name: "Pennsylvania" },
  { abbr: "RI", name: "Rhode Island" },
  { abbr: "SC", name: "South Carolina" },
  { abbr: "SD", name: "South Dakota" },
  { abbr: "TN", name: "Tennessee" },
  { abbr: "TX", name: "Texas" },
  { abbr: "UT", name: "Utah" },
  { abbr: "VT", name: "Vermont" },
  { abbr: "VA", name: "Virginia" },
  { abbr: "WA", name: "Washington" },
  { abbr: "WV", name: "West Virginia" },
  { abbr: "WI", name: "Wisconsin" },
  { abbr: "WY", name: "Wyoming" },
];

const POPULAR_MAKES = [
  "Acura", "Alfa Romeo", "Audi", "BMW", "Buick", "Cadillac", "Chevrolet",
  "Chrysler", "Dodge", "Ford", "Genesis", "GMC", "Honda", "Hyundai",
  "Infiniti", "Jeep", "Kia", "Land Rover", "Lexus", "Lincoln", "Mazda",
  "Mercedes-Benz", "Mitsubishi", "Nissan", "Porsche", "RAM", "Subaru",
  "Tesla", "Toyota", "Volkswagen", "Volvo",
];

const SORT_OPTIONS = [
  { value: "rating_desc", label: "Highest Rated" },
  { value: "reviews_desc", label: "Most Reviews" },
  { value: "name_asc", label: "Name A–Z" },
  { value: "enriched_first", label: "Verified First" },
];

const LIMIT = 36;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function buildUrl(
  params: Record<string, string | number | undefined>,
): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "" && !(k === "page" && v === 1)) {
      sp.set(k, String(v));
    }
  }
  const qs = sp.toString();
  return qs ? `/dealers?${qs}` : "/dealers";
}

function parseState(abbr: string | undefined) {
  if (!abbr) return undefined;
  return ALL_STATES.find((s) => s.abbr === abbr.toUpperCase()) ?? undefined;
}

// ─── Sub-components (server) ──────────────────────────────────────────────────

function StarRating({ rating, size = "sm" }: { rating: number; size?: "sm" | "md" }) {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  const dim = size === "md" ? "h-4 w-4" : "h-3.5 w-3.5";
  return (
    <span className="flex items-center gap-0.5" aria-label={`${rating} stars`}>
      {Array.from({ length: 5 }, (_, i) => {
        const filled = i < full;
        const isHalf = !filled && i === full && half;
        return (
          <svg key={i} viewBox="0 0 20 20" className={`${dim} ${filled || isHalf ? "text-amber-400" : "text-zinc-200 dark:text-zinc-700"}`} fill="currentColor" aria-hidden>
            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
          </svg>
        );
      })}
    </span>
  );
}

function DealerGridCard({ dealer, baseParams }: { dealer: DealerCard; baseParams: Record<string, string | undefined> }) {
  const parts = dealer.address.split(",");
  const street = parts[0]?.trim() ?? "";
  const cityState = parts.slice(1, 3).join(",").trim();

  return (
    <div className="group relative flex flex-col rounded-2xl border border-zinc-200/80 bg-white shadow-sm transition-all duration-200 hover:border-emerald-300 hover:shadow-lg dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-emerald-700/60">
      {/* Card header */}
      <div className="flex flex-col gap-2 p-5 pb-3">
        <div className="flex items-start justify-between gap-2">
          <Link href={`/dealers/${dealer.slug}`} className="flex-1 min-w-0">
            <h2 className="text-sm font-bold text-zinc-900 group-hover:text-emerald-700 dark:text-zinc-50 dark:group-hover:text-emerald-400 leading-snug line-clamp-2">
              {dealer.name}
            </h2>
          </Link>
          {dealer.enriched && (
            <span className="shrink-0 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-800">
              <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none" aria-hidden>
                <circle cx="6" cy="6" r="5.5" stroke="currentColor" strokeWidth="1" />
                <path d="M3.5 6l1.5 1.5 3.5-3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Verified
            </span>
          )}
        </div>

        {/* Address */}
        <div className="flex items-start gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
          <svg viewBox="0 0 16 16" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-400" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M8 1.5C5.515 1.5 3.5 3.515 3.5 6c0 3.5 4.5 8.5 4.5 8.5S12.5 9.5 12.5 6c0-2.485-2.015-4.5-4.5-4.5Z" />
            <circle cx="8" cy="6" r="1.5" />
          </svg>
          <span className="leading-snug">
            {street && <span className="block">{street}</span>}
            {cityState && <span>{cityState}</span>}
          </span>
        </div>

        {/* Rating */}
        {dealer.rating != null ? (
          <div className="flex items-center gap-2">
            <StarRating rating={dealer.rating} />
            <span className="text-sm font-bold text-zinc-800 dark:text-zinc-200">{dealer.rating.toFixed(1)}</span>
            {dealer.review_count != null && (
              <span className="text-xs text-zinc-400 dark:text-zinc-500">({dealer.review_count.toLocaleString()} reviews)</span>
            )}
          </div>
        ) : (
          <div className="text-xs text-zinc-400 dark:text-zinc-600">No rating yet</div>
        )}
      </div>

      {/* Divider */}
      <div className="mx-5 border-t border-zinc-100 dark:border-zinc-800/80" />

      {/* Brands */}
      <div className="flex flex-wrap gap-1.5 px-5 py-3">
        {dealer.oem_brands.length > 0 ? (
          <>
            {dealer.oem_brands.slice(0, 5).map((brand) => (
              <Link
                key={brand}
                href={buildUrl({ ...baseParams, make: brand, page: undefined })}
                className="rounded-full bg-sky-50 px-2.5 py-0.5 text-[10px] font-semibold text-sky-700 ring-1 ring-sky-200/80 hover:bg-sky-100 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-800/50 dark:hover:bg-sky-900/60 transition-colors"
              >
                {brand}
              </Link>
            ))}
            {dealer.oem_brands.length > 5 && (
              <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-[10px] font-medium text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                +{dealer.oem_brands.length - 5}
              </span>
            )}
          </>
        ) : (
          <span className="text-[10px] text-zinc-400 dark:text-zinc-600">No brands listed</span>
        )}
      </div>

      {/* Footer action */}
      <div className="mt-auto px-5 pb-5">
        <Link
          href={`/dealers/${dealer.slug}`}
          className="flex items-center justify-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700 transition-colors"
        >
          View Dealer
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M3 8h10M9 4l4 4-4 4" />
          </svg>
        </Link>
      </div>
    </div>
  );
}

function DealerListRow({ dealer, baseParams }: { dealer: DealerCard; baseParams: Record<string, string | undefined> }) {
  const parts = dealer.address.split(",");
  const cityState = parts.slice(1, 3).join(",").trim();

  return (
    <div className="group flex items-center gap-4 rounded-xl border border-zinc-200/80 bg-white px-5 py-4 shadow-sm transition-all hover:border-emerald-300 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-emerald-700/60">
      {/* Name + address */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <Link href={`/dealers/${dealer.slug}`}>
            <span className="text-sm font-bold text-zinc-900 group-hover:text-emerald-700 dark:text-zinc-50 dark:group-hover:text-emerald-400 leading-snug">
              {dealer.name}
            </span>
          </Link>
          {dealer.enriched && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-800">
              <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none" aria-hidden>
                <circle cx="6" cy="6" r="5.5" stroke="currentColor" strokeWidth="1" />
                <path d="M3.5 6l1.5 1.5 3.5-3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Verified
            </span>
          )}
        </div>
        {cityState && (
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{cityState}</p>
        )}
      </div>

      {/* Brands */}
      <div className="hidden sm:flex flex-wrap gap-1 min-w-0 max-w-[200px]">
        {dealer.oem_brands.slice(0, 3).map((brand) => (
          <Link
            key={brand}
            href={buildUrl({ ...baseParams, make: brand, page: undefined })}
            className="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-semibold text-sky-700 ring-1 ring-sky-200/80 hover:bg-sky-100 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-800/50 transition-colors"
          >
            {brand}
          </Link>
        ))}
        {dealer.oem_brands.length > 3 && (
          <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-medium text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            +{dealer.oem_brands.length - 3}
          </span>
        )}
      </div>

      {/* Rating */}
      <div className="hidden md:flex items-center gap-1.5 shrink-0 w-28">
        {dealer.rating != null ? (
          <>
            <StarRating rating={dealer.rating} />
            <span className="text-sm font-bold text-zinc-800 dark:text-zinc-200">{dealer.rating.toFixed(1)}</span>
          </>
        ) : (
          <span className="text-xs text-zinc-400">—</span>
        )}
      </div>

      {/* Reviews count */}
      <div className="hidden lg:block text-xs text-zinc-500 dark:text-zinc-400 shrink-0 w-24 text-right">
        {dealer.review_count != null ? `${dealer.review_count.toLocaleString()} reviews` : ""}
      </div>

      {/* CTA */}
      <Link
        href={`/dealers/${dealer.slug}`}
        className="shrink-0 flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 transition-colors"
      >
        View
        <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M3 8h10M9 4l4 4-4 4" />
        </svg>
      </Link>
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  buildPageUrl,
}: {
  page: number;
  totalPages: number;
  buildPageUrl: (p: number) => string;
}) {
  if (totalPages <= 1) return null;

  const delta = 2;
  const range: (number | "…")[] = [];
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= page - delta && i <= page + delta)) {
      range.push(i);
    } else if (range[range.length - 1] !== "…") {
      range.push("…");
    }
  }

  return (
    <div className="flex items-center justify-center gap-1.5 pt-2">
      {page > 1 && (
        <Link
          href={buildPageUrl(page - 1)}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-200 bg-white text-sm font-medium text-zinc-600 hover:bg-zinc-50 hover:border-zinc-300 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors"
          aria-label="Previous page"
        >
          <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M10 4l-4 4 4 4" />
          </svg>
        </Link>
      )}
      {range.map((item, i) =>
        item === "…" ? (
          <span key={`ellipsis-${i}`} className="flex h-9 w-9 items-center justify-center text-sm text-zinc-400">…</span>
        ) : (
          <Link
            key={item}
            href={buildPageUrl(item)}
            className={`flex h-9 w-9 items-center justify-center rounded-lg text-sm font-medium transition-colors ${
              item === page
                ? "bg-emerald-600 text-white shadow-sm"
                : "border border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50 hover:border-zinc-300 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
            }`}
            aria-current={item === page ? "page" : undefined}
          >
            {item}
          </Link>
        )
      )}
      {page < totalPages && (
        <Link
          href={buildPageUrl(page + 1)}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-200 bg-white text-sm font-medium text-zinc-600 hover:bg-zinc-50 hover:border-zinc-300 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 transition-colors"
          aria-label="Next page"
        >
          <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M6 4l4 4-4 4" />
          </svg>
        </Link>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function DealersIndexPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;

  const q = typeof sp.q === "string" && sp.q ? sp.q : undefined;
  const make = typeof sp.make === "string" && sp.make ? sp.make : undefined;
  const state = typeof sp.state === "string" && sp.state ? sp.state : undefined;
  const sort = typeof sp.sort === "string" && sp.sort ? sp.sort : "rating_desc";
  const view = sp.view === "list" ? "list" : "grid";
  const pageStr = typeof sp.page === "string" ? sp.page : "1";
  const page = Math.max(1, parseInt(pageStr, 10) || 1);
  const offset = (page - 1) * LIMIT;

  const stateObj = parseState(state);

  const { dealers, total } = await fetchDealerList({
    q,
    make,
    state,
    sort,
    limit: LIMIT,
    offset,
  });

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));

  const baseParams: Record<string, string | undefined> = {
    q,
    make,
    state,
    sort: sort !== "rating_desc" ? sort : undefined,
    view: view !== "grid" ? view : undefined,
  };

  const buildPageUrl = (p: number) => buildUrl({ ...baseParams, page: p });

  const hasFilters = !!(q || make || state);
  const sortLabel = SORT_OPTIONS.find((o) => o.value === sort)?.label ?? "Highest Rated";

  return (
    <>
      <DirectoryHeader />

      {/* ── Hero ── */}
      <div className="bg-zinc-950 dark:bg-zinc-950 border-b border-zinc-800">
        <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-14">
          <h1 className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
            Dealership Directory
          </h1>
          <p className="mt-2 text-zinc-400 text-sm sm:text-base">
            {total > 0
              ? `${total.toLocaleString()} dealer${total !== 1 ? "s" : ""} indexed — search by name, brand, or state`
              : "Search car dealerships by name, brand, or location"}
          </p>

          {/* Search bar */}
          <form action="/dealers" method="GET" className="mt-6">
            {/* Preserve non-search params */}
            {make && <input type="hidden" name="make" value={make} />}
            {state && <input type="hidden" name="state" value={state} />}
            {sort !== "rating_desc" && <input type="hidden" name="sort" value={sort} />}
            {view !== "grid" && <input type="hidden" name="view" value={view} />}

            <div className="flex items-center rounded-2xl bg-white ring-1 ring-zinc-200 shadow-xl overflow-hidden dark:bg-zinc-900 dark:ring-zinc-700">
              <span className="pl-4 pr-2 text-zinc-400 dark:text-zinc-500 shrink-0">
                <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <circle cx="8.5" cy="8.5" r="5.5" />
                  <path d="M14.5 14.5l3.5 3.5" />
                </svg>
              </span>
              <input
                type="text"
                name="q"
                defaultValue={q}
                placeholder="Search dealers by name, city, or brand…"
                className="flex-1 bg-transparent py-4 pr-4 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none dark:text-zinc-100 dark:placeholder:text-zinc-500"
                autoComplete="off"
              />
              {q && (
                <Link
                  href={buildUrl({ ...baseParams, q: undefined, page: undefined })}
                  className="mr-2 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                  aria-label="Clear search"
                >
                  <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
                    <path d="M4 4l8 8M12 4l-8 8" />
                  </svg>
                </Link>
              )}
              <button
                type="submit"
                className="m-1.5 shrink-0 rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700 transition-colors"
              >
                Search
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* ── Filter strip ── */}
      <div className="sticky top-0 z-20 border-b border-zinc-200 bg-white/95 backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-950/95">
        <form action="/dealers" method="GET">
          {/* Preserve search query */}
          {q && <input type="hidden" name="q" value={q} />}
          {view !== "grid" && <input type="hidden" name="view" value={view} />}

          <div className="mx-auto flex max-w-6xl items-center gap-2 overflow-x-auto px-4 py-3 sm:px-6">
            {/* Make */}
            <div className="shrink-0">
              <select
                name="make"
                defaultValue={make ?? ""}
                className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-700 shadow-sm hover:border-zinc-300 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                aria-label="Filter by make"
              >
                <option value="">All Makes</option>
                {POPULAR_MAKES.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>

            {/* State */}
            <div className="shrink-0">
              <select
                name="state"
                defaultValue={state ?? ""}
                className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-700 shadow-sm hover:border-zinc-300 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                aria-label="Filter by state"
              >
                <option value="">All States</option>
                {ALL_STATES.map((s) => (
                  <option key={s.abbr} value={s.abbr}>{s.name}</option>
                ))}
              </select>
            </div>

            {/* Sort */}
            <div className="shrink-0">
              <select
                name="sort"
                defaultValue={sort}
                className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-700 shadow-sm hover:border-zinc-300 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                aria-label="Sort results"
              >
                {SORT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>

            {/* Apply */}
            <button
              type="submit"
              className="shrink-0 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-700 transition-colors dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              Apply
            </button>

            {/* Spacer */}
            <div className="flex-1" />

            {/* View toggle */}
            <div className="shrink-0 flex items-center gap-1 rounded-lg border border-zinc-200 bg-zinc-50 p-1 dark:border-zinc-700 dark:bg-zinc-900">
              <Link
                href={buildUrl({ ...baseParams, view: undefined, page: undefined })}
                className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${view === "grid" ? "bg-white shadow-sm text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100" : "text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"}`}
                aria-label="Grid view"
                title="Grid view"
              >
                <svg viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor" aria-hidden>
                  <rect x="1" y="1" width="6" height="6" rx="1" />
                  <rect x="9" y="1" width="6" height="6" rx="1" />
                  <rect x="1" y="9" width="6" height="6" rx="1" />
                  <rect x="9" y="9" width="6" height="6" rx="1" />
                </svg>
              </Link>
              <Link
                href={buildUrl({ ...baseParams, view: "list", page: undefined })}
                className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${view === "list" ? "bg-white shadow-sm text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100" : "text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"}`}
                aria-label="List view"
                title="List view"
              >
                <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
                  <path d="M3 4h10M3 8h10M3 12h10" />
                </svg>
              </Link>
            </div>
          </div>
        </form>
      </div>

      {/* ── Main content ── */}
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">

        {/* Active filter pills */}
        {hasFilters && (
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Filters:</span>
            {q && (
              <Link
                href={buildUrl({ ...baseParams, q: undefined, page: undefined })}
                className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900 pl-3 pr-2 py-1 text-xs font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
              >
                &ldquo;{q}&rdquo;
                <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
                  <path d="M3 3l6 6M9 3l-6 6" />
                </svg>
              </Link>
            )}
            {make && (
              <Link
                href={buildUrl({ ...baseParams, make: undefined, page: undefined })}
                className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 pl-3 pr-2 py-1 text-xs font-medium text-white"
              >
                {make}
                <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
                  <path d="M3 3l6 6M9 3l-6 6" />
                </svg>
              </Link>
            )}
            {state && (
              <Link
                href={buildUrl({ ...baseParams, state: undefined, page: undefined })}
                className="inline-flex items-center gap-1.5 rounded-full bg-violet-600 pl-3 pr-2 py-1 text-xs font-medium text-white"
              >
                {stateObj?.name ?? state}
                <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
                  <path d="M3 3l6 6M9 3l-6 6" />
                </svg>
              </Link>
            )}
            <Link
              href="/dealers"
              className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 underline underline-offset-2 transition-colors"
            >
              Clear all
            </Link>
          </div>
        )}

        {/* Results bar */}
        <div className="mb-4 flex items-center justify-between">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {total > 0 ? (
              <>
                <span className="font-semibold text-zinc-900 dark:text-zinc-100">
                  {(offset + 1).toLocaleString()}–{Math.min(offset + LIMIT, total).toLocaleString()}
                </span>{" "}
                of{" "}
                <span className="font-semibold text-zinc-900 dark:text-zinc-100">{total.toLocaleString()}</span> dealers
                {hasFilters && <span className="text-zinc-400"> matching filters</span>}
              </>
            ) : (
              "No dealers found"
            )}
          </p>
          <p className="hidden sm:block text-xs text-zinc-400 dark:text-zinc-500">
            Sorted by <span className="font-medium text-zinc-600 dark:text-zinc-400">{sortLabel}</span>
          </p>
        </div>

        {/* Results */}
        {dealers.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 bg-zinc-50 p-12 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-zinc-200 dark:bg-zinc-800">
              <svg viewBox="0 0 20 20" className="h-6 w-6 text-zinc-400" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <circle cx="8.5" cy="8.5" r="5.5" />
                <path d="M14.5 14.5l3.5 3.5" />
              </svg>
            </div>
            <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">No dealers found</p>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-500">
              {hasFilters ? "Try adjusting your filters or search terms." : "Dealers appear as inventory is discovered."}
            </p>
            <div className="mt-5 flex items-center justify-center gap-3">
              {hasFilters && (
                <Link href="/dealers" className="rounded-xl border border-zinc-300 bg-white px-4 py-2 text-sm font-semibold text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
                  Clear Filters
                </Link>
              )}
              <Link href="/" className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700">
                Search Inventory
              </Link>
            </div>
          </div>
        ) : view === "list" ? (
          <div className="flex flex-col gap-2">
            {/* List header */}
            <div className="hidden md:grid grid-cols-[1fr_200px_140px_100px_80px] gap-4 px-5 pb-1">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Dealer</span>
              <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Brands</span>
              <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">Rating</span>
              <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400 text-right">Reviews</span>
              <span className="sr-only">Action</span>
            </div>
            {dealers.map((d) => (
              <DealerListRow key={d.slug} dealer={d} baseParams={baseParams} />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {dealers.map((d) => (
              <DealerGridCard key={d.slug} dealer={d} baseParams={baseParams} />
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="mt-10 flex flex-col items-center gap-3">
            <Pagination page={page} totalPages={totalPages} buildPageUrl={buildPageUrl} />
            <p className="text-xs text-zinc-400 dark:text-zinc-500">
              Page {page} of {totalPages.toLocaleString()}
            </p>
          </div>
        )}
      </main>
    </>
  );
}
