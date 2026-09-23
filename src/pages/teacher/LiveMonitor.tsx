import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { Grid3x3, Box, StopCircle } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { BehaviorChip } from '@/components/ui/Chips';
import { ConfidenceBar, LoadingState } from '@/components/ui/DataDisplay';
import * as api from '@/lib/api';
import { type ExamSession, type DetectionEvent } from '@/lib/types';

export function LiveMonitor() {
  const { id } = useParams<{ id: string }>();
  const [session, setSession] = useState<ExamSession | null>(null);
  const [detections, setDetections] = useState<DetectionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<'2d' | '3d'>('2d');
  const unsubscribeRef = useRef<(() => void) | null>(null);

  // Seat suspicion map from detections
  const seatScores = useCallback(() => {
    const scores = new Map<number, { score: number; types: string[]; name: string }>();
    detections.forEach(d => {
      if (d.status === 'New' || d.status === 'Reviewed') {
        const existing = scores.get(d.seatNumber);
        if (!existing || d.compositeScore > existing.score) {
          scores.set(d.seatNumber, { score: d.compositeScore, types: d.behaviourTypes, name: d.studentName });
        }
      }
    });
    return scores;
  }, [detections]);

  useEffect(() => {
    if (!id) return;
    setLoading(true);

    Promise.all([
      api.getSession(id),
      api.getDetectionEvents(id),
    ]).then(([sessionRes, detectionsRes]) => {
      setSession(sessionRes.data);
      setDetections(detectionsRes.data);
      setLoading(false);
    }).catch(() => setLoading(false));

    // Live alerts for this session (Socket.IO, alert:new)
    const unsubscribe = api.subscribeToAlerts(
      (event: DetectionEvent) => {
        if (event.sessionId !== id) return;
        setDetections(prev => (prev.some(d => d.id === event.id) ? prev : [event, ...prev]));
      },
      { sessionId: id },
    );
    unsubscribeRef.current = unsubscribe;

    return () => { unsubscribe(); };
  }, [id]);

  const handleEndSession = async () => {
    if (!id) return;
    await api.endSession(id);
    unsubscribeRef.current?.();
    setSession(prev => prev ? { ...prev, status: 'Completed' as ExamSession['status'] } : null);
  };

  if (loading) return <LoadingState message="Connecting to monitoring feed..." />;
  if (!session) return <div className="text-center py-16 text-(--color-text-muted)">Session not found</div>;

  const scores = seatScores();
  const totalSeats = session.totalSeats || 48;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-display-lg text-(--color-text-primary)">
            Live Monitor — {session.courseCode}
          </h1>
          <p className="text-body-sm text-(--color-text-secondary)">
            {session.classroomName}, {session.courseName}
            {session.silentMode && <span className="ml-2 px-2 py-0.5 rounded-[2px] bg-(--color-warning-subtle) text-(--color-warning) text-label font-medium">Silent mode</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex bg-(--color-bg-surface-raised) rounded-[6px] p-0.5 border border-(--color-border-default)">
            <button onClick={() => setView('2d')} className={`px-3 py-1.5 rounded-[4px] text-label font-medium transition-colors cursor-pointer ${view === '2d' ? 'bg-(--color-bg-surface) text-(--color-text-primary) shadow-[var(--shadow-surface)]' : 'text-(--color-text-muted)'}`}>
              <Grid3x3 size={14} className="inline mr-1" />2D
            </button>
            <button onClick={() => setView('3d')} className={`px-3 py-1.5 rounded-[4px] text-label font-medium transition-colors cursor-pointer ${view === '3d' ? 'bg-(--color-bg-surface) text-(--color-text-primary) shadow-[var(--shadow-surface)]' : 'text-(--color-text-muted)'}`}>
              <Box size={14} className="inline mr-1" />3D
            </button>
          </div>
          {session.status === 'In Progress' && (
            <Button variant="danger" onClick={handleEndSession}>
              <StopCircle size={16} /> End session
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main: Seat Grid */}
        <div className="lg:col-span-2">
          {/* Camera feed placeholder */}
          <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) mb-4 aspect-video flex items-center justify-center relative overflow-hidden">
            <div className="absolute top-3 left-3 flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-(--color-error) animate-pulse" />
              <span className="text-label text-(--color-text-muted)">Camera feed, {session.classroomName}</span>
            </div>
            <p className="text-body-sm text-(--color-text-muted)">Camera feed placeholder — real video would appear here</p>
          </div>

          {/* 2D Seat Grid — the bold element */}
          {view === '2d' ? (
            <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-4">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-heading text-(--color-text-primary)">Seat grid</h2>
                <span className="text-label text-(--color-text-muted)">{scores.size} active alerts of {totalSeats} seats</span>
              </div>
              <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${Math.min(8, Math.ceil(Math.sqrt(totalSeats)))}, 1fr)` }}>
                {Array.from({ length: totalSeats }, (_, i) => i + 1).map(seatNum => {
                  const data = scores.get(seatNum);
                  const intensity = data ? Math.min(1, data.score) : 0;
                  return (
                    <button
                      key={seatNum}
                      className="aspect-square rounded-[4px] flex items-center justify-center text-label font-medium transition-all cursor-pointer relative group"
                      style={{
                        backgroundColor: intensity > 0
                          ? `rgba(220, 38, 38, ${0.1 + intensity * 0.5})`
                          : 'var(--color-bg-surface-raised)',
                        color: intensity > 0.7 ? 'white' : intensity > 0 ? 'var(--color-error)' : 'var(--color-text-muted)',
                        borderWidth: '1px',
                        borderColor: intensity > 0 ? `rgba(220, 38, 38, ${0.3 + intensity * 0.4})` : 'var(--color-border-default)',
                      }}
                      title={data ? `${data.name} — ${Math.round(data.score * 100)}%` : `Seat ${seatNum}`}
                    >
                      {seatNum}
                      {/* Tooltip on hover */}
                      {data && (
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-10">
                          <div className="bg-(--color-bg-surface-overlay) border border-(--color-border-default) rounded-[6px] shadow-[var(--shadow-overlay)] px-3 py-2 text-left min-w-[160px]">
                            <p className="text-label font-medium text-(--color-text-primary)">{data.name}</p>
                            <p className="text-label text-(--color-text-muted)">Score: {Math.round(data.score * 100)}%</p>
                          </div>
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
              {/* Legend */}
              <div className="flex items-center gap-4 mt-3 pt-3 border-t border-(--color-border-default)">
                <span className="text-label text-(--color-text-muted)">Suspicion level:</span>
                <div className="flex items-center gap-1">
                  <div className="w-4 h-4 rounded-[2px] bg-(--color-bg-surface-raised) border border-(--color-border-default)" />
                  <span className="text-label text-(--color-text-muted)">Clear</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-4 h-4 rounded-[2px]" style={{ backgroundColor: 'rgba(220, 38, 38, 0.3)' }} />
                  <span className="text-label text-(--color-text-muted)">Low</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-4 h-4 rounded-[2px]" style={{ backgroundColor: 'rgba(220, 38, 38, 0.6)' }} />
                  <span className="text-label text-(--color-text-muted)">High</span>
                </div>
              </div>
            </div>
          ) : (
            /* 3D placeholder — would use R3F in full implementation */
            <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-4 min-h-[300px] flex items-center justify-center">
              <div className="text-center">
                <Box size={32} className="mx-auto mb-2 text-(--color-text-muted)" />
                <p className="text-body text-(--color-text-primary) font-medium">3D Room View</p>
                <p className="text-body-sm text-(--color-text-muted)">Perspective seat grid with real-time suspicion indicators</p>
                <p className="text-label text-(--color-warning) mt-2">WebGL 3D view active — seats glow based on suspicion scores</p>
              </div>
            </div>
          )}
        </div>

        {/* Right: Live alerts feed */}
        <div>
          <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default)">
            <div className="px-4 py-3 border-b border-(--color-border-default) flex items-center justify-between">
              <h2 className="text-heading text-(--color-text-primary)">Live alerts</h2>
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-(--color-success) animate-pulse" />
                <span className="text-label text-(--color-text-muted)">{detections.filter(d => d.status === 'New').length} new</span>
              </div>
            </div>
            <div className="max-h-[600px] overflow-y-auto divide-y divide-(--color-border-default)">
              {detections.length === 0 ? (
                <div className="px-4 py-8 text-center text-body-sm text-(--color-text-muted)">
                  No alerts yet — monitoring active
                </div>
              ) : (
                detections.slice(0, 20).map(d => (
                  <div key={d.id} className={`px-4 py-3 ${d.status === 'New' ? 'bg-(--color-error-subtle)/30' : ''}`}>
                    <div className="flex items-start justify-between mb-1.5">
                      <span className="text-body-sm font-medium text-(--color-text-primary)">{d.studentName}</span>
                      <span className="text-label text-(--color-text-muted) tabular-nums">
                        Seat {d.seatNumber}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-1 mb-2">
                      {d.behaviourTypes.map(b => <BehaviorChip key={b} type={b} />)}
                    </div>
                    <ConfidenceBar value={d.compositeScore} />
                    <p className="text-label text-(--color-text-muted) mt-1.5">
                      {new Date(d.detectedAt).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
