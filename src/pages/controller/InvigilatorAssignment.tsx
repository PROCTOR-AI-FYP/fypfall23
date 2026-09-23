import { useEffect, useState } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { FormField, Select } from '@/components/ui/FormElements';
import * as api from '@/lib/api';
import type { InvigilatorAssignment, ExamScheduleEntry, User } from '@/lib/types';
import { Role } from '@/lib/types';

export function InvigilatorAssignment() {
  const [assignments, setAssignments] = useState<InvigilatorAssignment[]>([]);
  const [exams, setExams] = useState<ExamScheduleEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedExam, setSelectedExam] = useState('');
  const [selectedTeacher, setSelectedTeacher] = useState('');
  const [saving, setSaving] = useState(false);
  const [teachers, setTeachers] = useState<User[]>([]);

  const load = () => {
    setLoading(true);
    Promise.all([api.getAssignments(), api.getExamSchedule(), api.getUsers({ role: Role.Teacher, status: 'Active' })]).then(([aRes, eRes, tRes]) => {
      setAssignments(aRes.data);
      setExams(eRes.data.filter(e => !e.invigilatorId)); // Only unassigned exams
      setTeachers(tRes.data);
      setLoading(false);
    });
  };
  useEffect(() => { load(); }, []);

  const handleAssign = async () => {
    if (!selectedExam || !selectedTeacher) return;
    setSaving(true);
    await api.assignInvigilator(selectedExam, selectedTeacher);
    setModalOpen(false);
    load();
    setSaving(false);
  };

  const columns: Column<InvigilatorAssignment>[] = [
    { key: 'teacherName', header: 'Teacher', sortable: true, render: a => <div><span className="font-medium">{a.teacherName}</span><br/><span className="text-label text-(--color-text-muted)">{a.department}</span></div> },
    { key: 'courseCode', header: 'Exam', sortable: true },
    { key: 'date', header: 'Date/Time', render: a => <span className="text-body-sm tabular-nums">{a.date} | {a.startTime}-{a.endTime}</span> },
    { key: 'classroomName', header: 'Room', sortable: true },
    { key: 'status', header: 'Status', render: a => <span className="px-2 py-0.5 rounded-[2px] bg-(--color-success-subtle) text-(--color-success) text-label font-medium">{a.status}</span> },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-display-lg text-(--color-text-primary)">Invigilator Assignments</h1>
        <Button onClick={() => setModalOpen(true)}>Assign Invigilator</Button>
      </div>

      <DataTable columns={columns} data={assignments} loading={loading} searchable rowKey={a=>a.id} />

      <Modal isOpen={modalOpen} onClose={() => setModalOpen(false)} title="Assign Invigilator"
        footer={<><Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button><Button onClick={handleAssign} loading={saving}>Assign</Button></>}
      >
        <div className="space-y-4">
          <FormField label="Unassigned Exam" required>
            <Select value={selectedExam} onChange={e => setSelectedExam(e.target.value)}>
              <option value="">Select Exam...</option>
              {exams.map(e => <option key={e.id} value={e.id}>{e.courseCode} ({e.date} {e.startTime})</option>)}
            </Select>
          </FormField>
          <FormField label="Teacher" required>
            <Select value={selectedTeacher} onChange={e => setSelectedTeacher(e.target.value)}>
              <option value="">Select Teacher...</option>
              {teachers.map(t => <option key={t.id} value={t.id}>{t.name} ({t.department})</option>)}
            </Select>
          </FormField>
        </div>
      </Modal>
    </div>
  );
}
