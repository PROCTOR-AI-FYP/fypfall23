import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Scale, Download } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { StatusChip, BehaviorChip } from '@/components/ui/Chips';
import { LoadingState } from '@/components/ui/DataDisplay';
import * as api from '@/lib/api';
import { type Case, CaseStatus } from '@/lib/types';

export function StudentCaseDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    api.getCase(id).then(r => { setCaseData(r.data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [id]);

  if (loading) return <LoadingState />;
  if (!caseData) return <div className="text-center py-16 text-(--color-text-muted)">Case not found</div>;

  const canAppeal = caseData.status === CaseStatus.Confirmed && caseData.penalty && !caseData.appeal;

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/student/cases')} className="p-2 rounded-[6px] text-(--color-text-muted) hover:bg-(--color-bg-surface-raised)">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-display-lg text-(--color-text-primary)">{caseData.referenceNo}</h1>
          <p className="text-body-sm text-(--color-text-secondary)">{caseData.courseCode} — {caseData.courseName}</p>
        </div>
        <StatusChip status={caseData.status} />
      </div>

      <div className="space-y-6">
        {/* Notice of Case */}
        <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-6">
           <h2 className="text-heading text-(--color-text-primary) mb-4 border-b border-(--color-border-default) pb-2">Case Summary</h2>
           <div className="grid grid-cols-1 md:grid-cols-2 gap-y-4">
              <div><p className="text-label text-(--color-text-muted)">Date</p><p className="font-medium">{new Date(caseData.createdAt).toLocaleDateString()}</p></div>
              <div><p className="text-label text-(--color-text-muted)">Room & Seat</p><p className="font-medium">{caseData.classroomName}, Seat {caseData.seatNumber}</p></div>
              <div className="col-span-2">
                <p className="text-label text-(--color-text-muted) mb-1">Detected Behaviors</p>
                <div className="flex gap-2">{caseData.behaviourTypes.map(b => <BehaviorChip key={b} type={b} />)}</div>
              </div>
           </div>
        </div>

        {/* Penalty details if any */}
        {caseData.penalty && (
          <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-error)/20 p-6">
            <h2 className="text-heading text-(--color-error) mb-4 border-b border-(--color-border-default) pb-2">Issued Penalty</h2>
            <div className="space-y-3">
              <div><p className="text-label text-(--color-text-muted)">Penalty Type</p><p className="text-body font-medium text-(--color-error)">{caseData.penalty.type}</p></div>
              <div><p className="text-label text-(--color-text-muted)">Description</p><p className="text-body text-(--color-text-primary)">{caseData.penalty.description}</p></div>
              <div><p className="text-label text-(--color-text-muted)">Issued By</p><p className="text-body-sm text-(--color-text-secondary)">{caseData.penalty.issuedByName} (Head of Department)</p></div>
            </div>
            <div className="mt-6 flex gap-3">
              <Button variant="secondary"><Download size={16} /> Download Notice PDF</Button>
              {canAppeal && (
                <Button onClick={() => navigate(`/student/cases/${caseData.id}/appeal`)}><Scale size={16} /> File an Appeal</Button>
              )}
            </div>
          </div>
        )}

        {/* Appeal Status */}
        {caseData.appeal && (
          <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-behavior-gaze)/30 p-6">
            <h2 className="text-heading text-(--color-behavior-gaze) mb-4 border-b border-(--color-border-default) pb-2">Appeal Information</h2>
            <div className="space-y-3">
              <div><p className="text-label text-(--color-text-muted)">Status</p><p className="font-medium">{caseData.appeal.status}</p></div>
              <div><p className="text-label text-(--color-text-muted)">Your Statement</p><p className="text-body-sm text-(--color-text-secondary)">{caseData.appeal.statement}</p></div>
              {caseData.appeal.status !== 'Open' && (
                <div><p className="text-label text-(--color-text-muted)">HOD Review Note</p><p className="text-body font-medium">{caseData.appeal.reviewNote}</p></div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
