import { useCallback, useEffect, useRef, useState } from 'react';
import { request, type SessionSeatMap } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/FormElements';
import type { CameraObject } from '@/lib/vision/object-tracking';

type Region={seat_number:number;box:number[]};
type Pose={seat_number:number;state:string;calibrated:boolean;calibrating:boolean;calibration_progress:number;
  sustained:boolean;violating:boolean;review_enabled:boolean;yaw:number|null;pitch:number|null;face_box:number[]|null};
type HeadResult={seats:Pose[];alerts:unknown[];alert_error:string|null;image_size:number[]};
type ObjectResult={objects:(CameraObject&{seat_number:number})[];ai_seconds:number;alert:unknown|null;
  alerts:unknown[];alert_error:string|null;warning:string|null;checked_seat:number|null;mapped_seats:number;review_observations:number;review_status:string};
type Capture={stream:MediaStream;run:string|null;abort:AbortController;timers:Set<number>;stopped:boolean;layoutKey:string;dimensions:number[]};
const poseLabel:Record<string,string>={calibration_required:'Set neutral posture',calibrating:'Calibrating',
  face_forward_to_calibrate:'Face forward to calibrate',no_face:'Face not visible',multiple_faces:'Two faces in this seat region',
  face_too_small:'Face too small for reliable angles',unreliable_face:'Face tracking uncertain',
  neutral:'Within head-pose limits',turning:'Checking head movement',sustained:'Sustained head-pose warning'};

