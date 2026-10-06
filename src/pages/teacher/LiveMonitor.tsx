import { RoomCamera } from '@/components/monitoring/RoomCamera';
import { DeviceCamera } from '@/components/monitoring/DeviceCamera';
import { SessionSeatPlan } from '@/components/monitoring/SessionSeatPlan';
import { useLiveRevision } from '@/lib/live-context';
import { useEffect, useState, useRef } from 'react';
import { useParams,useNavigate } from 'react-router-dom';
import { Grid3x3, Box, StopCircle } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { BehaviorChip } from '@/components/ui/Chips';
import { ConfidenceBar, LoadingState } from '@/components/ui/DataDisplay';
import * as api from '@/lib/api';
import { type ExamSession, type DetectionEvent } from '@/lib/types';

export function LiveMonitor() {
  const { id } = useParams<{ id: string }>();
  return <MonitorSession key={id} id={id}/>;
}

function MonitorSession({id}:{id?:string}) {
  const liveRevision = useLiveRevision();
  const navigate=useNavigate();
  const [session, setSession] = useState<ExamSession | null>(null);
  const [detections, setDetections] = useState<DetectionEvent[]>([]);
  const [seatMap,setSeatMap]=useState<api.SessionSeatMap|null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [view, setView] = useState<'2d' | '3d'>('2d');
  const [cameraMode,setCameraMode]=useState<'live'|'room'>('live');
  const unsubscribeRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!id) return;
    if (!liveRevision) setLoading(true);

    let cancelled=false;
    Promise.all([
      api.getSession(id),
      api.getDetectionEvents(id),
      api.getSessionSeatMap(id),
    ]).then(([sessionRes, detectionsRes,map]) => {
      if(cancelled)return;
      setError('');setSeatMap(map);
      setSession(sessionRes.data);
      setDetections(detectionsRes.data);
      setLoading(false);
    }).catch(reason => { if(!cancelled){setError(reason.message); setLoading(false);} });

    // Live alerts for this session (Socket.IO, alert:new)
    const unsubscribe = api.subscribeToAlerts(
      (event: DetectionEvent) => {
        if (event.sessionId !== id) return;
        setDetections(prev => (prev.some(d => d.id === event.id) ? prev : [event, ...prev]));
      },
      { sessionId: id },
    );
    unsubscribeRef.current = unsubscribe;

    return () => { cancelled=true;unsubscribe(); };
  }, [id, liveRevision]);

  const handleEndSession = async () => {
    if (!id) return;
    try {
      await api.endSession(id);
      unsubscribeRef.current?.();
      setSession(prev => prev ? { ...prev, status: 'Completed' as ExamSession['status'] } : null);
    } catch (reason) { setError((reason as {message:string}).message); }
  };

  if (loading) return <LoadingState message="Connecting to monitoring feed..." />;
  if (!session) return <div role="alert" className="text-center py-16 text-(--color-text-muted)">{error || 'Session not found'}</div>;


  return (
    <div>
      {error && <p role="alert" className="text-(--color-error) mb-4">{error}</p>}
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
              <Box size={14} className="inline mr-1" />Perspective
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
          <div className="flex flex-wrap items-center gap-2 mb-3" role="group" aria-label="Camera monitoring mode">
            <Button variant={cameraMode==='live'?'primary':'secondary'} aria-pressed={cameraMode==='live'} onClick={()=>setCameraMode('live')}>Live camera</Button>
            <Button variant={cameraMode==='room'?'primary':'secondary'} aria-pressed={cameraMode==='room'} onClick={()=>setCameraMode('room')}>Classroom mapping</Button>
          </div>
          {cameraMode==='live'?<DeviceCamera key={`live-${session.id}`} sessionId={session.id} active={session.status === 'In Progress'}/>:seatMap&&<RoomCamera key={`room-${session.id}`} sessionId={session.id} active={session.status === 'In Progress'} seatMap={seatMap}/>}
          {seatMap&&<SessionSeatPlan map={seatMap} detections={detections} perspective={view==='3d'} onReview={event=>navigate(`/teacher/alerts?alert=${event.id}`)}/>}

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
                    <Button variant="ghost" size="sm" className="mt-2" onClick={()=>navigate(`/teacher/alerts?alert=${d.id}`)}>Review alert</Button>
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
