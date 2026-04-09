import type { NextConfig } from "next";
import path from "node:path";

const workspaceRoot = path.resolve(process.cwd(), "..");

const nextConfig: NextConfig = {
  // Pin Turbopack root when multiple lockfiles exist above this app in the filesystem.
  turbopack: {
    root: workspaceRoot,
  },
  /**
   * Local dev proxies `/server/*` to FastAPI on the workstation.
   * Production should use the co-deployed `/server` service path directly.
   */
  async rewrites() {
    if (process.env.NODE_ENV === "production") {
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
