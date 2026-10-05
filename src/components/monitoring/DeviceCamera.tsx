import { useCallback, useEffect, useRef, useState } from 'react';
import { request } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/FormElements';
import type { HeadState } from '@/lib/vision/head-pose';
import { ObjectOverlayTracker, type CameraObject } from '@/lib/vision/object-tracking';

type Seat={seat_number:number;student_name:string;registration_no:string};
type SampleResult={objects:CameraObject[];ai_seconds:number;alert:unknown|null;alert_error:string|null};
interface Capture {
  stream:MediaStream;worker:Worker;controller:AbortController;run:string|null;
  head:HeadState|null;ready:boolean;headPending:boolean;stopped:boolean;
  timers:Set<number>;tracker:ObjectOverlayTracker;
}
const headLabels:Record<string,string>={
  calibration_required:'Face forward in your normal exam posture, then set neutral pose.',
  calibrating:'Hold still while neutral posture is recorded.',face_forward_to_calibrate:'Face forward and hold still.',
  no_face:'Face not visible',multiple_faces:'Keep only the monitored student in view.',
  face_too_small:'Move closer so your face is clear.',unreliable_face:'Face tracking uncertain',
  neutral:'Head pose within limits',turning:'Checking sustained head movement',sustained:'Sustained head-pose warning',
};
function cameraError(reason:unknown) {
  const error=reason as {name?:string;message?:string};
  if(error.name==='NotAllowedError')return 'Camera access was denied. Allow camera access for this website in browser settings, then retry.';
  if(error.name==='NotFoundError')return 'No camera was found on this device.';
  if(error.name==='NotReadableError')return 'The camera is in use. Close other camera apps, then retry.';
  return error.message||'Camera could not start.';
}
function blob(canvas:HTMLCanvasElement){return new Promise<Blob>((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(Error('Could not capture camera sample.')),'image/jpeg',.85));}

