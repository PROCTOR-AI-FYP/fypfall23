/** Keep slow model work off the lifetime of a single browser HTTP request. */
export interface ObjectCheckRequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
  rawBody?: Blob;
  signal?: AbortSignal;
}

export type ObjectCheckRequest = <T>(
  method: string,
  path: string,
  options?: ObjectCheckRequestOptions,
) => Promise<T>;

export interface ObjectCheckProgress {
  stage: 'uploading' | 'waiting' | 'retrying' | 'legacy';
  elapsedMs: number;
  jobId?: string;
}

/** Runtime overrides keep retry and cancellation tests independent of wall time. */
export interface ObjectCheckRuntime {
  now: () => number;
  delay: (milliseconds: number, signal: AbortSignal) => Promise<void>;
  setTimeout: (callback: () => void, milliseconds: number) => unknown;
  clearTimeout: (timer: unknown) => void;
}

export interface ObjectCheckOptions {
  signal: AbortSignal;
  mode?: 'room';
  onProgress?: (progress: ObjectCheckProgress) => void;
  runtime?: Partial<ObjectCheckRuntime>;
}

type JobReply<T> = {job_id?: string; state: 'running'} | {job_id?: string; state: 'complete'; result: T};
const REQUEST_TIMEOUT_MS = 10_000;
const CHECK_TIMEOUT_MS = 180_000;
const POLL_INTERVAL_MS = 750;
const RETRY_INTERVAL_MS = 1_000;

function cancelled(signal: AbortSignal): Error {
  return signal.reason instanceof Error ? signal.reason : new DOMException('Object check cancelled.', 'AbortError');
}

function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(cancelled(signal)); return; }
    const finish = () => { signal.removeEventListener('abort', abort); resolve(); };
    const timer = setTimeout(finish, milliseconds);
    const abort = () => { clearTimeout(timer); signal.removeEventListener('abort', abort); reject(cancelled(signal)); };
    signal.addEventListener('abort', abort, {once: true});
  });
}

function statusOf(error: unknown): number | undefined {
  return typeof error === 'object' && error !== null && 'status' in error && typeof error.status === 'number'
    ? error.status : undefined;
}

function transient(error: unknown): boolean {
  const status = statusOf(error);
  if (status !== undefined) return status === 0;
  if (typeof error === 'object' && error !== null) {
    const code = 'code' in error ? error.code : undefined;
    if (code === 'NETWORK_ERROR' || code === 'NETWORK_TIMEOUT') return true;
  }
  // Native fetch can throw TypeError; the API client normally supplies status 0.
  return error instanceof TypeError;
}

function checkTimeout(): Error & {code: string; status: number} {
  return Object.assign(new Error('Object detection took too long to finish. Check the server status and try again.'),
    {code: 'OBJECT_CHECK_TIMEOUT', status: 408});
}

function invalidReply(): Error & {code: string; status: number} {
  return Object.assign(new Error('The server returned an invalid object-check response.'),
    {code: 'INVALID_RESPONSE', status: 502});
}

/**
 * Upload once, then read that same job until the server commits its result.
 * A lost poll can be retried safely; a lost upload must never submit the JPEG twice.
 */
export async function runObjectCheck<T>(
  request: ObjectCheckRequest,
  runId: string,
  frameIndex: number,
  jpeg: Blob,
  options: ObjectCheckOptions,
): Promise<T> {
  const {signal, mode, onProgress} = options;
  const runtime: ObjectCheckRuntime = {
    now: () => Date.now(),
    delay: abortableDelay,
    setTimeout: (callback, milliseconds) => setTimeout(callback, milliseconds),
    clearTimeout: timer => clearTimeout(timer as ReturnType<typeof setTimeout>),
    ...options.runtime,
  };
  const started = runtime.now();
  const base = `/api/device-camera/${encodeURIComponent(runId)}`;
  let jobId: string | undefined;
  const remaining = () => {
    if (signal.aborted) throw cancelled(signal);
    const budget = CHECK_TIMEOUT_MS - Math.max(0, runtime.now() - started);
    if (budget <= 0) throw checkTimeout();
    return budget;
  };
  const progress = (stage: ObjectCheckProgress['stage']) => {
    onProgress?.({stage, elapsedMs: Math.max(0, runtime.now() - started), ...(jobId ? {jobId} : {})});
  };
  const fetchWithin = async <R>(method: string, path: string, requestOptions: ObjectCheckRequestOptions, limit = REQUEST_TIMEOUT_MS): Promise<R> => {
    const budget = Math.min(limit, remaining());
    const controller = new AbortController();
    const timeoutError = Object.assign(new Error('Object-check request timed out.'),
      {name: 'TimeoutError', code: 'NETWORK_TIMEOUT', status: 0});
    const abort = () => controller.abort(cancelled(signal));
    signal.addEventListener('abort', abort, {once: true});
    const timer = runtime.setTimeout(() => controller.abort(timeoutError), budget);
    let rejectAbort: (() => void) | undefined;
    const aborted = new Promise<never>((_resolve, reject) => {
      rejectAbort = () => reject(controller.signal.reason);
      controller.signal.addEventListener('abort', rejectAbort, {once: true});
      if (controller.signal.aborted) rejectAbort();
    });
    try {
      return await Promise.race([request<R>(method, path, {...requestOptions, signal: controller.signal}), aborted]);
    } catch (error) {
      if (signal.aborted) throw cancelled(signal);
      if (controller.signal.aborted) throw controller.signal.reason;
      throw error;
    } finally {
      runtime.clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      if (rejectAbort) controller.signal.removeEventListener('abort', rejectAbort);
    }
  };
  progress('uploading');
  let accepted: JobReply<T>;
  try {
    accepted = await fetchWithin<JobReply<T>>('POST', `${base}/object-jobs`, {
      query: {frame_index: frameIndex, ...(mode === 'room' ? {mode} : {})}, rawBody: jpeg,
    });
  } catch (error) {
    if (statusOf(error) !== 404 || signal.aborted) throw error;
    // Only the absent enqueue route indicates an older backend. A missing job is fatal.
    progress('legacy');
    return fetchWithin<T>('POST', `${base}${mode === 'room' ? '/room/frame' : '/frame'}`, {
      query: {frame_index: frameIndex}, rawBody: jpeg,
    }, remaining());
  }
  if (accepted?.state === 'complete' && 'result' in accepted) return accepted.result;
  if (accepted?.state !== 'running' || typeof accepted.job_id !== 'string' || !accepted.job_id) throw invalidReply();
  jobId = accepted.job_id;
  progress('waiting');
  let interval = POLL_INTERVAL_MS;
  while (true) {
    await runtime.delay(Math.min(interval, remaining()), signal);
    remaining();
    let reply: JobReply<T>;
    try {
      reply = await fetchWithin<JobReply<T>>('GET', `${base}/object-jobs/${encodeURIComponent(jobId)}`, {});
    } catch (error) {
      if (signal.aborted || !transient(error)) throw error;
      remaining();
      progress('retrying');
      interval = RETRY_INTERVAL_MS;
      continue;
    }
    if (reply?.state === 'complete' && 'result' in reply) return reply.result;
    if (reply?.state !== 'running') throw invalidReply();
    interval = POLL_INTERVAL_MS;
    progress('waiting');
  }
}