export function RoomCamera({sessionId,active,seatMap}:{sessionId:string;active:boolean;seatMap:SessionSeatMap}) {
  const video=useRef<HTMLVideoElement>(null),capture=useRef<Capture|null>(null),mounted=useRef(true),opening=useRef(false);
  const [phase,setPhase]=useState<'stopped'|'opening'|'mapping'|'running'>('stopped');
  const [regions,setRegions]=useState<Region[]>([]),[selected,setSelected]=useState(''),[inspect,setInspect]=useState('');
  const [drag,setDrag]=useState<number[]|null>(null),dragStart=useRef<number[]|null>(null);
  const [error,setError]=useState(''),[objectMessage,setObjectMessage]=useState(''),[headError,setHeadError]=useState('');
  const [poses,setPoses]=useState<Pose[]>([]),[objects,setObjects]=useState<(CameraObject&{seat_number:number})[]>([]);
  const [saved,setSaved]=useState(0),[ratio,setRatio]=useState(16/9),[imageSize,setImageSize]=useState([1600,900]);
  const [devices,setDevices]=useState<MediaDeviceInfo[]>([]),[device,setDevice]=useState('');
  const [starting,setStarting]=useState(false),[calibrating,setCalibrating]=useState(false);
  const assignments=seatMap.assignments.filter(s=>s.active);
  const roster=assignments.map(s=>`${s.seat_number}:${s.student_id}`).join('|');
  const stop=useCallback((message='')=>{
    const state=capture.current;capture.current=null;
    if(state){state.stopped=true;state.abort.abort();state.timers.forEach(window.clearTimeout);
      state.stream.getTracks().forEach(t=>t.stop());
      if(state.run)void request('POST',`/api/device-camera/${state.run}/stop`,{keepalive:true}).catch(()=>{});}
    if(video.current)video.current.srcObject=null;
    if(mounted.current){setPhase('stopped');setPoses([]);setObjects([]);setHeadError('');setCalibrating(false);if(message)setError(message);}
  },[]);
  useEffect(()=>{
    mounted.current=true;
    const hidden=()=>{if(document.hidden)stop('Room camera stopped while this tab was hidden.');};
    const leaving=()=>stop();
    document.addEventListener('visibilitychange',hidden);window.addEventListener('pagehide',leaving);
    return()=>{mounted.current=false;document.removeEventListener('visibilitychange',hidden);window.removeEventListener('pagehide',leaving);stop();};
  },[stop]);
  useEffect(()=>{if(!active)stop();},[active,stop]);
  // A new CSV invalidates camera attribution; ordinary live revisions do not.
  useEffect(()=>{stop();setRegions([]);setSelected('');setInspect('');},[roster,sessionId,stop]);

  const open=async()=>{
    if(opening.current||capture.current)return;
    opening.current=true;setPhase('opening');setError('');setSaved(0);setObjectMessage('');
    let stream:MediaStream|null=null;
    try{
      if(!navigator.mediaDevices?.getUserMedia||!window.isSecureContext)throw Error('Use HTTPS or localhost for camera access.');
      stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{width:{ideal:1920},height:{ideal:1080},frameRate:{ideal:30,max:30},
        ...(device?{deviceId:{exact:device}}:{facingMode:{ideal:'environment'}})}});
      if(!mounted.current||document.hidden){stream.getTracks().forEach(t=>t.stop());return;}
      const layoutKey=`proctorai-room-layout:${sessionId}:${stream.getVideoTracks()[0].getSettings().deviceId||device||'default'}`;
      const state:Capture={stream,run:null,abort:new AbortController(),timers:new Set(),stopped:false,layoutKey,dimensions:[]};capture.current=state;
      stream.getVideoTracks()[0].onended=()=>stop('Room camera disconnected.');
      video.current!.srcObject=stream;await video.current!.play();
      if(capture.current!==state)return;
      setRatio(video.current!.videoWidth/video.current!.videoHeight);
      state.dimensions=[video.current!.videoWidth,video.current!.videoHeight];
      try{
        const stored=JSON.parse(sessionStorage.getItem(layoutKey)||'null');
        if(stored?.roster===roster&&JSON.stringify(stored.dimensions)===JSON.stringify(state.dimensions)&&Array.isArray(stored.regions)){
          const valid=stored.regions.filter((r:Region)=>assignments.some(s=>s.seat_number===r.seat_number)&&Array.isArray(r.box)&&r.box.length===4&&r.box.every(v=>Number.isFinite(v)&&v>=0&&v<=1));
          setRegions(valid);
        }else setRegions([]);
      }catch{setRegions([]);}
      setDevices((await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput'));
      if(capture.current!==state)return;
      setPhase('mapping');setSelected(String(assignments[0]?.seat_number??''));
    }catch(reason){stream?.getTracks().forEach(t=>t.stop());stop();const failure=reason as {name?:string;message:string};
      setError(failure.name==='NotAllowedError'?'Allow camera access for this website, then retry.':failure.message);}
    finally{opening.current=false;if(!capture.current)setPhase('stopped');}
  };
  const sample=async()=>{
    const source=video.current!;
    if(!source.videoWidth)throw Error('Waiting for camera image.');
    const scale=Math.min(1,1600/source.videoWidth,1200/source.videoHeight);
    const canvas=document.createElement('canvas');canvas.width=Math.round(source.videoWidth*scale);canvas.height=Math.round(source.videoHeight*scale);
    canvas.getContext('2d')!.drawImage(source,0,0,canvas.width,canvas.height);
    return new Promise<Blob>((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(Error('Camera sample failed.')),'image/jpeg',.85));
  };
  const begin=async()=>{
    const state=capture.current;if(!state||starting||state.run)return;
    setStarting(true);setError('');
    try{
      const result=await request<{run_id:string}>('POST',`/api/sessions/${sessionId}/device-camera/room/start`,{body:{regions},signal:state.abort.signal});
      state.run=result.run_id;
      if(state.stopped){void request('POST',`/api/device-camera/${state.run}/stop`).catch(()=>{});return;}
      try{sessionStorage.setItem(state.layoutKey,JSON.stringify({roster,dimensions:state.dimensions,regions}));}catch{/* Mapping still works when browser storage is unavailable. */}
      setPhase('running');setObjectMessage('Scanning mapped student regions…');
      const schedule=(fn:()=>void,delay:number)=>{if(!state.stopped){const timer=window.setTimeout(()=>{state.timers.delete(timer);fn();},delay);state.timers.add(timer);}};
      const failed=(reason:unknown,head:boolean)=>{
        if(state.stopped)return;
        const failure=reason as {status?:number;message:string};
        if([401,403,404,409,410].includes(failure.status??0)){stop(failure.message);return;}
        const message=failure.status===429?'Verifier busy; retrying…':failure.message;
        if(head)setHeadError(message);else{setObjectMessage(message);setObjects([]);}
      };
      let headIndex=0,objectIndex=0;
      const heads=async()=>{
        if(state.stopped)return;
        try{
          const result=await request<HeadResult>('POST',`/api/device-camera/${state.run}/room/head/frame`,{
            query:{frame_index:headIndex++},rawBody:await sample(),signal:AbortSignal.any([state.abort.signal,AbortSignal.timeout(20000)])});
          if(state.stopped)return;
          setPoses(result.seats);setImageSize(result.image_size);setHeadError(result.alert_error||'');
          setCalibrating(result.seats.some(s=>s.calibrating));
          if(result.alerts.length)setSaved(n=>n+result.alerts.length);
        }catch(reason){failed(reason,true);}
        schedule(()=>void heads(),200);
      };
      const checkObjects=async()=>{
        if(state.stopped)return;
        try{
          const result=await request<ObjectResult>('POST',`/api/device-camera/${state.run}/room/frame`,{
            query:{frame_index:objectIndex++},rawBody:await sample(),signal:AbortSignal.any([state.abort.signal,AbortSignal.timeout(45000)])});
          if(state.stopped)return;
          setObjects(result.objects);
          const savedCount=result.alerts?.length??(result.alert?1:0);if(savedCount)setSaved(n=>n+savedCount);
          const decision:Record<string,string>={saved:'Review alert saved',cooldown:'Verified; repeat alert cooldown active',
            below_review_cutoff:'Below the administrator’s composite review cutoff',below_signal_threshold:'Below the administrator’s signal threshold',
            confirming:`${result.review_observations}/3 recognitions; hold the object visible`,no_verified_object:'No verified phone or book'};
          setObjectMessage(result.alert_error||result.warning||`${result.checked_seat===null?'Whole classroom checked':`Detail check: seat ${result.checked_seat}`} · ${result.ai_seconds.toFixed(1)}s · ${result.mapped_seats} mapped seats · ${decision[result.review_status]||''}`);
          // Returned boxes refer to a sampled frame; expire them rather than
          // retaining a stale box on a different student between slow checks.
          schedule(()=>setObjects([]),Math.min(6000,Math.max(1000,result.ai_seconds*1000)));
        }catch(reason){failed(reason,false);}
        schedule(()=>void checkObjects(),500);
      };
      void heads();void checkObjects();
    }catch(reason){if(!state.stopped)setError((reason as Error).message);}
    finally{if(mounted.current)setStarting(false);}
  };
  const calibrate=async()=>{
    const state=capture.current;if(!state?.run)return;
    setCalibrating(true);setHeadError('');
    try{await request('POST',`/api/device-camera/${state.run}/head/calibrate`,{signal:state.abort.signal});}
    catch(reason){if(!state.stopped){setHeadError((reason as Error).message);setCalibrating(false);}}
  };
  const point=(event:React.PointerEvent<SVGSVGElement>)=>{
    const bounds=event.currentTarget.getBoundingClientRect();
    return [Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width)),Math.max(0,Math.min(1,(event.clientY-bounds.top)/bounds.height))];
  };
  const finish=(event:React.PointerEvent<SVGSVGElement>)=>{
    const start=dragStart.current;dragStart.current=null;setDrag(null);if(!start)return;
    const end=point(event),box=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];
    if(box[2]-box[0]<.025||box[3]-box[1]<.025){setError('Draw a larger region around this student’s face and desk.');return;}
    const number=Number(selected),other=regions.filter(r=>r.seat_number!==number);
    if(other.some(r=>Math.min(box[2],r.box[2])>Math.max(box[0],r.box[0])+1e-5&&Math.min(box[3],r.box[3])>Math.max(box[1],r.box[1])+1e-5)){
      setError('Seat regions overlap. Leave a gap so detections cannot be assigned to two students.');return;}
    setRegions([...other,{seat_number:number,box}]);setError('');
    const next=assignments.find(s=>s.seat_number!==number&&!other.some(r=>r.seat_number===s.seat_number));
    if(next)setSelected(String(next.seat_number));
  };
  const regionRect=(region:Region,draft=false)=>{
    const [x,y,x2,y2]=region.box,focused=String(region.seat_number)===inspect;
    return <g key={draft?'draft':region.seat_number}><rect x={x} y={y} width={x2-x} height={y2-y} fill={draft?'#60a5fa22':focused?'#60a5fa33':'transparent'} stroke={draft||focused?'#60a5fa':'#ffffff88'} strokeWidth={focused ? .004 : .002}/>{!draft&&<text x={x+.008} y={y+.024} fill="white" fontSize=".02" stroke="black" strokeWidth=".001">Seat {region.seat_number}</text>}</g>;
  };
  return <section aria-label="Whole classroom camera" className="rounded-[6px] border border-(--color-border-default) bg-(--color-bg-surface) overflow-hidden mb-4">
    <div className="p-4 flex flex-wrap items-center gap-3"><h2 className="text-heading">Whole classroom camera</h2>
      <span className="text-label text-(--color-text-muted)">{phase==='running'?`${regions.length} seats monitored`:phase==='mapping'?'Align seats with the camera view':'Camera stopped'}</span>
      <div className="ml-auto flex gap-2 flex-wrap">
        {devices.length>1&&<Select aria-label="Room camera device" value={device} disabled={phase!=='stopped'} onChange={e=>{setDevice(e.target.value);setRegions([]);}}><option value="">Default room camera</option>{devices.map(d=><option key={d.deviceId} value={d.deviceId}>{d.label||'Camera'}</option>)}</Select>}
        <Button disabled={phase==='opening'||!active||!assignments.length||assignments.length>64} onClick={()=>phase==='stopped'?void open():stop()}>{phase==='stopped'?'Open room camera':phase==='opening'?'Opening camera…':'Stop camera'}</Button>
      </div>
    </div>
    <div className="relative bg-black" style={{aspectRatio:ratio}}>
      <video ref={video} muted playsInline autoPlay className="w-full h-full" aria-label="Live classroom camera"/>
      <svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-label="Camera seat region mapping" className={`absolute inset-0 w-full h-full ${phase==='mapping'?'cursor-crosshair touch-none':'pointer-events-none'}`}
        onPointerDown={e=>{if(phase!=='mapping'||!selected)return;dragStart.current=point(e);e.currentTarget.setPointerCapture(e.pointerId);setDrag([...dragStart.current,...dragStart.current]);}}
        onPointerMove={e=>{if(dragStart.current)setDrag([...dragStart.current,...point(e)]);}} onPointerUp={finish} onPointerCancel={()=>{dragStart.current=null;setDrag(null);}}>
        {regions.map(r=>regionRect(r))}{drag&&regionRect({seat_number:0,box:[Math.min(drag[0],drag[2]),Math.min(drag[1],drag[3]),Math.max(drag[0],drag[2]),Math.max(drag[1],drag[3])]},true)}
        {objects.map(o=><g key={`${o.seat_number}-${o.track_id}`}><rect x={o.box[0]} y={o.box[1]} width={o.box[2]-o.box[0]} height={o.box[3]-o.box[1]} fill="none" stroke="#fbbf24" strokeWidth=".003"/><text x={o.box[0]} y={Math.max(.025,o.box[1]-.008)} fontSize=".022" fill="#fbbf24" stroke="black" strokeWidth=".001">{o.label} · Seat {o.seat_number} · {Math.round(o.confidence*100)}%</text></g>)}
        {poses.filter(p=>p.face_box).map(p=>{const [x,y,x2,y2]=p.face_box!.map((v,i)=>v/imageSize[i%2]);return <rect key={p.seat_number} x={x} y={y} width={x2-x} height={y2-y} fill="none" stroke={p.sustained?'#f87171':p.violating?'#fbbf24':'#86efac'} strokeWidth=".003"/>;})}
      </svg>
      {phase==='stopped'&&<p className="absolute inset-0 grid place-items-center p-6 text-white/70 text-center">{active?'Position one fixed camera to view the classroom, then open it here.':'Camera monitoring is available during an active exam.'}</p>}
    </div>
    <div className="p-4 space-y-3">
      {phase==='mapping'&&<><p className="text-body-sm">Choose a CSV seat and drag a region around that student’s face and desk. Leave gaps between students. The CSV identifies students; these regions identify their location in this camera view.</p>
        <p className="text-label text-(--color-text-muted)">Saved regions can be reused on this camera and browser tab. Check that they still match the current view before beginning.</p>
        <div className="flex flex-wrap items-center gap-2"><Select aria-label="Seat to map in camera" value={selected} onChange={e=>setSelected(e.target.value)}>{assignments.map(s=><option key={s.seat_number} value={s.seat_number}>Seat {s.seat_number} · {s.student_name} {regions.some(r=>r.seat_number===s.seat_number)?'✓':''}</option>)}</Select>
          <Button variant="secondary" onClick={()=>setRegions(r=>r.filter(s=>s.seat_number!==Number(selected)))}>Clear this region</Button>
          <span className="text-label">{regions.length}/{assignments.length} mapped</span>
          <Button disabled={starting||regions.length!==assignments.length} onClick={()=>void begin()}>{starting?'Starting…':'Begin room monitoring'}</Button></div></>}
      {phase==='running'&&<><div className="flex flex-wrap items-center gap-2"><Select aria-label="Inspect seat (view only)" value={inspect} onChange={e=>setInspect(e.target.value)}><option value="">Whole classroom</option>{assignments.map(s=><option key={s.seat_number} value={s.seat_number}>Inspect seat {s.seat_number} · {s.student_name}</option>)}</Select>
        <Button variant="secondary" disabled={calibrating} onClick={()=>void calibrate()}>{calibrating?'Calibrating…':'Set neutral for all seats'}</Button></div>
        <p className="text-body-sm" role="status">{objectMessage}</p>
        <p className="text-body-sm">{poses.filter(p=>p.calibrated).length}/{assignments.length} head poses calibrated. Ask students to face forward and hold still while setting neutral.</p>
        <div className="max-h-56 overflow-auto grid gap-2 sm:grid-cols-2">{poses.filter(p=>!inspect||String(p.seat_number)===inspect).map(p=><p key={p.seat_number} className={`text-body-sm ${p.sustained?'text-(--color-error)':''}`}>Seat {p.seat_number} · {poseLabel[p.state]||p.state}{p.sustained&&!p.review_enabled?' · below administrator’s review policy':''}{p.calibrating?` ${Math.round(p.calibration_progress*100)}%`:p.yaw!==null?` · yaw ${p.yaw.toFixed(0)}° · pitch ${p.pitch?.toFixed(0)}°`:''}</p>)}</div></>}
      {!!saved&&<p role="status" className="text-body-sm text-(--color-success)">{saved} live {saved===1?'alert':'alerts'} saved to this exam’s review workflow.</p>}
      {!assignments.length&&<p className="text-body-sm text-(--color-warning)">Upload a fully resolved student seating CSV before monitoring.</p>}
      {assignments.length>64&&<p className="text-body-sm text-(--color-warning)">This hosted camera supports up to 64 mapped seats per room.</p>}
      <p className="text-label text-(--color-text-muted)">Keep the camera fixed after mapping. All seats share this camera; inspecting a seat only highlights its region. Head pose is checked independently for each visible face. Object checks scan the whole classroom, with seat detail checks for smaller objects, and need three recognitions spanning at least three seconds. Small or obscured faces, and objects on seat boundaries, cannot create attributed alerts. Check scan timing and camera detail before an exam; alerts require human review.</p>
      {(error||headError)&&<p role="alert" className="text-body-sm text-(--color-error)">{error||headError}</p>}
    </div>
  </section>;
}