export function DeviceCamera({sessionId,active=true}:{sessionId?:string;active?:boolean}) {
  const video=useRef<HTMLVideoElement>(null),overlay=useRef<HTMLCanvasElement>(null);
  const capture=useRef<Capture|null>(null),mounted=useRef(true),starting=useRef(false);
  const [seats,setSeats]=useState<Seat[]>([]),[seat,setSeat]=useState('');
  const [devices,setDevices]=useState<MediaDeviceInfo[]>([]),[device,setDevice]=useState('');
  const [phase,setPhase]=useState<'stopped'|'starting'|'running'>('stopped');
  const [error,setError]=useState(''),[objectMessage,setObjectMessage]=useState('');
  const [objects,setObjects]=useState<CameraObject[]>([]),[head,setHead]=useState<HeadState|null>(null);
  const [headError,setHeadError]=useState(''),[seconds,setSeconds]=useState<number|null>(null),[saved,setSaved]=useState(false);

  const stop=useCallback((message='')=>{
    const state=capture.current;capture.current=null;
    if(state){
      state.stopped=true;state.controller.abort();state.worker.terminate();
      state.timers.forEach(window.clearTimeout);state.stream.getTracks().forEach(track=>track.stop());
      if(state.run)void request('POST',`/api/device-camera/${state.run}/stop`,{keepalive:true}).catch(()=>{});
    }
    if(video.current)video.current.srcObject=null;
    const context=overlay.current?.getContext('2d');if(context)context.clearRect(0,0,context.canvas.width,context.canvas.height);
    if(mounted.current){setPhase('stopped');setHead(null);setObjects([]);setObjectMessage('');if(message)setError(message);}
  },[]);
  useEffect(()=>{
    mounted.current=true;
    const hidden=()=>{if(document.hidden)stop('Camera stopped because this tab is hidden. Return here and start again.');};
    const leaving=()=>stop();
    document.addEventListener('visibilitychange',hidden);
    window.addEventListener('pagehide',leaving);
    return()=>{mounted.current=false;document.removeEventListener('visibilitychange',hidden);window.removeEventListener('pagehide',leaving);stop();};
  },[stop]);
  useEffect(()=>{if(!active)stop();},[active,stop]);
  useEffect(()=>{
    if(!sessionId)return;
    let cancelled=false;
    request<Seat[]>('GET',`/api/sessions/${sessionId}/device-camera/seats`).then(value=>{if(!cancelled)setSeats(value);}).catch(reason=>{if(!cancelled)setError(reason.message);});
    return()=>{cancelled=true;stop();};
  },[sessionId,stop]);

  const start=async()=>{
    if(starting.current||capture.current)return;
    starting.current=true;setPhase('starting');setError('');setHeadError('');setSaved(false);setSeconds(null);setObjects([]);
    let stream:MediaStream|null=null;
    try{
      if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw Error('Open this page using HTTPS or localhost to access the device camera.');
      stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{width:{ideal:1280},height:{ideal:720},frameRate:{ideal:30,max:30},...(device?{deviceId:{exact:device}}:{facingMode:{ideal:'user'}})}});
      if(!mounted.current||document.hidden){stream.getTracks().forEach(track=>track.stop());return;}
      const worker=new Worker('/vision/head.worker.js');
      const state:Capture={stream,worker,controller:new AbortController(),run:null,head:null,ready:false,headPending:false,stopped:false,timers:new Set(),tracker:new ObjectOverlayTracker()};
      capture.current=state;
      stream.getVideoTracks()[0].onended=()=>stop('The device camera disconnected.');
      worker.onmessage=event=>{
        if(capture.current!==state)return;
        if(event.data.type==='ready')state.ready=true;
        if(event.data.type==='pose'){state.headPending=false;state.head=event.data.status;setHead(event.data.status);}
        if(event.data.type==='error'){state.headPending=false;setHeadError('Head tracking could not run on this browser. '+event.data.message);}
      };
      worker.onerror=()=>{if(capture.current===state)setHeadError('Head tracking could not load. Stop the camera and retry.');};
      video.current!.srcObject=stream;await video.current!.play();
      const available=await navigator.mediaDevices.enumerateDevices();if(capture.current!==state)return;
      setDevices(available.filter(value=>value.kind==='videoinput'));
      worker.postMessage({type:'init',origin:window.location.origin});setPhase('running');setObjectMessage('Loading the phone and book checker…');
      const drawCanvas=document.createElement('canvas');drawCanvas.width=320;
      const drawContext=drawCanvas.getContext('2d',{willReadFrequently:true})!;
      const schedule=(fn:()=>void,delay:number)=>{if(!state.stopped){const timer=window.setTimeout(()=>{state.timers.delete(timer);fn();},delay);state.timers.add(timer);}};
      const draw=async()=>{
        if(state.stopped)return;
        const source=video.current,canvas=overlay.current;
        if(source&&canvas&&source.videoWidth){
          const ratio=source.videoHeight/source.videoWidth;drawCanvas.height=Math.round(320*ratio);
          drawContext.drawImage(source,0,0,drawCanvas.width,drawCanvas.height);
          const current=drawContext.getImageData(0,0,drawCanvas.width,drawCanvas.height),tracked=state.tracker.update(current,performance.now());
          canvas.width=source.videoWidth;canvas.height=source.videoHeight;
          const context=canvas.getContext('2d')!;context.lineWidth=3;context.font='18px sans-serif';
          const drawBox=(box:number[],color:string,label:string)=>{
            const [x,y,x2,y2]=box.map((v,i)=>v*(i%2?canvas.height:canvas.width));
            context.strokeStyle=color;context.strokeRect(x,y,x2-x,y2-y);
            context.fillStyle='rgba(0,0,0,.8)';context.fillRect(x,Math.max(0,y-27),Math.max(120,context.measureText(label).width+14),27);
            context.fillStyle=color;context.fillText(label,x+7,Math.max(20,y-7));
          };
          tracked.forEach(object=>drawBox(object.box,object.label==='phone'?'#f87171':'#fbbf24',`${object.label==='phone'?'Phone':'Book'} ${Math.round(object.confidence*100)}%${object.confirmed?'':' · checking'}`));
          if(state.head?.box)drawBox(state.head.box,state.head.sustained?'#f87171':state.head.violating?'#fbbf24':'#86efac','Head pose');
          if(state.ready&&!state.headPending){
            state.headPending=true;
            try{
              const width=Math.min(960,source.videoWidth),height=Math.round(width*ratio),bitmap=await createImageBitmap(source,{resizeWidth:width,resizeHeight:height});
              if(!state.stopped)worker.postMessage({type:'frame',bitmap,timestamp:performance.now()},[bitmap]);else bitmap.close();
            }catch(reason){state.headPending=false;setHeadError('Could not capture a head-tracking frame. '+cameraError(reason));}
          }
        }
        schedule(()=>void draw(),120);
      };
      void draw();
      const result=await request<{run_id:string}>('POST',sessionId?`/api/sessions/${sessionId}/device-camera/start`:'/api/device-camera/check/start',sessionId?{body:{seat_number:Number(seat)}}:{});
      state.run=result.run_id;
      if(state.stopped){void request('POST',`/api/device-camera/${state.run}/stop`).catch(()=>{});return;}
      let index=0;
      const sample=async()=>{
        if(state.stopped)return;
        const source=video.current!,sampleCanvas=document.createElement('canvas'),ratio=Math.min(1,1280/source.videoWidth,1200/source.videoHeight);
        sampleCanvas.width=Math.round(source.videoWidth*ratio);sampleCanvas.height=Math.round(source.videoHeight*ratio);
        sampleCanvas.getContext('2d')!.drawImage(source,0,0,sampleCanvas.width,sampleCanvas.height);
        const reference=document.createElement('canvas');reference.width=320;reference.height=Math.round(320*source.videoHeight/source.videoWidth);
        const context=reference.getContext('2d',{willReadFrequently:true})!;context.drawImage(sampleCanvas,0,0,reference.width,reference.height);
        const image=context.getImageData(0,0,reference.width,reference.height);
        try{
          const result=await request<SampleResult>('POST',`/api/device-camera/${state.run}/frame`,{query:{frame_index:index++,head_sustained:state.head?.sustained??false},rawBody:await blob(sampleCanvas),signal:AbortSignal.any([state.controller.signal,AbortSignal.timeout(45000)])});
          if(state.stopped)return;
          state.tracker.set(result.objects,image,performance.now());setObjects(result.objects);setSeconds(result.ai_seconds);
          setObjectMessage(result.alert_error||(result.objects.length?'':'Checking for phones and books…'));if(result.alert)setSaved(true);
        }catch(reason){
          if(state.stopped)return;
          const failure=reason as {status?:number;message:string};
          if([401,403,404,409,410].includes(failure.status??0)){stop(failure.message);return;}
          setObjectMessage(failure.status===429?'Object checker busy; retrying…':failure.message);state.tracker.patches=[];setObjects([]);
        }
        schedule(()=>void sample(),500);
      };
      void sample();
    }catch(reason){stream?.getTracks().forEach(track=>track.stop());stop();if(mounted.current)setError(cameraError(reason));}
    finally{starting.current=false;if(mounted.current&&!capture.current)setPhase('stopped');}
  };

  return <section className="pa-camera rounded-[6px] border border-(--color-border-default) bg-(--color-bg-surface) overflow-hidden" aria-label="Device camera monitoring">
    <div className="p-4 flex flex-wrap items-center gap-3"><h2 className="text-heading">{sessionId?'Live exam camera':'Check your device camera'}</h2><span className="text-label text-(--color-text-muted)">{phase==='running'?'Device camera live':phase==='starting'?'Opening camera…':'Camera stopped'}</span>
      <div className="ml-auto flex flex-wrap gap-2">
        {sessionId&&<Select aria-label="Monitored student seat" value={seat} disabled={phase!=='stopped'||!active} onChange={event=>setSeat(event.target.value)}><option value="">Select student seat</option>{seats.map(value=><option key={value.seat_number} value={value.seat_number}>Seat {value.seat_number} · {value.student_name}</option>)}</Select>}
        {devices.length>1&&<Select aria-label="Device camera" value={device} disabled={phase!=='stopped'} onChange={event=>setDevice(event.target.value)}><option value="">Default camera</option>{devices.map(value=><option key={value.deviceId} value={value.deviceId}>{value.label||'Camera'}</option>)}</Select>}
        <Button disabled={phase==='starting'||!active||(!!sessionId&&!seat)} onClick={()=>phase==='running'?stop():void start()}>{phase==='running'?'Stop camera':'Start camera'}</Button>
      </div>
    </div>
    <div className="relative bg-black aspect-video"><video ref={video} muted playsInline autoPlay aria-label="Live device camera" className="w-full h-full object-contain" /><canvas ref={overlay} aria-label="Live head pose and object overlays" className="absolute inset-0 w-full h-full object-contain pointer-events-none" />{phase==='stopped'&&<div className="absolute inset-0 grid place-items-center p-6 text-center text-white/70">{active?'Start camera and allow access in your browser.':'Camera monitoring is available during an active exam.'}</div>}</div>
    <div className="p-4 space-y-3">
      {sessionId&&!seats.length&&<p className="text-body-sm text-(--color-warning)">Assign registered students to the exam seats before monitoring.</p>}
      <p className="text-body-sm" aria-live="polite">{objects.map(value=>`${value.label==='phone'?'Phone':'Book'} · ${Math.round(value.confidence*100)}%${value.confirmed?'':' · checking'}`).join(' · ')||objectMessage||'Phone and book detection ready'}{seconds!==null&&<span className="ml-2 text-(--color-text-muted)">Object check: {seconds.toFixed(1)}s</span>}</p>
      {!!objects.length&&objectMessage&&<p role="status" className="text-body-sm text-(--color-warning)">{objectMessage}</p>}
      <div className="flex flex-wrap justify-between items-center gap-3"><p className={`text-body-sm ${head?.sustained?'text-(--color-error)':head?.violating?'text-(--color-warning)':''}`} aria-live="polite">{head?headLabels[head.state]||head.state:phase==='running'?'Loading head tracking…':'Set neutral after starting the camera.'}{head?.calibrating&&` ${Math.round(head.calibration_progress*100)}%`}</p><Button variant="secondary" disabled={phase!=='running'||!head||head.calibrating||!!headError} onClick={()=>capture.current?.worker.postMessage({type:'calibrate'})}>{head?.calibrated?'Recalibrate':'Set neutral pose'}</Button></div>
      {head?.yaw!==null&&head?.yaw!==undefined&&<div className="grid grid-cols-3 gap-3 text-body-sm tabular-nums">{([['Yaw',head.yaw],['Pitch',head.pitch],['Roll',head.roll]] as const).map(([label,value])=><p key={label}>{label} {value!==null?`${value>0?'+':''}${value.toFixed(1)}°`:'—'}</p>)}</div>}
      {saved&&<p className="text-body-sm text-(--color-success)">Confirmed object evidence saved to this exam’s review workflow.</p>}
      <p className="text-label text-(--color-text-muted)">{sessionId?'One registered student per camera view.':'Equipment check only: no exam evidence or cases are saved.'} Head tracking runs on this device. Sampled images go to the hosted object checker. Set neutral while facing forward for two seconds. Sideways turns over 30° or looking down over 20° require two continuous seconds. Head pose alone is a warning.</p>
      {(error||headError)&&<p role="alert" className="text-body-sm text-(--color-error)">{error||headError}</p>}
    </div>
  </section>;
}
