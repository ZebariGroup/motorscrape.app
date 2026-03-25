import { NextRequest, NextResponse } from "next/server";

import { buildLocationLabelFromNominatimAddress } from "@/lib/reverseGeocodeLabel";

const NOMINATIM = "https://nominatim.openstreetmap.org/reverse";

export async function GET(req: NextRequest) {
  const latRaw = req.nextUrl.searchParams.get("lat");
  const lonRaw = req.nextUrl.searchParams.get("lon");
  const lat = Number.parseFloat(latRaw ?? "");
  const lon = Number.parseFloat(lonRaw ?? "");

  if (
    !Number.isFinite(lat) ||
    !Number.isFinite(lon) ||
    lat < -90 ||
    lat > 90 ||
    lon < -180 ||
    lon > 180
  ) {
    return NextResponse.json({ error: "Invalid coordinates" }, { status: 400 });
  }

  const url = new URL(NOMINATIM);
  url.searchParams.set("lat", String(lat));
  url.searchParams.set("lon", String(lon));
  url.searchParams.set("format", "json");
  url.searchParams.set("addressdetails", "1");

  let res: Response;
  try {
    res = await fetch(url.toString(), {
      headers: {
        Accept: "application/json",
        "User-Agent": "Motorscrape/1.0 (https://www.motorscrape.com)",
      },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "Geocoding request failed" }, { status: 502 });
  }

  if (!res.ok) {
    return NextResponse.json({ error: "Geocoding service error" }, { status: 502 });
  }

  let data: unknown;
  try {
    data = await res.json();
  } catch {
    return NextResponse.json({ error: "Invalid geocoding response" }, { status: 502 });
  }

  if (!data || typeof data !== "object" || !("address" in data)) {
    return NextResponse.json({ error: "No address in response" }, { status: 502 });
  }

  const addr = (data as { address?: Record<string, string> }).address;
  const label = buildLocationLabelFromNominatimAddress(addr);
  if (!label || label.trim().length < 2) {
    return NextResponse.json({ error: "Could not derive location label" }, { status: 502 });
  }

  return NextResponse.json({ label: label.trim() });
}
