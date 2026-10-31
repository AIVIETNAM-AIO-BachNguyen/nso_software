/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  distDir: process.env.NSO_NEXT_DIST_DIR || ".next",
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${process.env.NSO_API_BASE || "http://127.0.0.1:8000"}/:path*` }];
  },
};
module.exports = nextConfig;
