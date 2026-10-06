import { useEffect, useState } from 'react';
import type { CameraObject } from '@/lib/vision/object-tracking';

export interface CheckedObjectSample {
  image:Blob;
  objects:(CameraObject&{seat_number?:number})[];
  capturedAt:number;
  checkedAt:number;
}

/** Exact image/boxes checked by the server, distinct from the moving preview. */
export function CheckedObjectFrame({sample}:{sample:CheckedObjectSample|null}) {
  const [display,setDisplay]=useState<{url:string;sample:CheckedObjectSample}|null>(null);
  useEffect(()=>{
    if(!sample){setDisplay(null);return;}
    const next=URL.createObjectURL(sample.image);setDisplay({url:next,sample});
    return()=>URL.revokeObjectURL(next);
  },[sample]);
  if(!sample||display?.sample!==sample)return null;
  return <figure aria-label="Last checked object frame" className="rounded border border-(--color-border-default) overflow-hidden">
    <figcaption className="p-3 text-body-sm">
      <p className="font-medium">Latest object check</p>
      <p>{sample.objects.map(o=>`${o.label==='phone'?'Phone':'Book'} ${Math.round(o.confidence*100)}%${o.seat_number!==undefined?` · Seat ${o.seat_number}`:''}`).join(' · ')}</p>
      <p className="text-label text-(--color-text-muted)">Captured {new Date(sample.capturedAt).toLocaleTimeString()} · checked {((sample.checkedAt-sample.capturedAt)/1000).toFixed(1)}s later. Live boxes follow the object when its appearance can be matched.</p>
    </figcaption>
    <div className="relative mx-auto max-w-sm bg-black">
      <img src={display.url} alt="Camera frame checked for phones and books" className="block w-full"/>
      <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="absolute inset-0 h-full w-full pointer-events-none" aria-label="Verified object locations in the checked frame">
        {sample.objects.map(o=><g key={`${o.seat_number??''}-${o.track_id}`}><rect x={o.box[0]} y={o.box[1]} width={o.box[2]-o.box[0]} height={o.box[3]-o.box[1]} fill="none" stroke={o.label==='phone'?'#f87171':'#fbbf24'} strokeWidth=".008"/></g>)}
      </svg>
    </div>
  </figure>;
}
