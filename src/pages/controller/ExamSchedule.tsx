import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { FormField, Input, Select } from '@/components/ui/FormElements';
import * as api from '@/lib/api';
import { classrooms } from '@/lib/fixtures';
import type { ExamScheduleEntry } from '@/lib/types';
import { SessionStatus } from '@/lib/types';

export function ExamSchedule() {
  const [exams, setExams] = useState<ExamScheduleEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ courseCode: '', courseName: '', date: '', startTime: '', endTime: '', classroomId: '' });

  const load = () => {
    setLoading(true);
    api.getExamSchedule().then(r => { setExams(r.data); setLoading(false); }).catch(e => { setError(e.message); setLoading(false); });
  };
  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    if (!form.courseCode || !form.classroomId) return;
    setSaving(true);
    const cls = classrooms.find(c => c.id === form.classroomId);
    try {
      await api.createExam({ ...form, classroomName: cls?.name || '', department: 'Computer Science', status: SessionStatus.Scheduled });
      setModalOpen(false);
      load();
    } catch {
      setError('Failed to create');
    }
    setSaving(false);
  };

  const columns: Column<ExamScheduleEntry>[] = [
    { key: 'courseCode', header: 'Course', sortable: true, render: e => <div><span className="font-medium">{e.courseCode}</span><br/><span className="text-label text-(--color-text-muted)">{e.courseName}</span></div> },
    { key: 'date', header: 'Date', sortable: true, render: e => <span className="text-body-sm tabular-nums">{e.date}</span> },
    { key: 'time', header: 'Time', render: e => <span className="text-body-sm tabular-nums">{e.startTime} - {e.endTime}</span> },
    { key: 'classroomName', header: 'Room', sortable: true },
    { key: 'invigilatorName', header: 'Invigilator', render: e => e.invigilatorName ? <span>{e.invigilatorName}</span> : <span className="text-(--color-text-muted) italic">Unassigned</span> },
    { key: 'status', header: 'Status', render: e => (
      e.hasConflict ? <span className="px-2 py-0.5 rounded-[2px] bg-(--color-error-subtle) text-(--color-error) text-label font-medium">Conflict</span>
      : <span className="px-2 py-0.5 rounded-[2px] bg-(--color-success-subtle) text-(--color-success) text-label font-medium">Scheduled</span>
    )}
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-display-lg text-(--color-text-primary)">Exam Schedule</h1>
        <Button onClick={() => { setForm({ courseCode: '', courseName: '', date: '', startTime: '', endTime: '', classroomId: '' }); setModalOpen(true); }}>
          <Plus size={16} /> Schedule Exam
        </Button>
      </div>

      <DataTable columns={columns} data={exams} loading={loading} error={error} onRetry={load} searchable rowKey={e=>e.id} />

      <Modal isOpen={modalOpen} onClose={() => setModalOpen(false)} title="Schedule Exam"
        footer={<><Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button><Button onClick={handleCreate} loading={saving}>Schedule</Button></>}
      >
        <div className="space-y-4">
          <FormField label="Course Code" required><Input value={form.courseCode} onChange={e => setForm(f => ({...f, courseCode: e.target.value}))} placeholder="CS-301" /></FormField>
          <FormField label="Course Name" required><Input value={form.courseName} onChange={e => setForm(f => ({...f, courseName: e.target.value}))} placeholder="Database Systems" /></FormField>
          <div className="grid grid-cols-2 gap-4">
             <FormField label="Date" required><Input type="date" value={form.date} onChange={e => setForm(f => ({...f, date: e.target.value}))} /></FormField>
             <FormField label="Room" required>
               <Select value={form.classroomId} onChange={e => setForm(f => ({...f, classroomId: e.target.value}))}>
                 <option value="">Select Room...</option>
                 {classrooms.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
               </Select>
             </FormField>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Start Time" required><Input type="time" value={form.startTime} onChange={e => setForm(f => ({...f, startTime: e.target.value}))} /></FormField>
            <FormField label="End Time" required><Input type="time" value={form.endTime} onChange={e => setForm(f => ({...f, endTime: e.target.value}))} /></FormField>
          </div>
        </div>
      </Modal>
    </div>
  );
}
