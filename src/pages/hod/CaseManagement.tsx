import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { StatusChip, BehaviorChip } from '@/components/ui/Chips';
import { ConfidenceBar } from '@/components/ui/DataDisplay';
import { Select } from '@/components/ui/FormElements';
import * as api from '@/lib/api';
import { type Case, CaseStatus, BehaviorType } from '@/lib/types';

export function CaseManagement() {
  const navigate = useNavigate();
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [behaviorFilter, setBehaviorFilter] = useState('');

  const load = () => {
    setLoading(true); setError('');
    const filters: Parameters<typeof api.getCases>[0] = {};
    if (statusFilter) filters.status = statusFilter as CaseStatus;
    if (behaviorFilter) filters.behaviorType = behaviorFilter as BehaviorType;
    api.getCases(filters).then(r => { setCases(r.data); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  };

  useEffect(() => { load(); }, [statusFilter, behaviorFilter]);

  const columns: Column<Case>[] = [
    { key: 'referenceNo', header: 'Case ID', sortable: true, width: '180px', render: (c) => (
      <span className="font-medium text-(--color-accent-primary)">{c.referenceNo}</span>
    )},
    { key: 'studentName', header: 'Student', sortable: true, render: (c) => (
      <div><span className="font-medium text-(--color-text-primary)">{c.studentName}</span><br /><span className="text-label text-(--color-text-muted)">{c.studentRegNo}</span></div>
    )},
    { key: 'courseCode', header: 'Course', sortable: true, render: (c) => (
      <div><span className="text-body">{c.courseCode}</span><br /><span className="text-label text-(--color-text-muted)">{c.courseName}</span></div>
    )},
    { key: 'behaviourTypes', header: 'Behavior', render: (c) => (
      <div className="flex flex-wrap gap-1">{c.behaviourTypes.map(b => <BehaviorChip key={b} type={b} />)}</div>
    )},
    { key: 'compositeScore', header: 'Confidence', width: '140px', render: (c) => <ConfidenceBar value={c.compositeScore} /> },
    { key: 'status', header: 'Status', sortable: true, render: (c) => <StatusChip status={c.status} /> },
    { key: 'createdAt', header: 'Date', sortable: true, width: '100px', render: (c) => (
      <span className="text-body-sm text-(--color-text-muted) tabular-nums">{new Date(c.createdAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
    )},
  ];

  return (
    <div>
      <h1 className="text-display-lg text-(--color-text-primary) mb-6">Case Management</h1>
      <DataTable
        columns={columns} data={cases} loading={loading} error={error} onRetry={load}
        emptyMessage="No cases found matching your filters"
        searchable searchPlaceholder="Search by case ID, student, or course..."
        onRowClick={(c) => navigate(`/hod/cases/${c.id}`)}
        rowKey={c => c.id}
        filters={
          <div className="flex gap-2">
            <Select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="w-40">
              <option value="">All statuses</option>
              {Object.values(CaseStatus).map(s => <option key={s} value={s}>{s}</option>)}
            </Select>
            <Select value={behaviorFilter} onChange={e => setBehaviorFilter(e.target.value)} className="w-48">
              <option value="">All behaviors</option>
              {Object.values(BehaviorType).map(b => <option key={b} value={b}>{b}</option>)}
            </Select>
          </div>
        }
      />
    </div>
  );
}
