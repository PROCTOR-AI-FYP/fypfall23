import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/FormElements';
import * as api from '@/lib/api';
import type { AuditLogEntry } from '@/lib/types';

export function AuditLogViewer() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionFilter, setActionFilter] = useState('');

  const load = () => {
    setLoading(true); setError('');
    const filters = actionFilter ? { action: actionFilter } : undefined;
    api.getAuditLog(filters).then(r => { setEntries(r.data); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  };

  useEffect(() => { load(); }, [actionFilter]);

  const exportCsv = () => {
    const header = 'Timestamp,User,Role,Action,Target,Details,IP\n';
    const rows = entries.map(e => `"${e.timestamp}","${e.userName}","${e.userRole}","${e.action}","${e.target}","${e.details}","${e.ipAddress}"`).join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `proctorai-audit-log-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  const columns: Column<AuditLogEntry>[] = [
    { key: 'timestamp', header: 'Timestamp', sortable: true, width: '180px', render: (e) => (
      <span className="text-body-sm tabular-nums text-(--color-text-secondary)">{new Date(e.timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
    )},
    { key: 'userName', header: 'User', sortable: true, render: (e) => (
      <div><span className="font-medium text-(--color-text-primary)">{e.userName}</span><br /><span className="text-label text-(--color-text-muted)">{e.userRole}</span></div>
    )},
    { key: 'action', header: 'Action', sortable: true, render: (e) => <span className="font-medium">{e.action}</span> },
    { key: 'details', header: 'Details', render: (e) => <span className="text-body-sm text-(--color-text-secondary)">{e.details}</span> },
    { key: 'ipAddress', header: 'IP', width: '120px', render: (e) => <span className="text-body-sm tabular-nums text-(--color-text-muted)">{e.ipAddress}</span> },
  ];

  const actionTypes = [...new Set(entries.map(e => e.action))];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-display-lg text-(--color-text-primary)">Audit Log</h1>
        <Button variant="secondary" onClick={exportCsv}><Download size={16} /> Export CSV</Button>
      </div>
      <DataTable
        columns={columns} data={entries} loading={loading} error={error} onRetry={load}
        emptyMessage="No audit entries found" searchable searchPlaceholder="Search audit log..."
        rowKey={e => e.id}
        filters={
          <Select value={actionFilter} onChange={e => setActionFilter(e.target.value)} className="w-48">
            <option value="">All actions</option>
            {actionTypes.map(a => <option key={a} value={a}>{a}</option>)}
          </Select>
        }
      />
    </div>
  );
}
