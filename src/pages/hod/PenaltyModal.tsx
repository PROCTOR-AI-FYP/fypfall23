import { useState } from 'react';
import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';
import { FormField, Select, TextArea } from '@/components/ui/FormElements';
import { useAuth } from '@/lib/auth-context';
import * as api from '@/lib/api';
import { type Case, PenaltyType } from '@/lib/types';

interface PenaltyModalProps {
  isOpen: boolean;
  onClose: () => void;
  caseData: Case;
  onPenaltyIssued: (updatedCase: Case) => void;
}

export function PenaltyModal({ isOpen, onClose, caseData, onPenaltyIssued }: PenaltyModalProps) {
  const { user } = useAuth();
  const [type, setType] = useState<PenaltyType>(PenaltyType.FormalWarning);
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [confirmed, setConfirmed] = useState(false);

  const handleIssue = async () => {
    if (!description.trim()) { setError('Description is required'); return; }
    setSaving(true);
    setError('');
    try {
      await api.issuePenalty(caseData.id, {
        type,
        description,
        issuedBy: user?.id || '',
        issuedByName: user?.name || '',
      });
      setConfirmed(true);

      // Brief confirmation moment then close
      setTimeout(async () => {
        const updated = await api.getCase(caseData.id);
        onPenaltyIssued(updated.data);
        setConfirmed(false);
        setDescription('');
        setType(PenaltyType.FormalWarning);
      }, 1500);
    } catch {
      setError('Failed to issue penalty');
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Issue penalty"
      size="lg"
      footer={
        !confirmed ? (
          <>
            <Button variant="secondary" onClick={onClose}>Cancel</Button>
            <Button variant="danger" onClick={handleIssue} loading={saving}>Issue penalty</Button>
          </>
        ) : undefined
      }
    >
      {confirmed ? (
        <div className="flex flex-col items-center py-8">
          {/* Confirmation moment — solemn, not celebratory */}
          <div className="w-16 h-16 rounded-full border-2 border-(--color-accent-primary) flex items-center justify-center mb-4">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <p className="text-heading text-(--color-text-primary)">Penalty issued</p>
          <p className="text-body-sm text-(--color-text-muted) mt-1">Notice reference: {caseData.referenceNo}</p>
        </div>
      ) : (
        <div className="space-y-5">
          {error && <div className="px-4 py-3 bg-(--color-error-subtle) rounded-[6px] text-body-sm text-(--color-error)">{error}</div>}

          {/* Case summary */}
          <div className="bg-(--color-bg-surface-raised) rounded-[6px] p-4">
            <div className="grid grid-cols-2 gap-3 text-body-sm">
              <div><span className="text-(--color-text-muted)">Student:</span> <span className="font-medium">{caseData.studentName}</span></div>
              <div><span className="text-(--color-text-muted)">Reg. No.:</span> <span className="font-medium">{caseData.studentRegNo}</span></div>
              <div><span className="text-(--color-text-muted)">Course:</span> <span className="font-medium">{caseData.courseCode}</span></div>
              <div><span className="text-(--color-text-muted)">Case:</span> <span className="font-medium text-(--color-accent-primary)">{caseData.referenceNo}</span></div>
            </div>
          </div>

          <FormField label="Penalty type" required>
            <Select value={type} onChange={e => setType(e.target.value as PenaltyType)}>
              {Object.values(PenaltyType).map(t => <option key={t} value={t}>{t}</option>)}
            </Select>
          </FormField>

          <FormField label="Description" required error={error && !description.trim() ? 'Required' : undefined}>
            <TextArea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Describe the penalty and its justification..."
              rows={4}
              hasError={!!error && !description.trim()}
            />
          </FormField>

          {/* Document preview */}
          <div className="bg-(--color-bg-surface-raised) rounded-[6px] p-4 border border-(--color-border-default)">
            <h3 className="text-label text-(--color-text-muted) mb-2">Notice preview</h3>
            <div className="text-body-sm text-(--color-text-primary) space-y-2">
              <p className="font-medium">Notice of Academic Integrity Action</p>
              <p>Reference: {caseData.referenceNo}</p>
              <p>Student: {caseData.studentName} ({caseData.studentRegNo})</p>
              <p>Penalty: {type}</p>
              <p>Course: {caseData.courseCode} — {caseData.courseName}</p>
              {description && <p className="text-(--color-text-secondary) italic">"{description}"</p>}
              <p className="text-label text-(--color-text-muted) mt-3">Issued by: {user?.name || 'Head of Department'}</p>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
