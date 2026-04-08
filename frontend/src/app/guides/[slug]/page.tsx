import { notFound } from "next/navigation";
import { Metadata } from "next";

import { DirectoryHeader } from "@/components/DirectoryHeader";
import { JsonLd } from "@/components/seo/JsonLd";
import { getGuideBySlug, GUIDES } from "@/lib/guides";

type Props = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const decodedSlug = decodeURIComponent(slug);
  const guide = getGuideBySlug(decodedSlug);

  if (!guide) {
    return { title: "Not Found" };
  }

  return {
    title: `${guide.title} | Motorscrape Guides`,
    description: guide.description,
    alternates: {
      canonical: `/guides/${guide.slug}`,
    },
    openGraph: {
      title: guide.title,
      description: guide.description,
      type: "article",
      publishedTime: guide.publishedAt,
      authors: [guide.author],
    },
  };
}

export async function generateStaticParams() {
  return GUIDES.map((guide) => ({
    slug: guide.slug,
  }));
}

export default async function GuidePage({ params }: Props) {
  const { slug } = await params;
  const decodedSlug = decodeURIComponent(slug);
  const guide = getGuideBySlug(decodedSlug);

  if (!guide) {
    notFound();
  }

  const articleSchema = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: guide.title,
    description: guide.description,
    author: {
      "@type": "Organization",
      name: guide.author,
    },
    publisher: {
      "@type": "Organization",
      name: "Motorscrape",
      logo: {
        "@type": "ImageObject",
        url: "https://www.motorscrape.com/favicon.ico",
      },
    },
    datePublished: guide.publishedAt,
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": `https://www.motorscrape.com/guides/${guide.slug}`,
    },
  };

  return (
    <>
      <JsonLd data={articleSchema} />
      <DirectoryHeader />
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-8 sm:px-6 sm:py-12">
        <article className="prose prose-zinc max-w-none dark:prose-invert prose-headings:font-semibold prose-a:text-emerald-600 hover:prose-a:text-emerald-500 dark:prose-a:text-emerald-400">
          <header className="not-prose mb-10 border-b border-zinc-200 pb-8 dark:border-zinc-800">
            <time
              dateTime={guide.publishedAt}
              className="mb-4 block text-sm font-medium text-zinc-500 dark:text-zinc-400"
            >
              {new Date(guide.publishedAt).toLocaleDateString("en-US", {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </time>
            <h1 className="mb-4 text-3xl font-bold tracking-tight text-zinc-900 sm:text-4xl dark:text-zinc-50">
              {guide.title}
            </h1>
            <p className="text-xl text-zinc-600 dark:text-zinc-400">
              {guide.description}
            </p>
          </header>

          <div
            className="whitespace-pre-wrap"
            dangerouslySetInnerHTML={{
              __html: guide.content
                .replace(/^## (.*$)/gim, "<h2>$1</h2>")
                .replace(/^\* (.*$)/gim, "<li>$1</li>")
                .replace(/(<li>[\s\S]*<\/li>)/m, "<ul>$1</ul>"),
            }}
          />
        </article>
      </main>
    </>
  );
}
