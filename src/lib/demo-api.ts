// Local SQLite demo API. The authenticated platform API stays in api.ts.
export const DEMO_API_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');

export async function demoRequest<T>(path: string, method = 'GET', signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${DEMO_API_URL}${path}`, { method, signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status}).`);
  }
  return body as T;
}

export interface ObjectMonitorStatus {
  phase: 'stopped' | 'loading' | 'ready' | 'stopping' | 'error';
  running: boolean;
  run_id: number;
  session_id: number | null;
  fps: number;
  ai_seconds: number;
  detector?: { checks: number; last_check_age: number | null } | null;
  objects: { label: string; type: string; confidence: number; track_id: number }[];
  checking: string[];
  error: string | null;
  alert_error: string | null;
  head_error?: string | null;
  head_pose?: HeadPoseStatus | null;
}

export interface HeadPoseStatus {
  state: string;
  calibrated: boolean;
  calibrating: boolean;
  calibration_progress: number;
  yaw: number | null;
  pitch: number | null;
  roll: number | null;
  violating: boolean;
  sustained: boolean;
  duration: number;
  processing_ms: number;
  thresholds: { yaw: number; pitch: number; seconds: number };
}
