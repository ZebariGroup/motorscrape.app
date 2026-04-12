import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";

import { DirectoryHeader } from "@/components/DirectoryHeader";
import { fetchDealerBySlug, type DealerHours } from "@/lib/dealerApi";

type Props = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const dealer = await fetchDealerBySlug(slug);
  if (!dealer) return { title: "Dealer Not Found" };

  const brands = dealer.oem_brands.length > 0 ? dealer.oem_brands.slice(0, 3).join(", ") : "Auto";
  const city = dealer.address.split(",")[0]?.trim() ?? "";

  return {
    title: `${dealer.name} | ${brands} Dealership${city ? ` in ${city}` : ""}`,
    description:
      dealer.description ??
      `Browse inventory, hours, and details for ${dealer.name}${city ? ` in ${city}` : ""}. Verified by Motorscrape.`,
    alternates: { canonical: `/dealers/${slug}` },
    openGraph: {
      title: dealer.name,
      description: dealer.description ?? `${dealer.name} — dealership directory on Motorscrape`,
      type: "website",
    },
  };
}

// ─── Small UI atoms ───────────────────────────────────────────────────────────

function StarRating({ rating }: { rating: number }) {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  return (
    <span className="flex items-center gap-0.5" aria-label={`${rating} out of 5 stars`}>
      {Array.from({ length: 5 }, (_, i) => {
        const filled = i < full;
        const isHalf = !filled && i === full && half;
        return (
          <svg
            key={i}
            viewBox="0 0 20 20"
            className={`h-4 w-4 ${filled || isHalf ? "text-amber-400" : "text-zinc-300 dark:text-zinc-600"}`}
            fill="currentColor"
            aria-hidden
          >
            {isHalf ? (
              <>
                <defs>
                  <linearGradient id="half-star">
                    <stop offset="50%" stopColor="currentColor" />
                    <stop offset="50%" stopColor="transparent" />
                  </linearGradient>
                </defs>
                <path
                  fill="url(#half-star)"
                  d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"
                />
              </>
            ) : (
              <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
            )}
          </svg>
        );
      })}
    </span>
  );
}

function ServiceBadge({ service }: { service: string }) {
  const labels: Record<string, string> = {
    new: "New Vehicles",
    used: "Used Vehicles",
    cpo: "Certified Pre-Owned",
    finance: "Finance Center",
    service_center: "Service Center",
    parts: "Parts Dept.",
  };
  return (
    <span className="inline-flex items-center rounded-full border border-zinc-200 bg-white px-3 py-1 text-xs font-medium text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
      {labels[service] ?? service}
    </span>
  );
}

function OemBadge({ brand }: { brand: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700 dark:bg-blue-950/50 dark:text-blue-300">
      {brand}
    </span>
  );
}

function HoursBlock({ hours }: { hours: DealerHours }) {
  const lines = hours.weekdayDescriptions ?? [];
  if (lines.length === 0) return null;
  const today = new Date().getDay(); // 0 = Sunday
  return (
    <ul className="space-y-1 text-sm">
      {lines.map((line, i) => {
        // Google: index 0 = Monday, so shift: today=0(Sun)→i=6, today=1(Mon)→i=0
        const dayIdx = (today + 6) % 7;
        const isToday = i === dayIdx;
        return (
          <li
            key={i}
            className={`flex justify-between gap-4 ${
              isToday
                ? "font-semibold text-zinc-900 dark:text-zinc-50"
                : "text-zinc-600 dark:text-zinc-400"
            }`}
          >
            <span>{line.split(":")[0]}</span>
            <span>{line.split(":").slice(1).join(":").trim()}</span>
          </li>
        );
      })}
    </ul>
  );
}

function SocialLink({ platform, url }: { platform: string; url: string }) {
  const icons: Record<string, string> = {
    facebook: "f",
    instagram: "ig",
    twitter: "𝕏",
    youtube: "▶",
    yelp: "★",
    dealerrater: "dr",
    carscom: "c",
  };
  const labels: Record<string, string> = {
    facebook: "Facebook",
    instagram: "Instagram",
    twitter: "X / Twitter",
    youtube: "YouTube",
    yelp: "Yelp",
    dealerrater: "DealerRater",
    carscom: "Cars.com",
  };
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:border-zinc-300 hover:text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-100"
    >
      <span aria-hidden className="text-xs font-bold">{icons[platform] ?? platform}</span>
      {labels[platform] ?? platform}
    </a>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900/60">
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">{value}</p>
    </div>
  );
}

