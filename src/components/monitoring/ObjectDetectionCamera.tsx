import { useEffect, useState } from 'react';
import { Camera, Play, Square, LoaderCircle, VideoOff } from 'lucide-react';
import { DEMO_API_URL, demoRequest, type ObjectMonitorStatus } from '@/lib/demo-api';

const initial: ObjectMonitorStatus = {
  phase: 'stopped', running: false, run_id: 0, session_id: null,
  fps: 0, ai_seconds: 0, objects: [], checking: [], error: null, alert_error: null,
};

export function ObjectDetectionCamera() {
  const [status, setStatus] = useState(initial);
  const [reachable, setReachable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedError, setFeedError] = useState(false);
  const [feedRetry, setFeedRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    const refresh = async () => {
      if (pending || controller.signal.aborted) return;
      pending = true;
      try {
        const next = await demoRequest<ObjectMonitorStatus>('/object-monitor/status', 'GET', controller.signal);
        if (!controller.signal.aborted) {
          setStatus(next);
          setReachable(true);
        }
      } catch {
        if (!controller.signal.aborted) {
          setReachable(false);
          setStatus(previous => ({ ...previous, objects: [], checking: [], fps: 0 }));
        }
      } finally { pending = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, []);

  const control = async (action: 'start' | 'stop') => {
    setBusy(true);
    setError(null);
    setFeedError(false);
    try {
      const next = await demoRequest<ObjectMonitorStatus>(`/object-monitor/${action}`, 'POST');
      setStatus(next);
      setReachable(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not reach the monitoring server.');
    } finally { setBusy(false); }
  };

  const phaseLabel = !reachable ? 'Backend offline' : {
    stopped: 'Camera stopped', loading: 'Loading detector', ready: 'Monitoring',
    stopping: 'Stopping camera', error: 'Camera unavailable',
  }[status.phase];

  return (
    <section className="mb-8 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50" aria-label="Live phone and book detection">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 px-5 py-4">
        <div>
          <h2 className="flex items-center gap-2 font-semibold text-zinc-100"><Camera size={18} /> Live phone and book detection</h2>
          <p className="mt-1 text-sm text-zinc-400">Uses this PC’s connected webcam. Confirmed alerts appear in the inbox below.</p>
        </div>
        <button
          disabled={busy || !reachable || status.phase === 'stopping'}
          onClick={() => void control(status.running ? 'stop' : 'start')}
          className={`inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-colors disabled:cursor-wait disabled:opacity-50 ${status.running ? 'border-rose-500/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20' : 'border-indigo-500/30 bg-indigo-500/15 text-indigo-200 hover:bg-indigo-500/25'}`}
        >
          {busy ? <LoaderCircle size={16} className="animate-spin" /> : status.running ? <Square size={16} /> : <Play size={16} />}
          {status.running ? 'Stop monitoring' : 'Start monitoring'}
        </button>
      </div>
      <div className="relative flex aspect-video items-center justify-center bg-black">
        {status.running && reachable ? (
          <img
            key={`${status.run_id}-${feedRetry}`}
            src={`${DEMO_API_URL}/object-monitor/feed?run_id=${status.run_id}&retry=${feedRetry}`}
            alt="Live webcam with phone and book detection boxes"
            className="h-full w-full object-contain"
            onError={() => setFeedError(true)}
            onLoad={() => setFeedError(false)}
          />
        ) : (
          <div className="px-6 text-center text-zinc-500">
            <VideoOff size={36} className="mx-auto mb-3" />
            <p>{reachable ? 'Start monitoring to open the camera.' : 'Connect the local backend to enable monitoring.'}</p>
          </div>
        )}
        <div className="absolute left-3 top-3 flex items-center gap-2 rounded-md bg-black/75 px-3 py-2 text-xs text-zinc-100">
          <span className={`h-2 w-2 rounded-full ${status.running && reachable ? 'animate-pulse bg-emerald-400' : 'bg-zinc-500'}`} />
          {phaseLabel}
          {status.running && status.fps > 0 && <span className="text-zinc-400">{status.fps.toFixed(0)} FPS</span>}
          {status.running && status.ai_seconds > 0 && <span className="text-zinc-400">AI {status.ai_seconds.toFixed(1)}s</span>}
        </div>
        {feedError && status.running && (
          <div className="absolute inset-x-0 bottom-0 bg-black/85 p-3 text-center text-sm text-amber-200">
            Camera feed interrupted. <button className="ml-2 underline" onClick={() => { setFeedError(false); setFeedRetry(v => v+1); }}>Reconnect feed</button>
          </div>
        )}
      </div>
      <div className="space-y-3 px-5 py-4">
        <div className="flex flex-wrap items-center gap-2" aria-live="polite">
          {status.objects.map(object => (
            <span key={`${object.type}-${object.track_id}`} className="rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-1.5 text-sm text-rose-200">
              {object.label === 'phone' ? 'Phone detected' : 'Book detected'} · {Math.round(object.confidence*100)}%
            </span>
          ))}
          {status.checking.map(label => <span key={label} className="rounded-md bg-zinc-800 px-3 py-1.5 text-sm text-zinc-300">Checking {label}…</span>)}
          {status.running && status.objects.length === 0 && status.checking.length === 0 && (
            <span className="text-sm text-zinc-400">{status.phase === 'loading' ? 'The camera stays live while the detector loads.' : status.detector?.checks === 0 ? 'Running the first object check…' : 'Looking for phones and books…'}</span>
          )}
          {status.session_id !== null && <span className="ml-auto text-xs text-zinc-500">Session #{status.session_id}</span>}
        </div>
        <p className="text-xs leading-relaxed text-zinc-500">New objects need several seconds to confirm. Gray boxes are being checked; sustained confirmed detections create review alerts. Continuous alerts are limited to one per combination every 20 seconds.</p>
        {(error || status.error || status.alert_error) && <p role="alert" className="text-sm text-rose-300">{error || status.error || status.alert_error}</p>}
      </div>
    </section>
  );
}
