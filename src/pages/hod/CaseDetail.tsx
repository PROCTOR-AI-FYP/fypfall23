import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, EyeOff, Eye, Clock } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { StatusChip, BehaviorChip } from '@/components/ui/Chips';
import { ConfidenceBar, LoadingState } from '@/components/ui/DataDisplay';
import { PenaltyModal } from './PenaltyModal';
import { EvidenceViewer } from '@/components/evidence/EvidenceViewer';
import * as api from '@/lib/api';
import { type Case, CaseStatus } from '@/lib/types';

export function CaseDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [blurred, setBlurred] = useState(true);
  const [penaltyOpen, setPenaltyOpen] = useState(false);
  const [actionLoading, setActionLoading] = useState('');

  useEffect(() => {
    if (!id) return;
    api.getCase(id).then(r => { setCaseData(r.data); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [id]);

  const handleDismiss = async () => {
    if (!id) return;
    setActionLoading('dismiss');
    const res = await api.dismissCase(id, 'Insufficient evidence to proceed');
    setCaseData(res.data);
    setActionLoading('');
  };

  const handleEscalate = async () => {
    if (!id) return;
    setActionLoading('escalate');
    const res = await api.escalateCase(id, 'Referred to disciplinary committee');
    setCaseData(res.data);
    setActionLoading('');
  };

  if (loading) return <LoadingState />;
  if (error || !caseData) return <div className="text-center py-16 text-(--color-text-muted)">{error || 'Case not found'}</div>;

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/hod/cases')} className="p-2 rounded-[6px] text-(--color-text-muted) hover:bg-(--color-bg-surface-raised) cursor-pointer">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-display-lg text-(--color-text-primary)">{caseData.referenceNo}</h1>
          <p className="text-body-sm text-(--color-text-secondary)">{caseData.courseName}, {caseData.classroomName}</p>
        </div>
        <StatusChip status={caseData.status} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Evidence + Details */}
        <div className="lg:col-span-2 space-y-6">
          {/* Evidence viewer — the bold element on this screen */}
          <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) overflow-hidden">
            <div className="px-5 py-3 border-b border-(--color-border-default) flex items-center justify-between">
              <h2 className="text-heading text-(--color-text-primary)">Evidence capture</h2>
              <button onClick={() => setBlurred(!blurred)} aria-pressed={!blurred} className="flex items-center gap-1.5 text-label text-(--color-accent-primary) hover:underline cursor-pointer rounded-[2px]">
                {blurred ? <Eye size={14} aria-hidden="true" /> : <EyeOff size={14} aria-hidden="true" />}
                {blurred ? 'Reveal evidence' : 'Blur evidence'}
              </button>
            </div>
            <EvidenceViewer
              // Remount (and refetch) when the review outcome changes, since that can change the clip's state.
              key={`${caseData.status}:${caseData.penalty?.id ?? 'none'}`}
              caseId={caseData.id}
              concealed={blurred}
              subjectLabel={`seat ${caseData.seatNumber}, ${caseData.studentName}`}
            />
          </div>

          {/* Confidence breakdown */}
          <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
            <h2 className="text-heading text-(--color-text-primary) mb-4">Confidence breakdown</h2>
            <div className="space-y-3">
              {caseData.behaviourTypes.map(b => (
                <div key={b} className="flex items-center gap-4">
                  <div className="w-40 shrink-0"><BehaviorChip type={b} /></div>
                  <div className="flex-1"><ConfidenceBar value={caseData.compositeScore} /></div>
                </div>
              ))}
              <div className="pt-3 border-t border-(--color-border-default) flex items-center gap-4">
                <span className="w-40 text-body font-medium text-(--color-text-primary) shrink-0">Composite score</span>
                <div className="flex-1"><ConfidenceBar value={caseData.compositeScore} /></div>
              </div>
            </div>
          </div>

          {/* Teacher note */}
          {caseData.teacherNote && (
            <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
              <h2 className="text-heading text-(--color-text-primary) mb-2">Invigilator note</h2>
              <p className="text-body text-(--color-text-secondary)">{caseData.teacherNote}</p>
              <p className="text-label text-(--color-text-muted) mt-2">— {caseData.teacherName}</p>
            </div>
          )}

          {/* Actions */}
          {caseData.status === CaseStatus.PendingReview && (
            <div className="flex items-center gap-3">
              <Button onClick={() => setPenaltyOpen(true)}>Issue penalty</Button>
              <Button variant="danger" onClick={handleDismiss} loading={actionLoading === 'dismiss'}>Dismiss case</Button>
              <Button variant="secondary" onClick={handleEscalate} loading={actionLoading === 'escalate'}>Escalate</Button>
            </div>
          )}
        </div>

        {/* Right: Student info + Timeline */}
        <div className="space-y-6">
          {/* Student info */}
          <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
            <h2 className="text-heading text-(--color-text-primary) mb-3">Student information</h2>
            <dl className="space-y-2 text-body-sm">
              {[
                ['Name', caseData.studentName],
                ['Reg. No.', caseData.studentRegNo],
                ['Course', `${caseData.courseCode} — ${caseData.courseName}`],
                ['Room', caseData.classroomName],
                ['Seat', String(caseData.seatNumber)],
                ['Date', new Date(caseData.createdAt).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-2">
                  <dt className="text-(--color-text-muted)">{label}</dt>
                  <dd className="text-(--color-text-primary) font-medium text-right">{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          {/* Penalty info */}
          {caseData.penalty && (
            <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-error)/20 p-5">
              <h2 className="text-heading text-(--color-error) mb-3">Penalty issued</h2>
              <dl className="space-y-2 text-body-sm">
                <div className="flex justify-between"><dt className="text-(--color-text-muted)">Type</dt><dd className="font-medium text-(--color-error)">{caseData.penalty.type}</dd></div>
                <div className="flex justify-between"><dt className="text-(--color-text-muted)">Reference</dt><dd className="font-medium">{caseData.penalty.noticeReference}</dd></div>
                <div className="flex justify-between"><dt className="text-(--color-text-muted)">Issued by</dt><dd className="font-medium">{caseData.penalty.issuedByName}</dd></div>
              </dl>
              <p className="text-body-sm text-(--color-text-secondary) mt-3 pt-3 border-t border-(--color-border-default)">{caseData.penalty.description}</p>
            </div>
          )}

          {/* Appeal info */}
          {caseData.appeal && (
            <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-behavior-gaze)/20 p-5">
              <h2 className="text-heading text-(--color-behavior-gaze) mb-2">Appeal {caseData.appeal.status.toLowerCase()}</h2>
              <p className="text-body-sm text-(--color-text-secondary)">{caseData.appeal.statement}</p>
              {caseData.appeal.status === 'Open' && (
                <Button variant="secondary" size="sm" className="mt-3" onClick={() => navigate(`/hod/appeals/${caseData.appeal!.id}`)}>
                  Review appeal
                </Button>
              )}
            </div>
          )}

          {/* Timeline */}
          <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
            <h2 className="text-heading text-(--color-text-primary) mb-4">Audit timeline</h2>
            <div className="relative pl-6">
              <div className="absolute left-2 top-1 bottom-1 w-px bg-(--color-border-default)" />
              {caseData.timeline.map((entry) => (
                <div key={entry.id} className="relative pb-4 last:pb-0">
                  <div className="absolute left-[-18px] top-1 w-3 h-3 rounded-full bg-(--color-bg-surface) border-2 border-(--color-accent-primary)" />
                  <p className="text-body-sm font-medium text-(--color-text-primary)">{entry.action}</p>
                  {entry.details && <p className="text-body-sm text-(--color-text-muted) mt-0.5">{entry.details}</p>}
                  <p className="text-label text-(--color-text-muted) mt-1 flex items-center gap-1">
                    <Clock size={11} />
                    {new Date(entry.timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    {' — '}{entry.actorName}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <PenaltyModal
        isOpen={penaltyOpen}
        onClose={() => setPenaltyOpen(false)}
        caseData={caseData}
        onPenaltyIssued={(updated) => { setCaseData(updated); setPenaltyOpen(false); }}
      />
    </div>
  );
}