function formatPrice(n: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function DealerPage({ params }: Props) {
  const { slug } = await params;
  const dealer = await fetchDealerBySlug(slug);
  if (!dealer) notFound();

  const mapsUrl = `https://maps.google.com/?q=${encodeURIComponent(dealer.address)}`;
  const searchUrl = `/?location=${encodeURIComponent(dealer.address)}&${dealer.oem_brands[0] ? `make=${encodeURIComponent(dealer.oem_brands[0])}` : ""}`;

  const hasSocialLinks = dealer.social_links && Object.keys(dealer.social_links).length > 0;
  const hasHours = Boolean(dealer.hours_json?.weekdayDescriptions?.length);
  const hasStats = dealer.stats.scrape_count > 0;
  const heroPhotoRef = dealer.photo_refs?.[0]?.name ?? null;
  const hasMap = dealer.lat != null && dealer.lng != null;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "AutoDealer",
    name: dealer.name,
    address: {
      "@type": "PostalAddress",
      streetAddress: dealer.address,
    },
    ...(dealer.lat && dealer.lng
      ? { geo: { "@type": "GeoCoordinates", latitude: dealer.lat, longitude: dealer.lng } }
      : {}),
    ...(dealer.phone ? { telephone: dealer.phone } : {}),
    ...(dealer.website ? { url: dealer.website } : {}),
    ...(dealer.rating
      ? {
          aggregateRating: {
            "@type": "AggregateRating",
            ratingValue: dealer.rating,
            reviewCount: dealer.review_count ?? 1,
          },
        }
      : {}),
  };

  return (
    <>
      <DirectoryHeader />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <main className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 py-8 sm:px-6 sm:py-12">
        {/* Breadcrumb */}
        <nav className="flex items-center gap-1.5 text-sm text-zinc-500 dark:text-zinc-400" aria-label="Breadcrumb">
          <Link href="/" className="hover:text-zinc-700 dark:hover:text-zinc-200">Home</Link>
          <span>/</span>
          <Link href="/dealers" className="hover:text-zinc-700 dark:hover:text-zinc-200">Dealers</Link>
          <span>/</span>
          <span className="text-zinc-700 dark:text-zinc-300 truncate">{dealer.name}</span>
        </nav>

        {/* Hero photo */}
        {heroPhotoRef && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`/server/dealerships/photo?ref=${encodeURIComponent(heroPhotoRef)}&max_width=1200`}
            alt={`${dealer.name} dealership`}
            className="w-full h-52 rounded-2xl object-cover sm:h-72"
            loading="eager"
          />
        )}

        {/* Header */}
        <header className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-3xl">
                {dealer.name}
              </h1>
              {dealer.oem_brands.length > 0 && (
                <p className="mt-1 text-base text-zinc-500 dark:text-zinc-400">
                  {dealer.oem_brands.slice(0, 4).join(" · ")} Dealer
                </p>
              )}
            </div>

            {/* Verified badge */}
            {hasStats && (
              <span className="shrink-0 inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-800">
                <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" aria-hidden>
                  <circle cx="8" cy="8" r="7.5" stroke="currentColor" strokeWidth="1" />
                  <path d="M5 8l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Verified · {dealer.stats.scrape_count} scrape{dealer.stats.scrape_count !== 1 ? "s" : ""}
              </span>
            )}
          </div>

          {/* Rating */}
          {dealer.rating != null && (
            <div className="flex items-center gap-2">
              <StarRating rating={dealer.rating} />
              <span className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">{dealer.rating.toFixed(1)}</span>
              {dealer.review_count != null && (
                <span className="text-sm text-zinc-500 dark:text-zinc-400">
                  ({dealer.review_count.toLocaleString()} Google reviews)
                </span>
              )}
            </div>
          )}

          {/* Description */}
          {dealer.description && (
            <p className="text-base text-zinc-600 dark:text-zinc-400 max-w-2xl">{dealer.description}</p>
          )}

          {/* Brand + service chips */}
          {(dealer.oem_brands.length > 0 || dealer.services.length > 0) && (
            <div className="flex flex-wrap gap-2">
              {dealer.oem_brands.map((b) => <OemBadge key={b} brand={b} />)}
              {dealer.services.map((s) => <ServiceBadge key={s} service={s} />)}
            </div>
          )}
        </header>

        {/* Main grid */}
        <div className="grid gap-8 lg:grid-cols-3">
          {/* Left: contact + hours + social */}
          <div className="flex flex-col gap-6 lg:col-span-1">
            {/* Contact card */}
            <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Contact & Location
              </h2>
              <div className="space-y-3 text-sm">
                <div>
                  <p className="text-zinc-700 dark:text-zinc-300">{dealer.address}</p>
                  <a
                    href={mapsUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mt-1 inline-flex items-center gap-1 text-xs text-blue-600 hover:underline dark:text-blue-400"
                  >
                    Get Directions
                    <svg viewBox="0 0 11 11" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                      <path d="M4.5 2.5H2a1 1 0 00-1 1v6a1 1 0 001 1h6a1 1 0 001-1V7M7 1h3m0 0v3M10 1L5.5 5.5" />
                    </svg>
                  </a>
                </div>

                {dealer.phone && (
                  <div>
                    <a
                      href={`tel:${dealer.phone}`}
                      className="font-medium text-zinc-900 hover:text-blue-600 dark:text-zinc-100 dark:hover:text-blue-400"
                    >
                      {dealer.phone}
                    </a>
                  </div>
                )}

                {dealer.website && (
                  <div>
                    <a
                      href={dealer.website}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="truncate text-blue-600 hover:underline dark:text-blue-400"
                    >
                      {new URL(dealer.website).hostname.replace(/^www\./, "")}
                    </a>
                  </div>
                )}
              </div>
            </section>

            {/* Hours */}
            {hasHours && (
              <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
                <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                  Business Hours
                </h2>
                <HoursBlock hours={dealer.hours_json!} />
              </section>
            )}

            {/* Social links */}
            {hasSocialLinks && (
              <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
                <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                  Online Presence
                </h2>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(dealer.social_links ?? {}).map(([platform, url]) =>
                    url ? <SocialLink key={platform} platform={platform} url={url} /> : null
                  )}
                </div>
              </section>
            )}

            {/* Map */}
            {hasMap && (
              <section className="overflow-hidden rounded-2xl border border-zinc-200 shadow-sm dark:border-zinc-800">
                <iframe
                  title={`Map showing location of ${dealer.name}`}
                  src={`https://www.google.com/maps?q=${dealer.lat},${dealer.lng}&output=embed&z=15`}
                  className="h-52 w-full"
                  loading="lazy"
                  referrerPolicy="no-referrer-when-downgrade"
                />
              </section>
            )}
          </div>

          {/* Right: inventory stats + CTA */}
          <div className="flex flex-col gap-6 lg:col-span-2">
            {/* Activity stats */}
            {hasStats && (
              <section>
                <h2 className="mb-4 text-base font-semibold text-zinc-900 dark:text-zinc-50">
                  Inventory Insights
                </h2>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {dealer.stats.scrape_count > 0 && (
                    <StatCard label="Times Scraped" value={dealer.stats.scrape_count.toString()} />
                  )}
                  {dealer.stats.last_scraped_at && (
                    <StatCard label="Last Seen" value={formatDate(dealer.stats.last_scraped_at)} />
                  )}
                  {dealer.stats.price_median != null && (
                    <StatCard label="Median Price" value={formatPrice(dealer.stats.price_median)} />
                  )}
                  {dealer.stats.price_min != null && (
                    <StatCard label="Lowest Price Seen" value={formatPrice(dealer.stats.price_min)} />
                  )}
                </div>

                {dealer.stats.makes_in_inventory.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                      Makes in Inventory History
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {dealer.stats.makes_in_inventory.map((make) => (
                        <span
                          key={make}
                          className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                        >
                          {make}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            )}

            {/* Makes from dealership_makes */}
            {dealer.makes.length > 0 && (
              <section>
                <h2 className="mb-3 text-base font-semibold text-zinc-900 dark:text-zinc-50">
                  Brands Carried
                </h2>
                <div className="flex flex-wrap gap-2">
                  {dealer.makes.map((m) => (
                    <Link
                      key={`${m.make}-${m.category}`}
                      href={`/?make=${encodeURIComponent(m.make)}&location=${encodeURIComponent(dealer.address)}`}
                      className="rounded-full bg-zinc-100 px-3 py-1 text-sm font-medium text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                    >
                      {m.make}
                    </Link>
                  ))}
                </div>
              </section>
            )}

            {/* CTA */}
            <section className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-6 dark:border-emerald-900/50 dark:bg-emerald-950/20">
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
                Browse This Dealer&apos;s Inventory
              </h2>
              <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                Run a live scrape to see current vehicles available at {dealer.name}.
              </p>
              <Link
                href={searchUrl}
                className="mt-4 inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-600"
              >
                Search Inventory
                <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M3 8h10M9 4l4 4-4 4" />
                </svg>
              </Link>
            </section>

            {/* Google Maps review link */}
            {dealer.rating != null && dealer.place_id && (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                Ratings sourced from Google.{" "}
                <a
                  href={`https://search.google.com/local/reviews?placeid=${dealer.place_id}`}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-blue-600 hover:underline dark:text-blue-400"
                >
                  Read reviews on Google
                </a>
                {dealer.social_links?.yelp && (
                  <>
                    {" or "}
                    <a
                      href={dealer.social_links.yelp}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="text-blue-600 hover:underline dark:text-blue-400"
                    >
                      Yelp
                    </a>
                  </>
                )}
                {dealer.social_links?.dealerrater && (
                  <>
                    {" or "}
                    <a
                      href={dealer.social_links.dealerrater}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="text-blue-600 hover:underline dark:text-blue-400"
                    >
                      DealerRater
                    </a>
                  </>
                )}
                .
              </p>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
