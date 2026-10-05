import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveApiBaseUrl, resolveDevProxyTarget } from '../src/lib/api-origin.ts';
import { establishBrowserSession } from '../src/lib/browser-session.ts';

for (const base of ['http://localhost:8000', ' http://127.0.0.1:8000/ ', 'http://[::1]:8000']) {
  test(`development keeps ${base.trim()} requests on the website origin`, () => {
    assert.equal(resolveApiBaseUrl(base, true), '');
  });
}

test('an empty API setting uses the proxy with the default local backend', () => {
  assert.equal(resolveApiBaseUrl(undefined, true), '');
  assert.equal(resolveDevProxyTarget(''), 'http://127.0.0.1:8000');
});

test('a legacy custom local API port is preserved behind the proxy', () => {
  assert.equal(resolveApiBaseUrl('http://localhost:8003', true), '');
  assert.equal(resolveDevProxyTarget('http://localhost:8003'), 'http://127.0.0.1:8003');
});

test('an explicit proxy target takes precedence for isolated test/development servers', () => {
  assert.equal(resolveDevProxyTarget('http://localhost:8000', 'http://127.0.0.1:8006/'), 'http://127.0.0.1:8006');
});

test('production and hosted API URLs retain their explicit transport and location', () => {
  assert.equal(resolveApiBaseUrl('http://localhost:8000', false), 'http://localhost:8000');
  assert.equal(resolveApiBaseUrl('https://api.example.edu/', true), 'https://api.example.edu');
  assert.equal(resolveApiBaseUrl('https://api.example.edu/', false), 'https://api.example.edu');
  assert.equal(resolveApiBaseUrl('https://localhost:8000', true), 'https://localhost:8000');
  assert.equal(resolveApiBaseUrl('/backend', true), '/backend');
});

for (const role of ['admin', 'hod', 'teacher', 'exam_controller', 'student']) {
  test(`${role} sign-in waits for the browser cookie before returning an account`, async () => {
    let release;
    const confirmed = new Promise(resolve => { release = resolve; });
    let completed = false;
    const account = { id: `test-${role}`, role };
    const signingIn = establishBrowserSession(async () => account, () => confirmed).then(user => {
      completed = true;
      return user;
    });
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(completed, false);
    release(account);
    assert.deepEqual(await signingIn, account);
  });
}

test('blocked/missing cookies reject sign-in before a role portal can open', async () => {
  await assert.rejects(establishBrowserSession(
    async () => ({ id: 'controller', role: 'exam_controller' }),
    async () => { throw { status: 401, message: 'Not authenticated' }; },
  ), error => error.code === 'SESSION_NOT_ESTABLISHED' && /cookies/i.test(error.message));
});

test('a retained cookie for a different user cannot complete sign-in', async () => {
  await assert.rejects(establishBrowserSession(
    async () => ({ id: 'new-user' }), async () => ({ id: 'old-user' }),
  ), error => error.code === 'SESSION_ACCOUNT_MISMATCH');
});

test('the confirmed session supplies a role changed during sign-in', async () => {
  const user = await establishBrowserSession(
    async () => ({ id: 'same-user', role: 'exam_controller' }),
    async () => ({ id: 'same-user', role: 'teacher' }),
  );
  assert.equal(user.role, 'teacher');
});

test('rejected Google/account exchange does not proceed to session verification', async () => {
  const denied = { status: 403, message: 'This account is disabled' };
  let verified = false;
  await assert.rejects(establishBrowserSession(
    async () => { throw denied; }, async () => { verified = true; return { id: 'unused' }; },
  ), error => error === denied);
  assert.equal(verified, false);
});

for (const status of [0, 403, 503]) {
  test(`session verification preserves a ${status} failure instead of misreporting cookies`, async () => {
    const failure = { status, message: 'Original failure' };
    await assert.rejects(establishBrowserSession(
      async () => ({ id: 'user' }), async () => { throw failure; },
    ), error => error === failure);
  });
}

for (const message of ['Invalid or expired session', 'This account is no longer active']) {
  test(`session verification preserves the backend rejection: ${message}`, async () => {
    const failure = { status: 401, message };
    await assert.rejects(establishBrowserSession(
      async () => ({ id: 'user' }), async () => { throw failure; },
    ), error => error === failure);
  });
}
