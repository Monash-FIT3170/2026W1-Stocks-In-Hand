/** @type {import('next').NextConfig} */
const apiBaseUrl = process.env.INTERNAL_API_URL || "http://localhost:8000"

module.exports = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiBaseUrl}/:path*` }]
  }
}
