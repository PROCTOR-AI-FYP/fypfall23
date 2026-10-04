import { useEffect, useState } from 'react';
import { io } from 'socket.io-client';
import { ShieldAlert, CheckCircle, XCircle } from 'lucide-react';
import { ObjectDetectionCamera } from '@/components/monitoring/ObjectDetectionCamera';
import { DEMO_API_URL, demoRequest } from '@/lib/demo-api';

const SOCKET_URL = DEMO_API_URL || window.location.origin;

type CaseStatus = 'pending' | 'confirmed' | 'dismissed';

interface Case {
  id: number;
  detection_id: number;
  type?: string;
  confidence?: number;
  status: CaseStatus;
  created_at: string;
}

export default function App() {
  const [cases, setCases] = useState<Case[]>([]);
  const [connected, setConnected] = useState(false);
  const [caseError, setCaseError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<number | null>(null);

  useEffect(() => {
    // Fetch initial cases
    demoRequest<Case[]>('/cases')
      .then((data: Case[]) => {
        // Sort newest first
        const sorted = data.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        setCases(sorted);
      })
      .catch(() => setCaseError('Could not load the alert inbox. Check the local backend.'));

    // Connect WebSocket
    const socket = io(SOCKET_URL);

    socket.on('connect', () => {
      setConnected(true);
      // Reload after reconnect so alerts created during a disconnect are retained.
      demoRequest<Case[]>('/cases').then(data => {
        setCases(data.sort((a,b) => new Date(b.created_at).getTime()-new Date(a.created_at).getTime()));
        setCaseError(null);
      }).catch(() => setCaseError('Could not refresh the alert inbox.'));
    });
    socket.on('disconnect', () => setConnected(false));

    socket.on('case_created', (newCase: Case) => {
      setCases((prev) => prev.some(c => c.id === newCase.id) ? prev : [newCase, ...prev]);
    });

    socket.on('case_updated', (updatedCase: Case) => {
      setCases((prev) => prev.map(c => c.id === updatedCase.id ? { ...c, status: updatedCase.status } : c));
    });

    return () => {
      socket.disconnect();
    };
  }, []);

  const handleAction = async (id: number, action: 'confirm' | 'dismiss') => {
    setPendingAction(id);
    setCaseError(null);
    try {
      await demoRequest(`/cases/${id}/${action}`, 'POST');
      setCases(prev => prev.map(c => c.id === id ? { ...c, status: action === 'confirm' ? 'confirmed' : 'dismissed' } : c));
    } catch {
      setCaseError(`Could not ${action} the alert. It has not been marked resolved.`);
    } finally { setPendingAction(null); }
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-4 sm:p-8 font-sans selection:bg-indigo-500/30">
      <div className="max-w-4xl mx-auto">
        <header className="flex flex-col items-start gap-4 sm:flex-row sm:items-center justify-between mb-8 pb-6 border-b border-zinc-800">
          <div>
            <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-indigo-400 to-cyan-400 bg-clip-text text-transparent">
              Live Alert Inbox
            </h1>
            <p className="text-zinc-400 mt-2">Real-time detection events and anomaly monitoring</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-zinc-400">System Status:</span>
            <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border ${connected ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20'}`}>
              <div className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
              {connected ? 'Live' : 'Disconnected'}
            </div>
          </div>
        </header>

        <ObjectDetectionCamera />

        {caseError && <p role="alert" className="mb-4 text-sm text-rose-300">{caseError}</p>}

        <div className="space-y-4">
          {cases.length === 0 ? (
            <div className="text-center py-16 px-4 rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30">
              <ShieldAlert className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-zinc-300">No alerts yet</h3>
              <p className="text-zinc-500 mt-1">Waiting for incoming detections from the AI engine...</p>
            </div>
          ) : (
            cases.map((c) => (
              <div
                key={c.id}
                className="group relative flex flex-col items-stretch gap-4 sm:flex-row sm:items-center justify-between p-5 rounded-xl border border-zinc-800 bg-zinc-900/50 hover:bg-zinc-900 transition-all duration-200 shadow-sm hover:shadow-md hover:border-zinc-700 overflow-hidden"
              >
                {/* Status indicator line */}
                <div className={`absolute left-0 top-0 bottom-0 w-1 ${c.status === 'pending' ? 'bg-amber-500' : c.status === 'confirmed' ? 'bg-emerald-500' : 'bg-zinc-600'}`} />

                <div className="flex min-w-0 flex-col gap-1.5 pl-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="break-words font-semibold text-lg tracking-wide text-zinc-100">
                      {c.type ? c.type.replace(/_/g, ' ') : `Unknown Event`}
                    </span>
                    {c.status !== 'pending' && (
                      <span className={`text-xs px-2 py-0.5 rounded-md font-medium uppercase tracking-wider ${
                        c.status === 'confirmed' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-zinc-800 text-zinc-400'
                      }`}>
                        {c.status}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-sm text-zinc-400">
                    {c.confidence !== undefined && c.confidence !== null && (
                      <div className="flex items-center gap-1.5">
                        <span className="opacity-70">Alert score:</span>
                        <span className="font-mono text-indigo-300">{(c.confidence * 100).toFixed(1)}%</span>
                      </div>
                    )}
                    <div className="flex items-center gap-1.5">
                      <span className="opacity-70">Time:</span>
                      <span className="font-mono">{new Date(c.created_at).toLocaleTimeString()}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity duration-200">
                  {c.status === 'pending' ? (
                    <>
                      <button
                        disabled={pendingAction === c.id}
                        onClick={() => handleAction(c.id, 'confirm')}
                        className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 hover:text-emerald-300 transition-colors border border-emerald-500/20 cursor-pointer"
                      >
                        <CheckCircle className="w-4 h-4" />
                        Confirm
                      </button>
                      <button
                        disabled={pendingAction === c.id}
                        onClick={() => handleAction(c.id, 'dismiss')}
                        className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100 transition-colors border border-zinc-700 cursor-pointer"
                      >
                        <XCircle className="w-4 h-4" />
                        Dismiss
                      </button>
                    </>
                  ) : (
                    <span className="text-sm italic text-zinc-500 pr-4">Resolved</span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
