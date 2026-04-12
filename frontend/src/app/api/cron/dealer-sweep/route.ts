import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  // Vercel automatically injects CRON_SECRET and sends it as
  // "Authorization: Bearer {CRON_SECRET}" on cron-triggered requests.
  const cronSecret = process.env.CRON_SECRET;
  const authHeader = request.headers.get("authorization");
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const sweepSecret = process.env.DEALER_SWEEP_SECRET;
  if (!sweepSecret) {
    return NextResponse.json(
      { error: "DEALER_SWEEP_SECRET is not configured" },
      { status: 500 },
    );
  }

  // In Vercel Services deployments the backend runs at /server on the same
  // domain. VERCEL_PROJECT_PRODUCTION_URL is stable across deploys;
  // VERCEL_URL is deployment-specific. For local dev we fall back to the
  // FastAPI dev server via MOTORSCRAPE_API_ORIGIN.
  const host =
    process.env.VERCEL_PROJECT_PRODUCTION_URL ?? process.env.VERCEL_URL ?? null;
  const backendBase = host
    ? `https://${host}/server`
    : (process.env.MOTORSCRAPE_API_ORIGIN ?? "http://127.0.0.1:8000");
  const url = `${backendBase}/admin/dealer-sweep/run?max_pairs=25`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "x-sweep-secret": sweepSecret,
      "Content-Type": "application/json",
    },
    cache: "no-store",
  });

  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.ok ? 200 : res.status });
}
