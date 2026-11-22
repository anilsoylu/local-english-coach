import type { NextConfig } from "next";

// Static export: `bun run build` writes out/, which the FastAPI app serves next to /api on the same origin.
// https://nextjs.org/docs/app/guides/static-exports
const nextConfig: NextConfig = {
  output: "export",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
