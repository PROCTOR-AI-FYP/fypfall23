import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { FormField, TextArea } from '@/components/ui/FormElements';
import { useAuth } from '@/lib/auth-context';
import * as api from '@/lib/api';
import { type Appeal, AppealStatus } from '@/lib/types';

export function AppealReview() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [appeals, setAppeals] = useState<Appeal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedAppeal, setSelectedAppeal] = useState<Appeal | null>(null);
  const [reviewNote, setReviewNote] = useState('');
  const [resolving, setResolving] = useState('');
  const [resolved, setResolved] = useState(false);

  const load = () => {
    setLoading(true);
    api.getAppeals().then(r => { setAppeals(r.data); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  };
  useEffect(() => { load(); }, []);

  const handleResolve = async (status: AppealStatus.Accepted | AppealStatus.Rejected) => {
    if (!selectedAppeal || !reviewNote.trim()) return;
    setResolving(status);
    try {
      await api.resolveAppeal(selectedAppeal.id, {
        status, reviewNote, reviewerName: user?.name || '', reviewerId: user?.id || '',
      });
      setResolved(true);
      setTimeout(() => { setSelectedAppeal(null); setResolved(false); setReviewNote(''); load(); }, 1500);
    } catch { setError('Failed to resolve'); }
    setResolving('');
  };

  const columns: Column<Appeal>[] = [
    { key: 'caseId', header: 'Case', render: (a) => (
      <button onClick={(e) => { e.stopPropagation(); navigate(`/hod/cases/${a.caseId}`); }}
        className="text-(--color-accent-primary) hover:underline font-medium cursor-pointer">{a.caseId.replace('case-', 'AU-CS-INT-2026-')}</button>
    )},
    { key: 'studentName', header: 'Student', sortable: true, render: (a) => (
      <div><span className="font-medium">{a.studentName}</span><br /><span className="text-label text-(--color-text-muted)">{a.studentRegNo}</span></div>
    )},
    { key: 'statement', header: 'Statement', render: (a) => (
      <span className="text-body-sm text-(--color-text-secondary) line-clamp-2">{a.statement}</span>
    )},
    { key: 'status', header: 'Status', render: (a) => {
      const colors = { Open: 'var(--color-warning)', Accepted: 'var(--color-success)', Rejected: 'var(--color-error)' };
      return <span className="text-label font-medium" style={{ color: colors[a.status] }}>{a.status}</span>;
    }},
    { key: 'submittedAt', header: 'Submitted', sortable: true, render: (a) => (
      <span className="text-body-sm text-(--color-text-muted) tabular-nums">{new Date(a.submittedAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
    )},
  ];

  return (
    <div>
      <h1 className="text-display-lg text-(--color-text-primary) mb-6">Appeal Review</h1>
      <DataTable columns={columns} data={appeals} loading={loading} error={error} onRetry={load}
        emptyMessage="No appeals submitted" searchable onRowClick={a => setSelectedAppeal(a)} rowKey={a => a.id} />

      <Modal isOpen={!!selectedAppeal} onClose={() => { setSelectedAppeal(null); setResolved(false); }} title="Review appeal" size="lg"
        footer={!resolved ? (
          <>
            <Button variant="secondary" onClick={() => setSelectedAppeal(null)}>Cancel</Button>
            <Button variant="danger" onClick={() => handleResolve(AppealStatus.Rejected)} loading={resolving === 'Rejected'} disabled={!reviewNote.trim()}>Reject</Button>
            <Button onClick={() => handleResolve(AppealStatus.Accepted)} loading={resolving === 'Accepted'} disabled={!reviewNote.trim()}>Accept appeal</Button>
          </>
        ) : undefined}
      >
        {resolved ? (
          <div className="flex flex-col items-center py-8">
            <div className="w-16 h-16 rounded-full border-2 border-(--color-accent-primary) flex items-center justify-center mb-4">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-primary)" strokeWidth="2"><polyline points="20 6 9 17 4 12" /></svg>
            </div>
            <p className="text-heading text-(--color-text-primary)">Appeal resolved</p>
          </div>
        ) : selectedAppeal && (
          <div className="space-y-5">
            <div className="bg-(--color-bg-surface-raised) rounded-[6px] p-4">
              <h3 className="text-label text-(--color-text-muted) mb-2">Student's statement</h3>
              <p className="text-body text-(--color-text-primary)">{selectedAppeal.statement}</p>
              {selectedAppeal.supportingInfo && (
                <p className="text-body-sm text-(--color-text-secondary) mt-2 pt-2 border-t border-(--color-border-default)">
                  Supporting info: {selectedAppeal.supportingInfo}
                </p>
              )}
            </div>
            <FormField label="Review reasoning" required>
              <TextArea value={reviewNote} onChange={e => setReviewNote(e.target.value)}
                placeholder="Provide your reasoning for accepting or rejecting this appeal..." rows={4} />
            </FormField>
          </div>
        )}
      </Modal>
    </div>
  );
}
