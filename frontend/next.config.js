/** @type {import('next').NextConfig} */
const apiBaseUrl = process.env.INTERNAL_API_URL || "http://localhost:8000"

const nextConfig = {
  trailingSlash: true,
}

// Rewrites need a Next.js server, so keep this local-development convenience
// out of the production static export. CloudFront owns the /api/* routing in AWS.
if (process.env.NODE_ENV === "development") {
  nextConfig.rewrites = async () => [
    { source: "/api/:path*", destination: `${apiBaseUrl}/:path*` },
  ]
} else {
  nextConfig.output = "export"
}

module.exports = nextConfig
