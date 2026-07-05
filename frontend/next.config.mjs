/** @type {import('next').NextConfig} */
const nextConfig = {
  // StrictMode отключён: в dev-режиме он вызывал каждый useEffect дважды →
  // 2× запросов к бэкенду (в логах видно GET /gaps/data парами). На тяжёлых
  // страницах (compare с двумя listEntities) это давало x4. In-flight-дедуп
  // в lib/api.js подстраховывает, но лучше не плодить дубли изначально.
  reactStrictMode: false,
  // Reverse-proxy для API. Браузер шлёт запросы same-origin
  // (относительные пути /api/...), а Next.js внутри контейнера
  // проксирует их на backend:8000. Это ломает зависимость от
  // NEXT_PUBLIC_API_URL — фронт работает и с localhost, и через
  // любой публичный туннель (pinggy, ngrok, cloudflared).
  async rewrites() {
    const backend = process.env.BACKEND_INTERNAL_URL || 'http://backend:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
