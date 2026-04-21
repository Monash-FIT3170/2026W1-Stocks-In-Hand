/** @type {import('next').NextConfig} */
module.exports = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://backend:8000/:path*" }]
  }
}
