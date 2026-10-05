import assert from 'node:assert/strict';
import test from 'node:test';
import { createVercelConfig } from '../scripts/vercel-config.mjs';

test('hosted API and Socket.IO routes preserve the backend paths before the SPA fallback', () => {
  const config = createVercelConfig({ PROCTORAI_BACKEND_URL: 'https://api.example.org/' });
  assert.deepEqual(config.rewrites.slice(0, 3), [
    { source: '/api/:path*', destination: 'https://api.example.org/api/:path*' },
    { source: '/socket.io/:path*', destination: 'https://api.example.org/socket.io/:path*' },
    { source: '/healthz', destination: 'https://api.example.org/healthz' },
  ]);
  const fallback = new RegExp(`^${config.rewrites.at(-1).source}$`);
  for (const route of ['/login', '/teacher/session-setup', '/exam-controller', '/']) assert.ok(fallback.test(route), route);
  for (const route of ['/api', '/api/auth/me', '/socket.io/', '/assets/missing.js', '/internal/detections', '/healthz']) assert.ok(!fallback.test(route), route);
});

test('authenticated responses are never cached but versioned static assets can be', () => {
  const config = createVercelConfig({ PROCTORAI_BACKEND_URL: 'https://api.example.org' });
  for (const route of ['/api/:path*', '/socket.io/:path*']) {
    const headers = Object.fromEntries(config.headers.find(rule => rule.source === route).headers.map(header => [header.key, header.value]));
    assert.equal(headers['Cache-Control'], 'private, no-store');
    assert.equal(headers['Vercel-CDN-Cache-Control'], 'no-store');
  }
});

for (const origin of ['', 'http://api.example.org', 'https://localhost', 'https://127.0.0.1', 'https://[::1]', 'https://user:secret@api.example.org', 'https://api.example.org/api', 'https://api.example.org/?key=secret', 'https://api.example.org/#path']) {
  test(`reject unusable backend configuration: ${origin.replace('secret', 'redacted')}`, () => {
    assert.throws(() => createVercelConfig({ PROCTORAI_BACKEND_URL: origin }), /PROCTORAI_BACKEND_URL/);
  });
}

test('cross-site and localhost frontend API overrides cannot bypass the hosted cookie proxy', () => {
  assert.throws(() => createVercelConfig({ PROCTORAI_BACKEND_URL: 'https://api.example.org', VITE_API_BASE_URL: 'http://localhost:8000' }), /VITE_API_BASE_URL/);
});
