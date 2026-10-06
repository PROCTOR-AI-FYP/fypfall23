import test from 'node:test';
import assert from 'node:assert/strict';
import {runObjectCheck} from '../src/lib/vision/object-check.ts';

const jpeg = new Blob(['recorded-frame'], {type: 'image/jpeg'});
const options = () => ({signal: new AbortController().signal});
function clock() {
  let now = 0;
  const sleeps = [], timers = [];
  return {
    sleeps, timers,
    runtime: {
      now: () => now,
      delay: async (milliseconds, signal) => {
        if (signal.aborted) throw signal.reason;
        sleeps.push(milliseconds); now += milliseconds;
      },
      setTimeout: (callback, milliseconds) => {const timer = {callback, milliseconds, cleared: false}; timers.push(timer); return timer;},
      clearTimeout: timer => {timer.cleared = true;},
    },
    advance: milliseconds => {now += milliseconds;},
  };
}

test('a cold CPU result beyond 45 seconds completes with one upload and short polls', async () => {
  const time = clock(), calls = [], progress = [], result = {objects: [{label: 'cell phone'}], detections: [{id: 'committed'}]};
  const request = async (method, path, opts) => {
    calls.push({method, path, opts});
    if (method === 'POST') return {job_id: 'job-1', state: 'running'};
    return time.runtime.now() >= 60_000 ? {state: 'complete', result} : {state: 'running'};
  };
  assert.deepEqual(await runObjectCheck(request, 'run-1', 17, jpeg, {...options(), runtime: time.runtime, onProgress: value => progress.push(value)}), result);
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(calls[0].opts.rawBody, jpeg);
  assert.deepEqual(calls[0].opts.query, {frame_index: 17});
  assert.ok(calls.filter(call => call.method === 'GET').every(call => call.path.endsWith('/object-jobs/job-1') && !call.opts.rawBody));
  assert.ok(time.sleeps.every(milliseconds => milliseconds >= 500 && milliseconds <= 1000));
  assert.ok(time.timers.every(timer => timer.milliseconds === 10_000 && timer.cleared));
  assert.ok(progress.some(value => value.elapsedMs > 45_000 && value.jobId === 'job-1'));
});

test('room requests keep the mode, frame index, and original JPEG', async () => {
  const time = clock(), calls = [];
  const request = async (...args) => {calls.push(args); return args[0] === 'POST' ? {job_id: 'room-job', state: 'running'} : {state: 'complete', result: {seats: [14, 25]}};};
  const result = await runObjectCheck(request, 'room-run', 3, jpeg, {...options(), mode: 'room', runtime: time.runtime});
  assert.deepEqual(result, {seats: [14, 25]});
  assert.deepEqual(calls[0][2].query, {frame_index: 3, mode: 'room'});
  assert.equal(calls[0][2].rawBody, jpeg);
});

test('network failures retry the same job without submitting another capture', async () => {
  const time = clock(), calls = [], progress = [];
  let polls = 0;
  const request = async (method, path) => {
    calls.push({method, path});
    if (method === 'POST') return {job_id: 'saved-job', state: 'running'};
    polls++;
    if (polls === 1) throw {status: 0, code: 'NETWORK_ERROR', message: 'offline'};
    if (polls === 2) throw new TypeError('Failed to fetch');
    return {state: 'complete', result: {objects: []}};
  };
  assert.deepEqual(await runObjectCheck(request, 'run', 1, jpeg, {...options(), runtime: time.runtime, onProgress: value => progress.push(value)}), {objects: []});
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(new Set(calls.filter(call => call.method === 'GET').map(call => call.path)).size, 1);
  assert.deepEqual(time.sleeps, [750, 1000, 1000]);
  assert.equal(progress.filter(value => value.stage === 'retrying').length, 2);
});

test('a poll timing out after 10 seconds retries the same job and then completes', async () => {
  const time = clock(), calls = [];
  let polls = 0;
  const request = (method, path) => {
    calls.push({method, path});
    if (method === 'POST') return Promise.resolve({job_id: 'slow-poll', state: 'running'});
    if (++polls === 1) {
      queueMicrotask(() => {const timer = time.timers.at(-1); time.advance(timer.milliseconds); timer.callback();});
      return new Promise(() => {});
    }
    return Promise.resolve({state: 'complete', result: 'done'});
  };
  assert.equal(await runObjectCheck(request, 'run', 1, jpeg, {...options(), runtime: time.runtime}), 'done');
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(polls, 2);
  assert.ok(time.timers.every(timer => timer.cleared));
});

test('stop interrupts an in-flight poll and does not start another request', async () => {
  const time = clock(), controller = new AbortController(), calls = [];
  const request = (method, path) => {
    calls.push({method, path});
    if (method === 'POST') return Promise.resolve({job_id: 'job', state: 'running'});
    queueMicrotask(() => controller.abort());
    return new Promise(() => {});
  };
  await assert.rejects(runObjectCheck(request, 'run', 1, jpeg, {signal: controller.signal, runtime: time.runtime}), {name: 'AbortError'});
  assert.equal(calls.length, 2);
  assert.ok(time.timers.every(timer => timer.cleared));
});

