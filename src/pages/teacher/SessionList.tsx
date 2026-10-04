import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { useLiveRevision } from '@/lib/live-context';
import { getSessions } from '@/lib/api';
import type { ExamSession } from '@/lib/types';

export function TeacherSessionList({ reports = false }: { reports?: boolean }) {
  const revision = useLiveRevision();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<ExamSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    getSessions().then(result => {
      if (!cancelled) {
        setSessions(result.data.filter(session => reports || session.status === 'In Progress'));
        setError('');
      }
    }).catch(reason => { if (!cancelled) setError(reason.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [revision, reports]);
  const columns: Column<ExamSession>[] = [
    { key: 'courseCode', header: 'Course', render: session => <span>{session.courseCode} · {session.courseName}</span> },
    { key: 'classroomName', header: 'Classroom' },
    { key: 'scheduledDate', header: 'Date' },
    { key: 'status', header: 'Status' },
  ];
  return <div>
    <h1 className="text-display-lg mb-4">{reports ? 'Session Reports' : 'Live Monitor'}</h1>
    <p className="text-body text-(--color-text-muted) mb-6">Select one of your assigned exam sessions.</p>
    <DataTable columns={columns} data={sessions} loading={loading} error={error} rowKey={session => session.id}
      emptyMessage={reports ? 'No assigned sessions yet.' : 'No active sessions. Start a scheduled exam from Session Setup.'}
      onRowClick={session => navigate(`/teacher/${reports ? 'session-report' : 'live-monitor'}/${session.id}`)} />
  </div>;
}
