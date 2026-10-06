import { useState } from 'react';
import type { SessionSeatMap } from '@/lib/api';
import type { DetectionEvent } from '@/lib/types';

export function SessionSeatPlan({map,detections,perspective,onReview}:{map:SessionSeatMap;detections:DetectionEvent[];
  perspective:boolean;onReview:(event:DetectionEvent)=>void}) {
  const [selected,setSelected]=useState<number|null>(null);
  const assignments=new Map(map.assignments.map(s=>[s.seat_number,s]));
  const alerts=new Map<number,DetectionEvent>();
  for(const event of detections){
    if(assignments.get(event.seatNumber)?.student_id!==event.studentId)continue;
    if(event.status!=='New'&&event.status!=='Reviewed')continue;
    const old=alerts.get(event.seatNumber);
    if(!old||event.compositeScore>old.compositeScore)alerts.set(event.seatNumber,event);
  }
  const title=(number:number)=>{const student=assignments.get(number),alert=alerts.get(number);
    return `Seat ${number} · ${student?`${student.student_name||'Student'} · ${student.registration_no}${student.active?'':' · inactive account'}`:'Unassigned'}${alert?` · Review score ${Math.round(alert.compositeScore*100)}%`:''}`;};
  const choose=(number:number)=>{setSelected(number);const alert=alerts.get(number);if(alert)onReview(alert);};
  const student=selected===null?null:assignments.get(selected);
  const vertices=map.polygons.flatMap(p=>p.vertices);
  const width=Math.max(1,...vertices.map(p=>p.x)),height=Math.max(1,...vertices.map(p=>p.y));
  return <section aria-label="CSV classroom seating plan" className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-4">
    <div className="flex items-center justify-between mb-3 gap-2"><h2 className="text-heading">Classroom seating plan</h2><span className="text-label text-(--color-text-muted)">{map.assignments.length} CSV assignments · {map.capacity} seats · {alerts.size} seats with review alerts</span></div>
    {!!map.polygons.length&&<svg aria-label="Saved classroom layout" viewBox={`0 0 ${width*1.05} ${height*1.05}`} className="w-full max-h-80 mb-4" style={{transform:perspective?'perspective(900px) rotateX(25deg)':undefined}}>
      {map.polygons.map(p=>{const assigned=assignments.has(p.seat_number),alert=alerts.has(p.seat_number);
        const cx=p.vertices.reduce((sum,v)=>sum+v.x,0)/p.vertices.length,cy=p.vertices.reduce((sum,v)=>sum+v.y,0)/p.vertices.length;
        return <g key={p.seat_number} role="button" tabIndex={0} aria-label={title(p.seat_number)} onClick={()=>choose(p.seat_number)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(p.seat_number);}}} className="cursor-pointer">
          <title>{title(p.seat_number)}</title><polygon points={p.vertices.map(v=>`${v.x},${v.y}`).join(' ')} fill={alert?'var(--color-error-subtle)':assigned?'var(--color-accent-subtle)':'var(--color-bg-surface-raised)'} stroke={alert?'var(--color-error)':assigned?'var(--color-accent-primary)':'var(--color-border-default)'} strokeWidth={width*.002}/>
          <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle" fontSize={width*.018} fill="var(--color-text-primary)">{p.seat_number}</text></g>;
      })}
    </svg>}
    <p className="text-label text-(--color-text-muted) mb-3">{map.polygons.length?'Saved room layout above; CSV identities below.':'Seat order below follows the CSV numbers. Map actual camera regions above before room monitoring.'}</p>
    <div className="grid gap-2 max-h-[480px] overflow-auto" style={{gridTemplateColumns:`repeat(${Math.max(1,Math.min(6,Math.ceil(Math.sqrt(map.capacity))))},minmax(0,1fr))`,transform:perspective&&!map.polygons.length?'perspective(900px) rotateX(15deg)':undefined}}>
      {Array.from({length:map.capacity},(_,i)=>i+1).map(number=>{const assigned=assignments.get(number),alert=alerts.get(number);
        return <button key={number} aria-label={title(number)} aria-pressed={selected===number} title={title(number)} onClick={()=>choose(number)} className="rounded-[4px] px-2 py-3 text-left border transition-colors cursor-pointer min-w-0"
          style={{background:alert?'var(--color-error-subtle)':assigned?'var(--color-accent-subtle)':'var(--color-bg-surface-raised)',borderColor:alert?'var(--color-error)':assigned?'var(--color-accent-primary)':'var(--color-border-default)'}}>
          <span className="block text-label font-semibold">Seat {number}{alert?' · alert':''}</span><span className="block text-label truncate text-(--color-text-secondary)">{assigned?.student_name||'Unassigned'}</span>
          {assigned&&<span className="block text-label text-(--color-text-muted)">{assigned.registration_no}{!assigned.active?' · inactive':''}</span>}
        </button>;
      })}
    </div>
    {selected!==null&&<p role="status" className="text-body-sm mt-3">Seat {selected} · {student?`${student.student_name||'Student'} · ${student.registration_no}${student.active?'':' · inactive'}`:'No CSV student assigned'}</p>}
    <div className="flex flex-wrap gap-4 mt-3 text-label text-(--color-text-muted)"><span>Blue: CSV student assigned</span><span>Grey: unassigned</span><span>Red: review alert</span></div>
  </section>;
}
