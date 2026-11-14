import type { NextConfig } from "next";

const snapshot = process.env.NEXT_PUBLIC_SNAPSHOT === "1";

const nextConfig: NextConfig = {
  // This app lives inside another project that has its own lockfile; pin the root here.
  outputFileTracingRoot: process.cwd(),
  // Hosted read-only demo: a static export served from GitHub Pages.
  ...(snapshot && {
    output: "export",
    basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
    trailingSlash: true,
    images: { unoptimized: true },
  }),
};

export default nextConfig;