test('stop cancels the pending poll delay before the next request', async () => {
  const controller = new AbortController(), time = clock(), calls = [];
  const request = async (method, path) => {calls.push({method, path}); return {job_id: 'job', state: 'running'};};
  const runtime = {...time.runtime, delay: async (_milliseconds, signal) => {controller.abort(); if (signal.aborted) throw signal.reason;}};
  await assert.rejects(runObjectCheck(request, 'run', 1, jpeg, {signal: controller.signal, runtime}), {name: 'AbortError'});
  assert.equal(calls.length, 1);
});

for (const status of [401, 403, 404, 409, 410, 422, 500, 503]) {
  test(`poll failure ${status} preserves the original error and does not fall back or reupload`, async () => {
    const time = clock(), original = {status, message: 'original server reason'}, calls = [];
    const request = async (method, path) => {calls.push({method, path}); if (method === 'POST') return {job_id: 'job', state: 'running'}; throw original;};
    await assert.rejects(runObjectCheck(request, 'run', 1, jpeg, {...options(), runtime: time.runtime}), error => error === original);
    assert.equal(calls.length, 2);
    assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  });
}

for (const mode of [undefined, 'room']) {
  test(`an absent enqueue route falls back once to the ${mode ?? 'single'} legacy endpoint`, async () => {
    const time = clock(), calls = [];
    const request = async (method, path, opts) => {calls.push({method, path, opts}); if (path.endsWith('/object-jobs')) throw {status: 404}; return {legacy: true};};
    assert.deepEqual(await runObjectCheck(request, 'run', 7, jpeg, {...options(), mode, runtime: time.runtime}), {legacy: true});
    assert.equal(calls.length, 2);
    assert.equal(calls[1].path, `/api/device-camera/run${mode ? '/room' : ''}/frame`);
    assert.deepEqual(calls[1].opts.query, {frame_index: 7});
    assert.equal(calls[1].opts.rawBody, jpeg);
  });
}

test('a lost enqueue response is never retried or treated as an older backend', async () => {
  const time = clock(), original = {status: 0, code: 'NETWORK_ERROR'}, calls = [];
  const request = async (...args) => {calls.push(args); throw original;};
  await assert.rejects(runObjectCheck(request, 'run', 1, jpeg, {...options(), runtime: time.runtime}), error => error === original);
  assert.equal(calls.length, 1);
});

test('an enqueue timeout never retries an upload whose acceptance is unknown', async () => {
  const time = clock(); let calls = 0;
  const request = () => {
    calls++;
    queueMicrotask(() => {const timer = time.timers.at(-1); time.advance(timer.milliseconds); timer.callback();});
    return new Promise(() => {});
  };
  await assert.rejects(runObjectCheck(request, 'run', 1, jpeg, {...options(), runtime: time.runtime}), {code: 'NETWORK_TIMEOUT', status: 0});
  assert.equal(calls, 1);
  assert.equal(time.runtime.now(), 10_000);
});

test('HTTP authorization failures cannot be hidden by a misleading network error code', async () => {
  const time = clock(), original = {status: 403, code: 'NETWORK_ERROR', message: 'Assignment removed'};
  let calls = 0;
  const request = async () => {if (++calls === 1) return {job_id: 'job', state: 'running'}; throw original;};
  await assert.rejects(runObjectCheck(request, 'run', 1, jpeg, {...options(), runtime: time.runtime}), error => error === original);
  assert.equal(calls, 2);
});

test('running jobs stop at the overall 180-second bound', async () => {
  const time = clock(), calls = [];
  const request = async (method, path) => {calls.push({method, path}); return {job_id: 'never-ready', state: 'running'};};
  await assert.rejects(runObjectCheck(request, 'run', 1, jpeg, {...options(), runtime: time.runtime}), {code: 'OBJECT_CHECK_TIMEOUT', status: 408});
  assert.equal(time.runtime.now(), 180_000);
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  assert.ok(time.timers.every(timer => timer.cleared));
});

test('a cancelled check never uploads a frame', async () => {
  const controller = new AbortController(); controller.abort();
  const time = clock(); let calls = 0;
  await assert.rejects(runObjectCheck(async () => {calls++;}, 'run', 1, jpeg, {signal: controller.signal, runtime: time.runtime}), {name: 'AbortError'});
  assert.equal(calls, 0);
});

test('invalid accepted job IDs and unknown job states fail without another upload', async () => {
  for (const reply of [{state: 'running'}, {job_id: '', state: 'running'}, {job_id: 'job', state: 'failed'}]) {
    const time = clock(); let calls = 0;
    await assert.rejects(runObjectCheck(async () => {calls++; return reply;}, 'run', 1, jpeg, {...options(), runtime: time.runtime}), {code: 'INVALID_RESPONSE', status: 502});
    assert.equal(calls, 1);
  }
});
