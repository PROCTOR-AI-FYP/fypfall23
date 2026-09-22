import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Clock, Users, ShieldAlert, FileCheck } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { StatCard, LoadingState } from '@/components/ui/DataDisplay';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { StatusChip, BehaviorChip } from '@/components/ui/Chips';
import * as api from '@/lib/api';
import type { ExamSession, Case } from '@/lib/types';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip as RechartsTooltip, Legend } from 'recharts';

export function SessionReport() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [session, setSession] = useState<ExamSession | null>(null);
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      api.getSession(id),
      api.getCases() // In reality, filter by sessionId
    ]).then(([sessRes, caseRes]) => {
      setSession(sessRes.data);
      setCases(caseRes.data.filter(c => c.sessionId === id));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingState />;
  if (!session) return <div className="text-center py-16 text-(--color-text-muted)">Session not found</div>;

  const durationStr = () => {
    if (!session.startTime || !session.endTime) return 'N/A';
    const s = new Date(`2000-01-01T${session.startTime}`);
    const e = new Date(`2000-01-01T${session.endTime}`);
    const diffMins = (e.getTime() - s.getTime()) / 60000;
    return `${Math.floor(diffMins / 60)}h ${diffMins % 60}m`;
  };

  const behaviorCounts = cases.reduce((acc, c) => {
    c.behaviourTypes.forEach(b => {
      acc[b] = (acc[b] || 0) + 1;
    });
    return acc;
  }, {} as Record<string, number>);
  
  const behaviorData = Object.entries(behaviorCounts).map(([name, value]) => ({ name, value }));
  const COLORS = ['#2B5EA7', '#DC2626', '#D97706', '#059669', '#7C3AED'];

  const columns: Column<Case>[] = [
    { key: 'referenceNo', header: 'Case ID', render: c => <span className="font-medium text-(--color-accent-primary)">{c.referenceNo}</span> },
    { key: 'studentName', header: 'Student', render: c => <span>{c.studentName} ({c.seatNumber})</span> },
    { key: 'behaviourTypes', header: 'Behaviors', render: c => <div className="flex gap-1">{c.behaviourTypes.map(b => <BehaviorChip key={b} type={b} />)}</div> },
    { key: 'status', header: 'Status', render: c => <StatusChip status={c.status} /> }
  ];

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/teacher/session-setup')} className="p-2 rounded-[6px] text-(--color-text-muted) hover:bg-(--color-bg-surface-raised)">
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-display-lg text-(--color-text-primary)">Session Report</h1>
          <p className="text-body-sm text-(--color-text-secondary)">{session.courseCode} — {session.courseName} | {session.scheduledDate}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={<Clock size={18} />} label="Duration" value={durationStr()} />
        <StatCard icon={<Users size={18} />} label="Attendance" value={`${session.occupiedSeats}/${session.totalSeats}`} />
        <StatCard icon={<ShieldAlert size={18} />} label="Confirmed Cases" value={cases.length} color="var(--color-error)" />
        <StatCard icon={<FileCheck size={18} />} label="Status" value={session.status} color={session.status === 'Completed' ? 'var(--color-success)' : undefined} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        {/* Behavior Chart */}
        <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
          <h2 className="text-heading text-(--color-text-primary) mb-4">Case Composition</h2>
          {cases.length > 0 ? (
            <div className="h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={behaviorData} innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                    {behaviorData.map((_, index) => <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />)}
                  </Pie>
                  <RechartsTooltip contentStyle={{ backgroundColor: 'var(--color-bg-surface-overlay)', border: '1px solid var(--color-border-default)', borderRadius: '6px', fontSize: '13px' }} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-[220px] flex items-center justify-center text-body-sm text-(--color-text-muted)">No cases recorded</div>
          )}
        </div>

        {/* Notes */}
        <div className="lg:col-span-2 bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
           <h2 className="text-heading text-(--color-text-primary) mb-4">Generated Summary</h2>
           <div className="prose prose-sm prose-invert max-w-none text-(--color-text-secondary)">
             <p>Session <strong>{session.courseCode}</strong> concluded on {session.scheduledDate} at {session.endTime}.</p>
             <p>Attendance was {Math.round((session.occupiedSeats / session.totalSeats)*100)}% with {session.occupiedSeats} students present.</p>
             <p>A total of {cases.length} confirmed integrity cases were escalated to the Head of Department. 
             {cases.length === 0 ? " The session proceeded smoothly without major incidents." : " Review the case list below for details."}</p>
           </div>
           <div className="mt-6 flex justify-end">
             <Button variant="secondary">Download PDF Report</Button>
           </div>
        </div>
      </div>

      {/* Cases Table */}
      <h2 className="text-heading text-(--color-text-primary) mb-4">Confirmed Cases</h2>
      <DataTable columns={columns} data={cases} emptyMessage="No cases confirmed during this session." rowKey={c=>c.id} />
    </div>
  );
}
