import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { JsonLd } from "@/components/seo/JsonLd";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://www.motorscrape.com"),
  title: {
    default: "Motorscrape | Local Dealership Inventory, One Place",
    template: "%s | Motorscrape",
  },
  description:
    "Local dealership inventory, one place. Search nearby dealer websites for real vehicle inventory across brands and stores in one streamlined experience.",
  keywords: [
    "dealer inventory search",
    "local dealership inventory",
    "car inventory search",
    "new car inventory",
    "used car inventory",
    "dealer website inventory",
    "Motorscrape",
  ],
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "Motorscrape | Local Dealership Inventory, One Place",
    description:
      "We crawl so you can drive. Search nearby dealer websites for real vehicle inventory in one place.",
    url: "https://www.motorscrape.com",
    siteName: "Motorscrape",
    locale: "en_US",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Motorscrape | Local Dealership Inventory, One Place",
    description:
      "We crawl so you can drive. Search nearby dealer websites for real vehicle inventory in one place.",
  },
  robots: {
    index: true,
    follow: true,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const websiteSchema = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "Motorscrape",
    url: "https://www.motorscrape.com",
    description: "Search nearby dealer websites for real vehicle inventory across brands and stores in one streamlined experience.",
    potentialAction: {
      "@type": "SearchAction",
      target: "https://www.motorscrape.com/?location={search_term_string}",
      "query-input": "required name=search_term_string"
    }
  };

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <JsonLd data={websiteSchema} />
        {children}
      </body>
    </html>
  );
}
