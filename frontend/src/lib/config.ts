/**
 * API base for EventSource / fetch.
 * - Vercel Services: set `NEXT_PUBLIC_API_URL` to the API route prefix (often auto-injected as `/server` when the Python service is named `api`).
 * - Local: leave unset to use http://localhost:8000, or point to a remote URL.
 */
export function getApiBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (url) {
    return url.replace(/\/$/, "");
  }
  return "http://localhost:8000";
}
