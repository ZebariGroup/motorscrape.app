import type { NextConfig } from "next";
import path from "node:path";

const workspaceRoot = path.resolve(process.cwd(), "..");

const nextConfig: NextConfig = {
  // Pin Turbopack root when multiple lockfiles exist above this app in the filesystem.
  turbopack: {
    root: workspaceRoot,
  },
  /**
   * Local dev: proxy `/server/*` to FastAPI so the browser stays same-origin with Next
   * (cookies + EventSource). On Vercel Services, `/server` is routed to the Python
   * service — do not rewrite.
   */
  async rewrites() {
    if (process.env.VERCEL) {
      return [];
    }
    const target = (process.env.MOTORSCRAPE_API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/$/, "");
    return [
      {
        source: "/server/:path*",
        destination: `${target}/server/:path*`,
      },
    ];
  },
};

export default nextConfig;
