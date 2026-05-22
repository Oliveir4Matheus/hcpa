import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  experimental: {
    typedRoutes: true,
  },
  // proxy /api/* → API real. Mantém browser e API na MESMA origem,
  // o que faz a cookie de sessão (SameSite=lax) viajar sem fricção.
  // Destination hardcoded porque rewrites do Next 15 são resolvidos em
  // build-time; env vars do compose só existem em runtime. `api` é o
  // nome do service em docker-compose.yml e docker-compose.prod.yml.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://api:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
