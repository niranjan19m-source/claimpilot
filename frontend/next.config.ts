import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // This app lives inside another project that has its own lockfile; pin the root here.
  outputFileTracingRoot: process.cwd(),
};

export default nextConfig;
