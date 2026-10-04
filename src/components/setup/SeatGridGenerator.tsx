import { useId, useState } from 'react';
import { Grid3X3 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { FormField, Input } from '@/components/ui/FormElements';
import { Modal } from '@/components/ui/Modal';
import { seatGrid, seatingPlanSvg } from '@/lib/setup-assets';
import type { SeatPolygon } from '@/lib/types';

export function SeatGridGenerator({capacity,hasSeats,onGenerate}:{capacity:number;hasSeats:boolean;onGenerate:(seats:SeatPolygon[])=>void}) {
  const [open,setOpen]=useState(false);
  const [seatInput,setSeatInput]=useState('30');
  const [columnInput,setColumnInput]=useState('5');
  const id=useId();
  const seats=Number(seatInput),columns=Number(columnInput);
  const invalid=!Number.isInteger(seats)||seats<1||seats>Math.min(capacity,200)||!Number.isInteger(columns)||columns<1||columns>20;
  const svg=invalid?'':seatingPlanSvg({seats,columns,room:'Camera polygon draft'});
  return <>
    <Button variant="secondary" size="sm" onClick={()=>{setSeatInput(String(Math.min(capacity,200)));setColumnInput(String(Math.min(capacity,5)));setOpen(true);}}><Grid3X3 size={14}/>Generate seat grid</Button>
    <Modal isOpen={open} onClose={()=>setOpen(false)} title="Generate a seat grid" size="lg" footer={<><Button variant="secondary" onClick={()=>setOpen(false)}>Cancel</Button><Button disabled={invalid} onClick={()=>{onGenerate(seatGrid(seats,columns));setOpen(false);}}>{hasSeats?'Replace draft with grid':'Create draft grid'}</Button></>}>
      <p className="text-body-sm text-(--color-text-secondary) mb-4">Start with numbered rectangular seats in the editor. Adjust the layout to the actual camera view before saving.</p>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <FormField label="Number of seats" htmlFor={`${id}-seats`}><Input id={`${id}-seats`} type="number" min={1} max={Math.min(capacity,200)} value={seatInput} onChange={e=>setSeatInput(e.target.value)}/></FormField>
        <FormField label="Columns" htmlFor={`${id}-columns`}><Input id={`${id}-columns`} type="number" min={1} max={20} value={columnInput} onChange={e=>setColumnInput(e.target.value)}/></FormField>
      </div>
      {invalid?<p role="alert" className="text-label text-(--color-error)">Choose 1–{Math.min(capacity,200)} seats and 1–20 columns.</p>:<img className="setup-plan-image" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`} alt={`Draft grid with ${seats} seats and ${columns} columns`}/>}
      {hasSeats&&<p className="text-body-sm text-(--color-warning) mt-4">This replaces the current editor draft. Your saved classroom map changes only when you select Save map.</p>}
    </Modal>
  </>;
}
