import { useId, useState, type MouseEvent } from 'react';
import { Download, Grid3X3, FileSpreadsheet, ArrowRight, CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { FormField, Input, TextArea } from '@/components/ui/FormElements';
import { SETUP_GUIDE, SETUP_TEMPLATES, downloadSetupFile, polygonJson, registrationNumbers, seatAssignmentCsv, seatingPlanSvg, validateAssignments } from '@/lib/setup-assets';
import starterKitUrl from '@/assets/setup-kit/proctorai-setup-kit.zip?url';
import { Link } from 'react-router-dom';
import { useAuth } from '@/lib/auth-context';
import { Role } from '@/lib/types';

interface SetupToolkitProps { capacity?:number; roomName?:string; onUseCsv?:(file:File)=>Promise<void>; }

export function SetupToolkit({capacity,roomName='Classroom',onUseCsv}:SetupToolkitProps) {
  const {user}=useAuth();
  const [open,setOpen]=useState(false);
  const [seatInput,setSeatInput]=useState('30');
  const [columnInput,setColumnInput]=useState('5');
  const [room,setRoom]=useState(roomName);
  const [roster,setRoster]=useState('');
  const [using,setUsing]=useState(false);
  const [notice,setNotice]=useState('');
  const [kitDownloading,setKitDownloading]=useState(false);
  const [kitError,setKitError]=useState('');
  const fieldId=useId();
  const seats=Number(seatInput), columns=Number(columnInput);
  const ids=registrationNumbers(roster);
  const layoutError= !Number.isInteger(seats)||seats<1||seats>200||!Number.isInteger(columns)||columns<1||columns>20 ? 'Choose 1–200 seats and 1–20 columns.' : undefined;
  const assignmentError=layoutError || (capacity!==undefined&&seats>capacity?`The selected classroom has capacity ${capacity}. Reduce the seat count.`:undefined) || validateAssignments(ids,seats);
  const svg=layoutError ? '' : seatingPlanSvg({seats,columns,room},ids);
  const openToolkit=()=>{ const roomSeats=capacity??30; setSeatInput(String(Math.min(200,Math.max(1,roomSeats)))); setColumnInput(String(Math.min(5,Math.max(1,roomSeats)))); setRoom(roomName); setNotice('');setOpen(true); };
  const download=(name:string,content:string,type?:string)=>{downloadSetupFile(name,content,type);setNotice(`${name} prepared for download.`);};
  const downloadKit=async(e:MouseEvent<HTMLAnchorElement>)=>{
    e.preventDefault();
    if (kitDownloading) return;
    setKitDownloading(true);setKitError('');
    try {
      const response=await fetch(starterKitUrl);
      if (!response.ok) throw new Error('Could not download the starter kit. Please try again.');
      downloadSetupFile('proctorai-setup-kit.zip',await response.blob());
      setNotice('proctorai-setup-kit.zip prepared for download.');
    } catch {setKitError('Could not download the starter kit. Please try again.');}
    finally {setKitDownloading(false);}
  };
  const useCsv=async()=>{
    if (!onUseCsv || assignmentError || !ids.length) return;
    setUsing(true);
    try { await onUseCsv(new File([seatAssignmentCsv(seats,ids)],'seat-assignments.csv',{type:'text/csv'})); setOpen(false); }
    finally {setUsing(false);}
  };
  return <>
    <Button variant="secondary" onClick={openToolkit}><Grid3X3 size={16}/>Setup templates & seat generator</Button>
    <Modal isOpen={open} onClose={()=>setOpen(false)} title="Exam setup toolkit" size="xl">
      <p className="text-body-sm text-(--color-text-secondary) mb-5">Prepare a room plan and the files your exam team needs. Enter real student registration numbers to create an upload-ready seat assignment.</p>
      <a href={starterKitUrl} download="proctorai-setup-kit.zip" onClick={downloadKit} aria-busy={kitDownloading} className="setup-kit-download"><Download size={15}/><span>{kitDownloading?'Preparing starter kit…':'Download starter kit'}<small>30-, 60- and 120-seat templates · All planning sheets and setup guide</small></span><ArrowRight size={15}/></a>
      {kitError&&<p role="alert" className="text-label text-(--color-error) mb-4">{kitError}</p>}
      <div className="setup-toolkit-grid">
        <div className="space-y-4">
          <FormField label="Room label" htmlFor={`${fieldId}-room`}><Input id={`${fieldId}-room`} value={room} maxLength={70} onChange={e=>setRoom(e.target.value)}/></FormField>
          <div className="grid grid-cols-2 gap-3">
            <FormField label="Total seats" htmlFor={`${fieldId}-seats`}><Input id={`${fieldId}-seats`} type="number" min={1} max={200} value={seatInput} onChange={e=>setSeatInput(e.target.value)}/></FormField>
            <FormField label="Columns" htmlFor={`${fieldId}-columns`}><Input id={`${fieldId}-columns`} type="number" min={1} max={20} value={columnInput} onChange={e=>setColumnInput(e.target.value)}/></FormField>
          </div>
          <FormField label="Student registration numbers" htmlFor={`${fieldId}-roster`} error={assignmentError}><TextArea id={`${fieldId}-roster`} value={roster} onChange={e=>setRoster(e.target.value)} placeholder="Paste one registration number per line" rows={5}/></FormField>
          <p className="text-label text-(--color-text-muted)">{ids.length} students · Seats assigned in order from 1. Leave this blank for an editable CSV template.</p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={!!assignmentError} onClick={()=>download('seat-assignments.csv',seatAssignmentCsv(seats,ids),'text/csv;charset=utf-8')}><Download size={14}/>{ids.length?'Download assignments':'Download blank seat CSV'}</Button>
            {onUseCsv && <Button variant="secondary" size="sm" disabled={!!assignmentError||!ids.length} loading={using} onClick={useCsv}>Use CSV in session<ArrowRight size={14}/></Button>}
          </div>
        </div>
        <div className="setup-plan-panel">
          <div className="flex justify-between gap-3 mb-3"><strong>Room plan</strong><span className="text-label text-(--color-text-muted)">{!layoutError&&`${Math.ceil(seats/columns)} rows · ${seats} seats`}</span></div>
          {svg ? <img className="setup-plan-image" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`} alt={`${room} seating plan: ${seats} numbered seats, ${columns} columns`}/> : <p role="status">Enter a valid layout to preview your plan.</p>}
          <div className="flex flex-wrap gap-2 mt-3">
            <Button variant="secondary" size="sm" disabled={!!assignmentError} onClick={()=>download('seating-plan.svg',svg,'image/svg+xml')}><Download size={14}/>Printable plan</Button>
            <Button variant="ghost" size="sm" disabled={!!layoutError} onClick={()=>download('seat-polygons.json',polygonJson(seats,columns),'application/json')}>Polygon draft JSON</Button>
          </div>
          <p className="text-label text-(--color-text-muted) mt-3">The diagram is a planning layout. Camera polygons must be aligned to the actual view in the administrator’s seat editor.</p>
        </div>
      </div>
      <div className="setup-template-list mt-6">
        {SETUP_TEMPLATES.map(template=><div key={template.id}><span className="setup-template-icon"><FileSpreadsheet size={18}/></span><div><strong>{template.title}</strong><p>{template.note}</p></div><Button variant="ghost" size="sm" onClick={()=>download(template.filename,template.content,'text/csv;charset=utf-8')} aria-label={`Download ${template.title} template`}><Download size={16}/></Button></div>)}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 mt-5"><p className="text-label text-(--color-text-muted)">Upload seat assignments on Session Setup. Setup sheets are imported by Admins and Exam Controllers.</p><Button variant="secondary" size="sm" onClick={()=>download('proctorai-setup-guide.md',SETUP_GUIDE)}><Download size={14}/>Setup guide</Button></div>
      {(user?.role===Role.Admin||user?.role===Role.ExamController)&&<Link onClick={()=>setOpen(false)} to={user.role===Role.Admin?'/admin/imports':'/exam-controller/imports'} className="setup-kit-download mt-4">Open CSV Imports<ArrowRight size={15}/></Link>}
      {notice&&<p className="flex items-center gap-2 text-label text-(--color-success) mt-4" role="status"><CheckCircle2 size={14}/>{notice}</p>}
    </Modal>
  </>;
}
