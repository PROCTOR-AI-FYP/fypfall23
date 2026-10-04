import { useEffect,useState } from 'react';
import { API_BASE_URL,request } from '@/lib/api';
import type { ObjectMonitorStatus } from '@/lib/demo-api';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/FormElements';

type CameraStatus = Omit<ObjectMonitorStatus,'session_id'> & {session_id:string;seat_number:number|null};
type Seat = {seat_number:number;student_name:string;registration_no:string};

export function SessionCamera({sessionId,active}:{sessionId:string;active:boolean}) {
  const [status,setStatus] = useState<CameraStatus|null>(null);
  const [seats,setSeats] = useState<Seat[]>([]);
  const [seat,setSeat] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [connectionError,setConnectionError] = useState('');
  const [feedError,setFeedError] = useState(false);
  const [retry,setRetry] = useState(0);
  const base = `/api/sessions/${sessionId}/camera`;

  useEffect(() => {
    let cancelled=false,pending=false;
    const refresh = async () => {
      if (pending) return;
      pending=true;
      try {
        const value=await request<CameraStatus>('GET',`${base}/status`);
        if (!cancelled) { setStatus(value); setConnectionError(''); }
      } catch (reason) {
        if (!cancelled) { setStatus(null); setConnectionError((reason as {message:string}).message); }
      } finally { pending=false; }
    };
    void refresh();
    request<Seat[]>('GET',`${base}/seats`).then(value=>{ if (!cancelled) setSeats(value); }).catch(reason=>{ if (!cancelled) setError(reason.message); });
    const timer=window.setInterval(()=>void refresh(),500);
    return ()=>{ cancelled=true; window.clearInterval(timer); };
  },[base]);

  const control = async (action:'start'|'stop'|'calibrate') => {
    setBusy(true);setError('');setFeedError(false);
    try { setStatus(await request<CameraStatus>('POST',`${base}/${action}`,action==='start'?{body:{seat_number:Number(seat)}}:{})); }
    catch (reason) { setError((reason as {message:string}).message); }
    finally {setBusy(false);}
  };
  const head=status?.head_pose;
  const headText = !head ? 'Head pose unavailable' : ({
    calibration_required:'Set neutral pose to enable head monitoring.',
    calibrating:`Hold still · ${Math.round(head.calibration_progress*100)}%`,
    face_forward_to_calibrate:'Face forward and hold still.',no_face:'Face not visible',
    multiple_faces:'Use one student in this camera view.',face_too_small:'Move closer so the face is clear.',
    unreliable_face:'Face tracking uncertain',neutral:'Head pose within limits',
    turning:`Checking movement · ${head.duration.toFixed(1)} / ${head.thresholds.seconds}s`,
    sustained:'Sustained head-pose warning',
  }[head.state]??'Tracking unavailable');

  return <section className="pa-camera rounded-[6px] border border-(--color-border-default) bg-(--color-bg-surface) overflow-hidden" aria-label="Live exam camera">
    <div className="p-4 flex flex-wrap items-center gap-3">
      <h2 className="text-heading">Live exam camera</h2>
      <span className="text-label text-(--color-text-muted)">{status?.running?`${Math.round(status.fps)} FPS · seat ${status.seat_number}`:'Camera stopped'}</span>
      <div className="ml-auto flex flex-wrap gap-2">
        <Select aria-label="Monitored student seat" value={status?.running?String(status.seat_number):seat} disabled={!!status?.running||busy||!active} onChange={event=>setSeat(event.target.value)}>
          <option value="">Select student seat</option>
          {seats.map(value=><option key={value.seat_number} value={value.seat_number}>Seat {value.seat_number} · {value.student_name}</option>)}
        </Select>
        <Button disabled={busy||!active||(!status?.running&&!seat)} onClick={()=>void control(status?.running?'stop':'start')}>{status?.running?'Stop camera':'Start camera'}</Button>
      </div>
    </div>
    {status?.running?<div className="relative bg-black"><img src={`${API_BASE_URL}${base}/feed?run=${status.run_id}&retry=${retry}`} alt="Live exam webcam with phone, book and head-pose overlays" className="w-full aspect-video object-contain" onError={()=>setFeedError(true)} onLoad={()=>setFeedError(false)} />{feedError&&<p className="absolute bottom-0 bg-black/80 p-3 text-white w-full">Feed interrupted. <button onClick={()=>setRetry(value=>value+1)} className="underline">Reconnect</button></p>}</div>:<div className="aspect-video grid place-items-center bg-(--color-bg-surface-raised) text-(--color-text-muted)">{active?'Select the registered student whose seat this webcam monitors.':'Camera monitoring is available during an active exam.'}</div>}
    <div className="p-4 space-y-3">
      {!seats.length&&<p className="text-body-sm text-(--color-warning)">Upload a resolved student seat map before starting detection.</p>}
      <p className="text-body-sm">{status?.objects.length?status.objects.map(value=>`${value.label==='phone'?'Phone':'Book'} · ${Math.round(value.confidence*100)}%`).join(' · '):status?.running?'Checking for phones and books…':'Phone and book detection ready'}</p>
      <div className="flex justify-between items-center gap-3"><p className={`text-body-sm ${head?.sustained?'text-(--color-error)':head?.violating?'text-(--color-warning)':''}`}>{headText}</p><Button variant="secondary" disabled={busy||!status?.running||!head||head.calibrating||!!status.head_error} onClick={()=>void control('calibrate')}>{head?.calibrated?'Recalibrate':'Set neutral pose'}</Button></div>
      {head?.yaw!=null&&<div className="grid grid-cols-3 gap-3 text-body-sm tabular-nums">{([['Yaw',head.yaw],['Pitch',head.pitch],['Roll',head.roll]] as const).map(([label,value])=><p key={label}>{label} {value!=null?(value>0?'+':'')+value.toFixed(1)+'°':'—'}</p>)}</div>}
      <p className="text-label text-(--color-text-muted)">One registered student per camera view. Set neutral in normal exam posture and hold still for two seconds. Sideways movement over 30° or downward movement over 20° needs two continuous seconds. Head pose alone is a warning. Confirmed object evidence enters the exam’s review workflow.</p>
      {(error||connectionError||status?.error||status?.head_error||status?.alert_error)&&<p role="alert" className="text-body-sm text-(--color-error)">{error||connectionError||status?.error||status?.head_error||status?.alert_error}</p>}
    </div>
  </section>;
}
