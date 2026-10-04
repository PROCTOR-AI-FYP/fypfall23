import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileSpreadsheet, Upload, CheckCircle2, Download, ArrowRight } from 'lucide-react';
import { useAuth } from '@/lib/auth-context';
import { Role } from '@/lib/types';
import * as api from '@/lib/api';
import { SETUP_TEMPLATES, downloadSetupFile } from '@/lib/setup-assets';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';

const fileTypes = [
  {kind:'student_roster',title:'Student roster',description:'Create student accounts with registration numbers and university emails.',template:'roster',role:Role.Admin},
  {kind:'classroom_inventory',title:'Classroom inventory',description:'Create rooms with capacity, camera ID and status.',template:'classrooms',role:Role.Admin},
  {kind:'exam_schedule',title:'Exam schedule',description:'Create scheduled exams and resolve each room by name.',template:'schedule'},
  {kind:'invigilator_assignments',title:'Invigilator assignments',description:'Resolve registered teachers by email and assign them to matching exams.',template:'invigilators'},
] as const;
const labels=Object.fromEntries(fileTypes.map(t=>[t.kind,t.title]));
const actionStyles={create:'text-(--color-accent-primary) bg-(--color-accent-primary-subtle)',skip:'text-(--color-text-muted) bg-(--color-bg-surface-raised)',error:'text-(--color-error) bg-(--color-error-subtle)'};
const columns:Column<api.CsvImportRow>[]=[
  {key:'kind',header:'File',render:r=><span>{labels[r.kind]}</span>},
  {key:'line',header:'Line',width:'65px'},
  {key:'label',header:'Record',render:r=><strong className="font-medium">{r.label}</strong>},
  {key:'action',header:'Result',render:r=><span className={`pa-chip inline-flex ${actionStyles[r.action]}`}>{r.action==='create'?'Ready':r.action==='skip'?'Unchanged':'Fix required'}</span>},
  {key:'note',header:'Details',render:r=><span className="text-body-sm">{r.note}</span>},
];

