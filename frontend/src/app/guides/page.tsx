import Link from "next/link";
import { Metadata } from "next";

import { DirectoryHeader } from "@/components/DirectoryHeader";
import { GUIDES } from "@/lib/guides";

export const metadata: Metadata = {
  title: "Guides & Advice | Motorscrape",
  description: "Expert advice on finding local car deals, tracking dealership inventory, and negotiating the best price.",
  alternates: {
    canonical: "/guides",
  },
};

export default function GuidesIndexPage() {
  return (
    <>
      <DirectoryHeader />
      <main className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-4 py-8 sm:px-6 sm:py-12">
        <header>
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
            Guides &amp; Advice
          </h1>
          <p className="mt-2 text-lg text-zinc-600 dark:text-zinc-400">
            Expert advice on finding local car deals, tracking dealership inventory, and negotiating the best price.
          </p>
        </header>

        <div className="grid gap-6 sm:grid-cols-2">
          {GUIDES.map((guide) => (
            <article
              key={guide.slug}
              className="flex flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm transition hover:border-emerald-300 hover:ring-1 hover:ring-emerald-500/20 dark:border-zinc-800 dark:bg-zinc-950"
            >
              <div className="flex flex-1 flex-col p-5 sm:p-6">
                <time
                  dateTime={guide.publishedAt}
                  className="mb-2 text-xs font-medium text-zinc-500 dark:text-zinc-400"
                >
                  {new Date(guide.publishedAt).toLocaleDateString("en-US", {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })}
                </time>
                <h2 className="mb-3 text-xl font-semibold leading-tight text-zinc-900 dark:text-zinc-50">
                  <Link href={`/guides/${guide.slug}`} className="hover:underline">
                    {guide.title}
                  </Link>
                </h2>
                <p className="mb-4 flex-1 text-sm text-zinc-600 dark:text-zinc-400">
                  {guide.description}
                </p>
                <div className="mt-auto">
                  <Link
                    href={`/guides/${guide.slug}`}
                    className="inline-flex items-center text-sm font-semibold text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
                  >
                    Read guide <span aria-hidden="true" className="ml-1">&rarr;</span>
                  </Link>
                </div>
              </div>
            </article>
          ))}
        </div>
      </main>
    </>
  );
}
