import { useEffect, useState } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import * as api from '@/lib/api';
import type { ExamSession } from '@/lib/types';
import { SessionStatus } from '@/lib/types';

export function SessionHistory() {
  const [sessions, setSessions] = useState<ExamSession[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.getSessions().then(r => { setSessions(r.data); setLoading(false); });
  };
  useEffect(() => { load(); }, []);

  const columns: Column<ExamSession>[] = [
    { key: 'courseCode', header: 'Course', sortable: true, render: s => <div><span className="font-medium">{s.courseCode}</span><br/><span className="text-label text-(--color-text-muted)">{s.courseName}</span></div> },
    { key: 'scheduledDate', header: 'Date', sortable: true, render: s => <span className="text-body-sm tabular-nums">{s.scheduledDate}</span> },
    { key: 'classroomName', header: 'Room', sortable: true },
    { key: 'invigilatorName', header: 'Invigilator' },
    { key: 'caseCount', header: 'Confirmed Cases', render: s => <span className={`text-body-sm tabular-nums font-medium ${s.caseCount > 0 ? 'text-(--color-error)' : 'text-(--color-text-muted)'}`}>{s.caseCount}</span> },
    { key: 'status', header: 'Status', render: s => (
      <span className={`px-2 py-0.5 rounded-[2px] text-label font-medium ${
        s.status === SessionStatus.Completed ? 'bg-(--color-success-subtle) text-(--color-success)' :
        s.status === SessionStatus.InProgress ? 'bg-(--color-warning-subtle) text-(--color-warning)' :
        'bg-(--color-bg-surface-raised) text-(--color-text-muted)'
      }`}>{s.status}</span>
    )},
  ];

  return (
    <div>
      <h1 className="text-display-lg text-(--color-text-primary) mb-6">Session History</h1>
      <DataTable columns={columns} data={sessions} loading={loading} searchable rowKey={s=>s.id} />
    </div>
  );
}
