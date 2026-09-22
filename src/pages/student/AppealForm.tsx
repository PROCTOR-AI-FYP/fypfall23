import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Send } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { FormField, TextArea, Input } from '@/components/ui/FormElements';
import { useAuth } from '@/lib/auth-context';
import * as api from '@/lib/api';
import type { Case } from '@/lib/types';

export function AppealForm() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [caseData, setCaseData] = useState<Case | null>(null);
  const [statement, setStatement] = useState('');
  const [supportingInfo, setSupportingInfo] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    api.getCase(id).then(r => { setCaseData(r.data); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [id]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id || !user || !statement.trim()) return;
    setSaving(true);
    try {
      await api.submitAppeal(id, {
        studentId: user.id,
        studentName: user.name,
        studentRegNo: user.registrationNo || 'N/A',
        statement,
        supportingInfo
      });
      navigate(`/student/cases/${id}`);
    } catch {
      setError('Failed to submit appeal');
      setSaving(false);
    }
  };

  if (loading) return <div className="py-16 flex justify-center"><div className="w-8 h-8 rounded-full border-2 border-(--color-accent-primary) border-t-transparent animate-spin" /></div>;
  if (!caseData) return <div className="py-16 text-center text-(--color-text-muted)">Case not found</div>;

  return (
    <div className="max-w-2xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate(`/student/cases/${id}`)} className="p-2 rounded-[6px] text-(--color-text-muted) hover:bg-(--color-bg-surface-raised)">
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-display-lg text-(--color-text-primary)">File an Appeal</h1>
          <p className="text-body-sm text-(--color-text-secondary)">Case {caseData.referenceNo}</p>
        </div>
      </div>

      <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-6">
        <div className="mb-6 p-4 bg-(--color-bg-surface-raised) rounded-[6px] text-body-sm">
           <p className="font-medium text-(--color-text-primary) mb-2">Appeal Guidelines</p>
           <ul className="list-disc pl-5 text-(--color-text-secondary) space-y-1">
             <li>Appeals must be based on factual errors in the case details or procedural irregularities.</li>
             <li>Provide clear, specific information.</li>
             <li>The Head of Department's decision on this appeal is final.</li>
           </ul>
        </div>

        {error && <div className="mb-4 p-3 bg-(--color-error-subtle) text-(--color-error) rounded-[6px] text-body-sm">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-6">
          <FormField label="Appeal Statement" required>
             <TextArea 
               value={statement} 
               onChange={e => setStatement(e.target.value)} 
               placeholder="Explain why the penalty should be reviewed..."
               rows={6}
             />
          </FormField>
          
          <FormField label="Link to Supporting Evidence (Optional)">
             <Input 
               value={supportingInfo} 
               onChange={e => setSupportingInfo(e.target.value)} 
               placeholder="e.g. Google Drive link to documents"
             />
          </FormField>

          <div className="pt-4 border-t border-(--color-border-default) flex justify-end">
            <Button type="submit" loading={saving} disabled={!statement.trim()}>
              <Send size={16} /> Submit Appeal
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