export function CsvImports() {
  const {user}=useAuth();
  const id=useId();
  const [files,setFiles]=useState<api.CsvImportFiles>({});
  const [plan,setPlan]=useState<api.CsvImportPreview|null>(null);
  const [result,setResult]=useState<api.CsvImportResult|null>(null);
  const [busy,setBusy]=useState<'preview'|'commit'|null>(null);
  const [error,setError]=useState('');
  const available=fileTypes.filter(type=>!('role' in type)||user?.role===type.role);
  const changeFile=(kind:api.CsvImportKind,file?:File)=>{
    setPlan(null);setResult(null);setError('');
    const next={...files};delete next[kind];
    if (file && (!file.name.toLowerCase().endsWith('.csv')||file.size>256*1024)) setError('Choose a CSV file of at most 256 KB.');
    else if (file) next[kind]=file;
    setFiles(next);
  };
  const preview=async()=>{
    setBusy('preview');setError('');setResult(null);setPlan(null);
    try {setPlan(await api.previewCsvImports(files));}
    catch(e) {setError((e as {message?:string}).message??'Could not preview the CSV files.');}
    finally {setBusy(null);}
  };
  const commit=async()=>{
    if(!plan?.can_import) return;
    setBusy('commit');setError('');
    try {setResult(await api.commitCsvImports(files,plan.preview_hash));setPlan(null);}
    catch(e) {setError((e as {message?:string}).message??'Import failed. No records were saved.');setPlan(null);}
    finally {setBusy(null);}
  };
  return <div className="csv-import-page">
    <div className="mb-6"><h1 className="text-display-lg text-(--color-text-primary)">CSV Imports</h1><p className="text-body-sm text-(--color-text-secondary) mt-2">Upload your setup sheets. ProctorAI checks the records, connects rooms, exams and teachers, then saves the complete valid batch.</p></div>
    <div className="csv-import-guide"><span>01 · Choose files</span><ArrowRight size={14}/><span>02 · Review validation</span><ArrowRight size={14}/><span>03 · Import together</span></div>
    {user?.role===Role.Admin?<p className="text-body-sm text-(--color-text-secondary) mb-5">Upload all four files together to set up an exam in one import, or upload only the sheets you need. Teachers must already have an active teacher account.</p>:<p className="text-body-sm text-(--color-text-secondary) mb-5">Import schedules and assignments together. Student accounts and classroom inventory are managed by your administrator.</p>}
    <div className="csv-import-files">
      {available.map(type=>{
        const template=SETUP_TEMPLATES.find(t=>t.id===type.template)!;
        return <section key={type.kind} className="csv-import-file">
          <div className="flex items-start gap-3"><span className="setup-template-icon"><FileSpreadsheet size={20}/></span><div><h2>{type.title}</h2><p>{type.description}</p></div></div>
          <label htmlFor={`${id}-${type.kind}`} className="text-label text-(--color-text-secondary) mt-5 mb-2 block">{type.title} CSV</label>
          <input id={`${id}-${type.kind}`} type="file" accept=".csv,text/csv" disabled={!!busy} onChange={e=>changeFile(type.kind,e.target.files?.[0])} className="csv-import-input"/>
          {files[type.kind]&&<p className="csv-import-selected">{files[type.kind]?.name} · {Math.ceil(files[type.kind]!.size/1024)} KB</p>}
          <Button variant="ghost" size="sm" disabled={!!busy} className="mt-3" onClick={()=>downloadSetupFile(template.filename,template.content,'text/csv;charset=utf-8')}><Download size={14}/>Blank template</Button>
        </section>;
      })}
    </div>
    <div className="csv-import-policy"><CheckCircle2 size={18}/><p>Exact matches are skipped, so uploading the same files again creates no duplicates. Different existing details, missing links and booking conflicts must be fixed before importing. Student accounts activate through their owner’s Google sign-in. Camera polygons are configured in the seat editor.</p></div>
    {error&&<p role="alert" className="auth-error mt-4">{error}</p>}
    <div className="flex flex-wrap gap-3 items-center my-5">
      <Button loading={busy==='preview'} disabled={!!busy||!Object.keys(files).length} onClick={preview}><Upload size={16}/>Preview CSV files</Button>
      <span className="text-label text-(--color-text-muted)">{Object.keys(files).length} {Object.keys(files).length===1?'file':'files'} selected · Up to 1,000 rows per file</span>
    </div>
    {plan&&<section className="csv-import-preview">
      <div className="csv-import-summary"><strong>{plan.counts.create} ready to import</strong><span>{plan.counts.skip} unchanged</span><span className={plan.counts.error?'text-(--color-error)':''}>{plan.counts.error} rows to fix</span></div>
      {plan.counts.error>0&&<p role="alert" className="auth-error mb-4">Fix every rejected row in your CSVs, choose the corrected files and preview again. Nothing has been imported.</p>}
      <DataTable columns={columns} data={plan.rows} rowKey={r=>`${r.kind}-${r.line}`} emptyMessage="No import rows"/>
      <div className="flex flex-wrap items-center justify-between gap-3 mt-5"><p className="text-label text-(--color-text-muted)">Records, audit entries and assignment notifications are saved together.</p><Button disabled={!!busy||!plan.can_import} loading={busy==='commit'} onClick={commit}><CheckCircle2 size={16}/>Import {plan.counts.create} records</Button></div>
    </section>}
    {result&&<section className="csv-import-result" role="status"><CheckCircle2 size={24}/><div><h2>Import complete</h2><p>{Object.values(result.created).reduce((a,b)=>a+b,0)} records imported · {result.skipped} unchanged. The connected portals refresh automatically.</p><div className="flex flex-wrap gap-4 mt-3">{user?.role===Role.Admin?<><Link to="/admin/users">View students<ArrowRight size={13}/></Link><Link to="/admin/classrooms">View classrooms<ArrowRight size={13}/></Link></>:<><Link to="/exam-controller/schedule">View schedule<ArrowRight size={13}/></Link><Link to="/exam-controller/assignments">View assignments<ArrowRight size={13}/></Link></>}</div></div></section>}
  </div>;
}
