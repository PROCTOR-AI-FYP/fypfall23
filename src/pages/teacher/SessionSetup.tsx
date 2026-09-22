import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { FormField, Select, Input } from '@/components/ui/FormElements';
import { Upload, Play, CheckCircle2, AlertTriangle, Clock } from 'lucide-react';
import * as api from '@/lib/api';
import { classrooms } from '@/lib/fixtures';
import { Role } from '@/lib/types';

type SeatRowStatus = 'Resolved' | 'Unregistered ID' | 'Unverified';

interface SeatRow {
  seatNumber: string;
  studentRegNo: string;
  status: SeatRowStatus;
}

const statusStyles: Record<SeatRowStatus, string> = {
  Resolved: 'bg-(--color-success-subtle) text-(--color-success)',
  Unverified: 'bg-(--color-warning-subtle) text-(--color-warning)',
  'Unregistered ID': 'bg-(--color-error-subtle) text-(--color-error)',
};

const statusIcons: Record<SeatRowStatus, typeof CheckCircle2> = {
  Resolved: CheckCircle2,
  Unverified: Clock,
  'Unregistered ID': AlertTriangle,
};

export function SessionSetup() {
  const navigate = useNavigate();
  const [classroomId, setClassroomId] = useState('');
  const [silentMode, setSilentMode] = useState(false);
  const [seatRows, setSeatRows] = useState<SeatRow[]>([]);
  const [csvError, setCsvError] = useState('');
  const [resolving, setResolving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const allResolved = seatRows.length > 0 && seatRows.every(r => r.status === 'Resolved');

  const handleCsvUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvError('');
    setSeatRows([]);
    const reader = new FileReader();
    reader.onload = async (ev) => {
      const text = ev.target?.result as string;
      const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
      if (lines.length < 2) {
        setCsvError('CSV is empty or missing data rows');
        return;
      }
      const header = lines[0].split(',').map(h => h.trim().toLowerCase());
      const seatIdx = header.findIndex(h => h.includes('seat'));
      const regIdx = header.findIndex(h => h.includes('reg'));
      const dataLines = lines.slice(1);

      setResolving(true);
      try {
        const { data: allUsers } = await api.getUsers();
        const rows: SeatRow[] = dataLines.map(line => {
          const cells = line.split(',').map(c => c.trim());
          const seatNumber = seatIdx >= 0 ? cells[seatIdx] : cells[0];
          const studentRegNo = regIdx >= 0 ? cells[regIdx] : cells[1];
          const match = allUsers.find(u => u.role === Role.Student && u.registrationNo === studentRegNo);
          let status: SeatRowStatus;
          if (!match) status = 'Unregistered ID';
          else if (match.emailVerified === false) status = 'Unverified';
          else status = 'Resolved';
          return { seatNumber, studentRegNo, status };
        });
        setSeatRows(rows);
      } catch {
        setCsvError('Failed to resolve seat map against registered students');
      }
      setResolving(false);
    };
    reader.readAsText(file);
  };

  const handleStart = async () => {
    const e: Record<string, string> = {};
    if (!classroomId) e.classroom = 'Select a classroom';
    if (seatRows.length > 0 && !allResolved) e.seatMap = 'Resolve all seat assignments before starting the session';
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    setStarting(true);
    const cls = classrooms.find(c => c.id === classroomId);
    const res = await api.createSession({
      classroomId,
      classroomName: cls?.name || '',
      courseCode: 'CS-301',
      courseName: 'Database Systems',
      invigilatorId: 'current',
      invigilatorName: 'Current Teacher',
      silentMode,
      totalSeats: cls?.capacity || 30,
      occupiedSeats: Math.floor((cls?.capacity || 30) * 0.8),
    });
    navigate(`/teacher/live-monitor/${res.data.id}`);
  };

  const onlineClassrooms = classrooms.filter(c => c.cameraStatus === 'Online');

  return (
    <div className="max-w-2xl">
      <h1 className="text-display-lg text-(--color-text-primary) mb-2">Session Setup</h1>
      <p className="text-body text-(--color-text-secondary) mb-8">Configure and start a proctoring session for an exam</p>

      <div className="space-y-6">
        <FormField label="Classroom" error={errors.classroom} required>
          <Select value={classroomId} onChange={e => setClassroomId(e.target.value)} hasError={!!errors.classroom}>
            <option value="">Select a classroom...</option>
            {onlineClassrooms.map(c => (
              <option key={c.id} value={c.id}>{c.name} — {c.building} (capacity {c.capacity})</option>
            ))}
          </Select>
          {classroomId && !onlineClassrooms.find(c => c.id === classroomId)?.seatMap && (
            <p className="text-label text-(--color-warning) mt-1">This classroom has no seat map configured. Detection accuracy may be reduced.</p>
          )}
        </FormField>

        {/* Silent mode toggle */}
        <div className="flex items-center justify-between bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-4">
          <div>
            <p className="text-body font-medium text-(--color-text-primary)">Silent mode</p>
            <p className="text-body-sm text-(--color-text-muted)">Enable lip movement detection for silent exams</p>
          </div>
          <button
            onClick={() => setSilentMode(!silentMode)}
            className={`w-11 h-6 rounded-full transition-colors cursor-pointer relative ${silentMode ? 'bg-(--color-accent-primary)' : 'bg-(--color-border-strong)'}`}
            role="switch"
            aria-checked={silentMode}
          >
            <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${silentMode ? 'translate-x-5.5' : 'translate-x-0.5'}`} />
          </button>
        </div>

        {/* CSV Upload */}
        <FormField label="Seat map (CSV upload)" error={csvError}>
          <div className="border-2 border-dashed border-(--color-border-default) rounded-[6px] p-6 text-center hover:border-(--color-accent-primary) transition-colors">
            <Upload size={24} className="mx-auto mb-2 text-(--color-text-muted)" />
            <p className="text-body-sm text-(--color-text-muted) mb-2">Upload a CSV file mapping students to seats (seat_number, student_reg_no)</p>
            <label className="cursor-pointer">
              <Input type="file" accept=".csv" onChange={handleCsvUpload} className="hidden" />
              <span className="px-3 py-1.5 text-label font-medium text-(--color-accent-primary) bg-(--color-accent-primary-subtle) rounded-[4px] cursor-pointer">
                Choose file
              </span>
            </label>
          </div>
        </FormField>

        {/* CSV Preview */}
        {resolving && (
          <p className="text-body-sm text-(--color-text-muted)">Resolving seat assignments against registered students…</p>
        )}
        {!resolving && seatRows.length > 0 && (
          <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) overflow-auto max-h-72">
            <table className="w-full text-body-sm">
              <thead>
                <tr className="bg-(--color-bg-surface-raised)">
                  <th className="px-3 py-2 text-left text-label text-(--color-text-secondary)">Seat</th>
                  <th className="px-3 py-2 text-left text-label text-(--color-text-secondary)">Student Reg. No.</th>
                  <th className="px-3 py-2 text-left text-label text-(--color-text-secondary)">Status</th>
                </tr>
              </thead>
              <tbody>
                {seatRows.map((row, i) => {
                  const StatusIcon = statusIcons[row.status];
                  return (
                    <tr key={i} className="border-t border-(--color-border-default)">
                      <td className="px-3 py-2">{row.seatNumber}</td>
                      <td className="px-3 py-2">{row.studentRegNo}</td>
                      <td className="px-3 py-2">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-[2px] text-label font-medium ${statusStyles[row.status]}`}>
                          <StatusIcon size={12} />
                          {row.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {errors.seatMap && <p className="text-label text-(--color-error)">{errors.seatMap}</p>}

        <div className="pt-4">
          <Button onClick={handleStart} loading={starting} size="lg" disabled={seatRows.length > 0 && !allResolved}>
            <Play size={16} /> Start proctoring session
          </Button>
        </div>

        {/* Quick demo link */}
        <div className="pt-4 border-t border-(--color-border-default)">
          <p className="text-label text-(--color-warning) mb-2">Dev: Quick access</p>
          <button onClick={() => navigate('/teacher/live-monitor/ses-001')}
            className="text-body-sm text-(--color-accent-primary) hover:underline cursor-pointer">
            Open active demo session (CS-301 in LH-4)
          </button>
        </div>
      </div>
    </div>
  );
}
