export function createVercelConfig(env) {
  let backend;
  try {
    backend = new URL((env.PROCTORAI_BACKEND_URL ?? '').trim());
  } catch {
    throw new Error('Set PROCTORAI_BACKEND_URL to the deployed HTTPS backend origin in Vercel.');
  }
  if (backend.protocol !== 'https:' || backend.username || backend.password
      || backend.pathname !== '/' || backend.search || backend.hash
      || ['localhost', '127.0.0.1', '[::1]'].includes(backend.hostname)) {
    throw new Error('PROCTORAI_BACKEND_URL must be a public HTTPS origin without credentials, a path, or a query.');
  }
  if ((env.VITE_API_BASE_URL ?? '').trim()) {
    throw new Error('Leave VITE_API_BASE_URL empty in Vercel so API requests use the first-party session cookie.');
  }

  const noCache = [
    { key: 'Cache-Control', value: 'private, no-store' },
    { key: 'CDN-Cache-Control', value: 'no-store' },
    { key: 'Vercel-CDN-Cache-Control', value: 'no-store' },
    { key: 'x-vercel-enable-rewrite-caching', value: '0' },
  ];
  return {
    framework: 'vite',
    installCommand: 'npm ci',
    buildCommand: 'npm run build',
    outputDirectory: 'dist',
    rewrites: [
      { source: '/api/:path*', destination: `${backend.origin}/api/:path*` },
      { source: '/socket.io/:path*', destination: `${backend.origin}/socket.io/:path*` },
      { source: '/healthz', destination: `${backend.origin}/healthz` },
      // A missing API, asset, or private worker route must never return SPA HTML.
      { source: '/((?!api(?:/|$)|socket\\.io(?:/|$)|assets(?:/|$)|vision(?:/|$)|healthz(?:/|$)|internal(?:/|$)).*)', destination: '/index.html' },
    ],
    headers: [
      { source: '/api/:path*', headers: noCache },
      { source: '/socket.io/:path*', headers: noCache },
      { source: '/healthz', headers: noCache },
      { source: '/assets/:path*', headers: [{ key: 'Cache-Control', value: 'public, max-age=31536000, immutable' }] },
      { source: '/index.html', headers: [{ key: 'Cache-Control', value: 'no-cache' }] },
      { source: '/vision/head.worker.js', headers: [{ key: 'Cache-Control', value: 'no-cache' }] },
    ],
  };
}
