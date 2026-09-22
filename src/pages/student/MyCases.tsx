import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { StatusChip, BehaviorChip } from '@/components/ui/Chips';
import { useAuth } from '@/lib/auth-context';
import * as api from '@/lib/api';
import type { Case } from '@/lib/types';

export function MyCases() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = () => {
    if (!user) return;
    setLoading(true);
    // Student sees only their cases
    api.getCases({ studentId: user.id }).then(r => { 
      setCases(r.data); 
      setLoading(false); 
    }).catch(e => { setError(e.message); setLoading(false); });
  };
  
  useEffect(() => { load(); }, [user]);

  const columns: Column<Case>[] = [
    { key: 'referenceNo', header: 'Case ID', render: c => <span className="font-medium text-(--color-accent-primary)">{c.referenceNo}</span> },
    { key: 'courseCode', header: 'Course', render: c => <div><span className="font-medium">{c.courseCode}</span><br/><span className="text-label text-(--color-text-muted)">{c.courseName}</span></div> },
    { key: 'behaviourTypes', header: 'Detected Behaviors', render: c => <div className="flex gap-1 flex-wrap">{c.behaviourTypes.map(b => <BehaviorChip key={b} type={b} />)}</div> },
    { key: 'status', header: 'Status', render: c => <StatusChip status={c.status} /> },
    { key: 'createdAt', header: 'Date', render: c => <span className="text-body-sm text-(--color-text-muted)">{new Date(c.createdAt).toLocaleDateString()}</span> },
  ];

  return (
    <div>
      <h1 className="text-display-lg text-(--color-text-primary) mb-2">My Cases</h1>
      <p className="text-body text-(--color-text-secondary) mb-8">View and track academic integrity cases filed against you</p>
      
      <div className="bg-(--color-bg-surface-raised) p-4 rounded-[6px] border border-(--color-border-default) mb-6">
        <h3 className="text-body font-medium text-(--color-text-primary) mb-1">Understanding your cases</h3>
        <p className="text-body-sm text-(--color-text-secondary)">
          If you have a confirmed case with an issued penalty, you have the right to file an appeal within 5 working days. 
          Click on a case to view details, penalty information, and access the appeal form.
        </p>
      </div>

      <DataTable 
        columns={columns} 
        data={cases} 
        loading={loading} 
        error={error} 
        onRetry={load}
        emptyMessage="You have no recorded cases."
        onRowClick={c => navigate(`/student/cases/${c.id}`)}
        rowKey={c => c.id}
      />
    </div>
  );
}
