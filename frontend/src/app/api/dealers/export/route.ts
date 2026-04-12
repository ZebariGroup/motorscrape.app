import { NextRequest, NextResponse } from "next/server";

function serverApiBase(): string {
  const origin = process.env.MOTORSCRAPE_API_ORIGIN?.replace(/\/$/, "");
  if (origin) return origin;
  const vercelUrl = process.env.VERCEL_URL;
  if (vercelUrl) return `https://${vercelUrl}`;
  return "http://127.0.0.1:8000";
}

function escapeCSVField(value: string | null | undefined): string {
  if (value == null) return "";
  const str = String(value);
  if (str.includes(",") || str.includes('"') || str.includes("\n")) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const base = serverApiBase();

  // Forward the session cookie to verify authentication
  const cookieHeader = request.headers.get("cookie") ?? "";
  const authRes = await fetch(`${base}/server/auth/me`, {
    headers: { cookie: cookieHeader },
    cache: "no-store",
  });

  if (!authRes.ok) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { searchParams } = request.nextUrl;
  const make = searchParams.get("make") ?? undefined;
  const state = searchParams.get("state") ?? undefined;
  const q = searchParams.get("q") ?? undefined;

  // Paginate through all dealers (backend limit is 100 per page)
  const pageSize = 100;
  const allDealers: Record<string, unknown>[] = [];
  let offset = 0;
  let total = Infinity;

  while (allDealers.length < total && allDealers.length < 5000) {
    const qs = new URLSearchParams();
    if (make) qs.set("make", make);
    if (state) qs.set("state", state);
    if (q) qs.set("q", q);
    qs.set("limit", String(pageSize));
    qs.set("offset", String(offset));
    qs.set("sort", "rating_desc");

    const res = await fetch(`${base}/server/dealerships?${qs}`, {
      cache: "no-store",
    });

    if (!res.ok) break;

    const data = (await res.json()) as {
      dealers: Record<string, unknown>[];
      total: number;
    };

    const batch = data.dealers ?? [];
    allDealers.push(...batch);
    total = data.total ?? 0;
    offset += pageSize;

    if (batch.length < pageSize) break;
  }

  // Build CSV
  const headers = ["Name", "Address", "Phone", "Website", "Rating", "Review Count", "Brands"];
  const rows = allDealers.map((d) => [
    escapeCSVField(d.name as string),
    escapeCSVField(d.address as string),
    escapeCSVField(d.phone as string),
    escapeCSVField(d.website as string),
    d.rating != null ? String(d.rating) : "",
    d.review_count != null ? String(d.review_count) : "",
    escapeCSVField(Array.isArray(d.oem_brands) ? (d.oem_brands as string[]).join("; ") : ""),
  ]);

  const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");

  const parts = [make && `${make}-`, state && `${state}-`, "dealers"].filter(Boolean).join("");
  const filename = `${parts || "dealers"}-export.csv`;

  return new NextResponse(csv, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${filename}"`,
      "Cache-Control": "no-store",
    },
  });
}
