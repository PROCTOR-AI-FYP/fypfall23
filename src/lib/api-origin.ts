function loopbackBackend(value: string): URL | null {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      && url.pathname === '/' && !url.search && !url.hash && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

/** Local development goes through Vite so localhost/127.0.0.1 cannot split cookies. */
export function resolveApiBaseUrl(configured: string | undefined, development: boolean): string {
  const base = (configured ?? '').trim().replace(/\/+$/, '');
  return development && loopbackBackend(base) ? '' : base;
}

/** Preserve a configured local API port while keeping browser requests first-party. */
export function resolveDevProxyTarget(configured: string | undefined, override?: string): string {
  if (override?.trim()) return override.trim().replace(/\/+$/, '');
  const local = loopbackBackend((configured ?? '').trim());
  if (!local) return 'http://127.0.0.1:8000';
  // The local launcher binds IPv4; Node may otherwise resolve localhost to ::1.
  if (local.hostname === 'localhost') local.hostname = '127.0.0.1';
  return local.origin;
}
