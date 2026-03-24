import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin Turbopack root when multiple lockfiles exist above this app in the filesystem.
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
