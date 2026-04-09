/**
 * Resolve API URLs for fetch/EventSource. Supports:
 * - Absolute `NEXT_PUBLIC_API_URL` (e.g. http://localhost:8000)
 * - Same-origin prefix (e.g. /server) with Next.js dev rewrites to FastAPI
 */
export function getApiBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (url) {
    return url.replace(/\/$/, "");
  }
  return "/server";
}

/** Full URL for client-side requests (fetch / EventSource). */
export function resolveApiUrl(path: string): string {
  const base = getApiBaseUrl();
  const p = path.startsWith("/") ? path : `/${path}`;
  if (base.startsWith("http")) {
    return `${base}${p}`;
  }
  if (typeof window !== "undefined") {
    return `${window.location.origin}${base}${p}`;
  }
  return `${base}${p}`;
}
