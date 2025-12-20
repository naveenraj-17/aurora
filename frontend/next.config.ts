import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  async rewrites() {
    return [
      // /api/chat is now handled by src/app/api/chat/route.ts
      // {
      //   source: '/api/chat',
      //   destination: 'http://127.0.0.1:8000/chat',
      // },
      {
        source: '/auth/:path*',
        destination: 'http://127.0.0.1:8000/auth/:path*',
      },
      {
        source: '/api/file',
        destination: 'http://127.0.0.1:8000/api/file',
      },
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/api/:path*',
      },
    ];
  },
};

export default nextConfig;
