import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { FormField, Select, Input } from '@/components/ui/FormElements';
import { Upload, Play, CheckCircle2, AlertTriangle, Clock } from 'lucide-react';
import * as api from '@/lib/api';
import type { Classroom } from '@/lib/types';

type SeatRow = api.SeatMapPreviewRow;
type SeatRowStatus = SeatRow['status'];

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
  const [seatFile, setSeatFile] = useState<File | null>(null);
  const [csvError, setCsvError] = useState('');
  const [resolving, setResolving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);

  useEffect(() => {
    api.getClassrooms()
      .then(res => setClassrooms(res.data))
      .catch(err => setErrors(prev => ({ ...prev, classroom: (err as { message?: string }).message || 'Could not load classrooms' })));
  }, []);

  const allResolved = seatRows.length > 0 && seatRows.every(r => r.status === 'Resolved');

  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvError('');
    setSeatRows([]);
    setSeatFile(null);
    setResolving(true);
    try {
      // Resolved server-side against registered, signed-in student accounts.
      const res = await api.previewSeatMap(file);
      setSeatRows(res.data);
      setSeatFile(file);
    } catch (err) {
      setCsvError((err as { message?: string }).message || 'Failed to resolve seat map against registered students');
    }
    setResolving(false);
  };

  const handleStart = async () => {
    const e: Record<string, string> = {};
    if (!classroomId) e.classroom = 'Select a classroom';
    if (seatRows.length > 0 && !allResolved) e.seatMap = 'Resolve all seat assignments before starting the session';
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    setStarting(true);
    try {
      // The backend starts this teacher's exam scheduled today in this room.
      const res = await api.createSession({ classroomId, silentMode }, seatFile ?? undefined);
      navigate(`/teacher/live-monitor/${res.data.id}`);
    } catch (err) {
      setErrors({ classroom: (err as { message?: string }).message || 'Could not start the session' });
      setStarting(false);
    }
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
      </div>
    </div>
  );
}
