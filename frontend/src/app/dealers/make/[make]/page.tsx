import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";

import { DirectoryHeader } from "@/components/DirectoryHeader";
import { fetchDealerList, type DealerCard } from "@/lib/dealerApi";
import { ALL_STATES, POPULAR_MAKES, makeBySlug } from "@/lib/dealerDirectory";

export const revalidate = 3600;

type Props = {
  params: Promise<{ make: string }>;
};

export async function generateStaticParams() {
  return POPULAR_MAKES.map((m) => ({ make: m.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { make: makeSlug } = await params;
  const makeEntry = makeBySlug(makeSlug);
  if (!makeEntry) return { title: "Not Found" };

  const title = `${makeEntry.name} Dealerships | Motorscrape`;
  const description = `Browse ${makeEntry.name} car dealerships nationwide. Find dealer ratings, phone numbers, hours, and live ${makeEntry.name} inventory in your area.`;

  return {
    title,
    description,
    alternates: { canonical: `/dealers/make/${makeSlug}` },
    openGraph: { title, description, type: "website" },
  };
}

// ─── Shared UI atoms ──────────────────────────────────────────────────────────

function StarRating({ rating }: { rating: number }) {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  const dim = "h-3.5 w-3.5";
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

function DealerCard({ dealer }: { dealer: DealerCard }) {
  const parts = dealer.address.split(",");
  const street = parts[0]?.trim() ?? "";
  const cityState = parts.slice(1, 3).join(",").trim();

  return (
    <div className="group relative flex flex-col rounded-2xl border border-zinc-200/80 bg-white shadow-sm transition-all duration-200 hover:border-emerald-300 hover:shadow-lg dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-emerald-700/60">
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

        {dealer.phone && (
          <a href={`tel:${dealer.phone}`} className="flex items-center gap-1.5 text-xs text-emerald-700 hover:text-emerald-900 dark:text-emerald-400 dark:hover:text-emerald-200 transition-colors">
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M2.5 3.5c0-.83.67-1.5 1.5-1.5h1.5l1.5 3-1.75 1.75A10.5 10.5 0 009 10.25L10.75 8.5l3 1.5V11.5A1.5 1.5 0 0112.25 13C6.58 13 2 8.42 2 2.75" />
            </svg>
            {dealer.phone}
          </a>
        )}

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

      <div className="mx-5 border-t border-zinc-100 dark:border-zinc-800/80" />

      <div className="flex flex-wrap gap-1.5 px-5 py-3">
        {dealer.oem_brands.length > 0 ? (
          <>
            {dealer.oem_brands.slice(0, 5).map((brand) => (
              <Link
                key={brand}
                href={`/dealers/make/${POPULAR_MAKES.find((m) => m.name === brand)?.slug ?? brand.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "")}`}
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

// ─── Page ─────────────────────────────────────────────────────────────────────

const LIMIT = 36;

export default async function MakeDirectoryPage({ params }: Props) {
  const { make: makeSlug } = await params;
  const makeEntry = makeBySlug(makeSlug);
  if (!makeEntry) notFound();

  const { dealers, total } = await fetchDealerList({
    make: makeEntry.name,
    sort: "rating_desc",
    limit: LIMIT,
    revalidate: 3600,
  });

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: `${makeEntry.name} Dealerships`,
    description: `Directory of ${makeEntry.name} dealerships nationwide`,
    url: `https://www.motorscrape.com/dealers/make/${makeSlug}`,
    numberOfItems: total,
    itemListElement: dealers.slice(0, 10).map((d, i) => ({
      "@type": "ListItem",
      position: i + 1,
      item: {
        "@type": "AutoDealer",
        name: d.name,
        address: d.address,
        telephone: d.phone ?? undefined,
        url: `https://www.motorscrape.com/dealers/${d.slug}`,
      },
    })),
  };

  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: "https://www.motorscrape.com" },
      { "@type": "ListItem", position: 2, name: "Dealers", item: "https://www.motorscrape.com/dealers" },
      { "@type": "ListItem", position: 3, name: `${makeEntry.name} Dealers`, item: `https://www.motorscrape.com/dealers/make/${makeSlug}` },
    ],
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }} />

      <DirectoryHeader />

      {/* Hero */}
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-14">
          {/* Breadcrumb */}
          <nav className="mb-4 flex items-center gap-1.5 text-xs text-zinc-500" aria-label="Breadcrumb">
            <Link href="/" className="hover:text-zinc-300 transition-colors">Home</Link>
            <span aria-hidden>/</span>
            <Link href="/dealers" className="hover:text-zinc-300 transition-colors">Dealers</Link>
            <span aria-hidden>/</span>
            <span className="text-zinc-300">{makeEntry.name}</span>
          </nav>

          <h1 className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
            {makeEntry.name} Dealerships
          </h1>
          <p className="mt-2 text-zinc-400 text-sm sm:text-base">
            {total > 0
              ? `${total.toLocaleString()} authorized ${makeEntry.name} dealer${total !== 1 ? "s" : ""} — ratings, phone numbers, hours, and live inventory`
              : `${makeEntry.name} dealerships appear as inventory is discovered`}
          </p>

          <div className="mt-5 flex flex-wrap gap-2">
            <Link
              href={`/dealers?make=${encodeURIComponent(makeEntry.name)}`}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-700 bg-zinc-800 px-4 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-700 transition-colors"
            >
              Filter &amp; Sort {makeEntry.name} Dealers
            </Link>
            <Link
              href="/dealers"
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition-colors"
            >
              All Brands
            </Link>
          </div>
        </div>
      </div>

      {/* Results */}
      <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
        {dealers.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 bg-zinc-50 p-12 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
            <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">No {makeEntry.name} dealers indexed yet</p>
            <p className="mt-1 text-sm text-zinc-500">Check back soon as we discover more inventory.</p>
            <Link href="/dealers" className="mt-5 inline-block rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700">
              Browse All Dealers
            </Link>
          </div>
        ) : (
          <>
            <div className="mb-4 flex items-center justify-between">
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                Showing top{" "}
                <span className="font-semibold text-zinc-900 dark:text-zinc-100">{Math.min(LIMIT, total).toLocaleString()}</span>
                {total > LIMIT && (
                  <> of <span className="font-semibold text-zinc-900 dark:text-zinc-100">{total.toLocaleString()}</span></>
                )}{" "}
                {makeEntry.name} dealers
              </p>
              {total > LIMIT && (
                <Link href={`/dealers?make=${encodeURIComponent(makeEntry.name)}`} className="text-xs text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 font-medium">
                  View all →
                </Link>
              )}
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {dealers.map((d) => (
                <DealerCard key={d.slug} dealer={d} />
              ))}
            </div>

            {total > LIMIT && (
              <div className="mt-8 text-center">
                <Link
                  href={`/dealers?make=${encodeURIComponent(makeEntry.name)}`}
                  className="inline-flex items-center gap-2 rounded-xl bg-zinc-900 px-6 py-3 text-sm font-semibold text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200 transition-colors"
                >
                  View All {total.toLocaleString()} {makeEntry.name} Dealers
                  <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M3 8h10M9 4l4 4-4 4" />
                  </svg>
                </Link>
              </div>
            )}
          </>
        )}

        {/* Browse by State */}
        <section className="mt-16 border-t border-zinc-200 pt-10 dark:border-zinc-800">
          <h2 className="mb-1 text-lg font-bold text-zinc-900 dark:text-zinc-100">
            {makeEntry.name} Dealers by State
          </h2>
          <p className="mb-5 text-sm text-zinc-500 dark:text-zinc-400">
            Find {makeEntry.name} dealerships near you by state.
          </p>
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {ALL_STATES.map((s) => (
              <Link
                key={s.slug}
                href={`/dealers/state/${s.slug}`}
                className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs font-medium text-zinc-700 hover:border-emerald-300 hover:text-emerald-700 transition-colors dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:border-emerald-700 dark:hover:text-emerald-400"
              >
                {s.name}
              </Link>
            ))}
          </div>
        </section>

        {/* Browse Other Makes */}
        <section className="mt-12 border-t border-zinc-200 pt-10 dark:border-zinc-800">
          <h2 className="mb-1 text-lg font-bold text-zinc-900 dark:text-zinc-100">
            Browse Dealers by Brand
          </h2>
          <p className="mb-5 text-sm text-zinc-500 dark:text-zinc-400">
            Explore dealership directories for other makes.
          </p>
          <div className="flex flex-wrap gap-2">
            {POPULAR_MAKES.map((m) => (
              <Link
                key={m.slug}
                href={`/dealers/make/${m.slug}`}
                className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                  m.slug === makeSlug
                    ? "border-sky-500 bg-sky-600 text-white"
                    : "border-zinc-200 bg-white text-zinc-700 hover:border-sky-300 hover:text-sky-700 hover:bg-sky-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:border-sky-700 dark:hover:text-sky-300"
                }`}
              >
                {m.name}
              </Link>
            ))}
          </div>
        </section>
      </main>
    </>
  );
}
