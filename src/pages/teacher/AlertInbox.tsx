import { useEffect, useState } from 'react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { FormField, TextArea } from '@/components/ui/FormElements';
import { BehaviorChip } from '@/components/ui/Chips';
import { ConfidenceBar } from '@/components/ui/DataDisplay';
import { EvidenceViewer } from '@/components/evidence/EvidenceViewer';
import * as api from '@/lib/api';
import type { DetectionEvent } from '@/lib/types';

export function AlertInbox() {
  const [alerts, setAlerts] = useState<DetectionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedAlert, setSelectedAlert] = useState<DetectionEvent | null>(null);
  const [teacherNote, setTeacherNote] = useState('');
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    setError('');
    // Every alert from the sessions this teacher invigilates.
    api.getDetectionEvents().then(r => {
      setAlerts(r.data.filter(d => d.status === 'New' || d.status === 'Reviewed'));
      setLoading(false);
    }).catch(e => { setError(e.message); setLoading(false); });
  };

  useEffect(() => { load(); }, []);

  // New alerts arrive live (Socket.IO alert:new), no refresh needed.
  useEffect(() => api.subscribeToAlerts(event => {
    setAlerts(prev => (prev.some(a => a.id === event.id) ? prev : [event, ...prev]));
  }), []);

  const handleConfirm = async () => {
    if (!selectedAlert) return;
    setSaving(true);
    try {
      await api.createCaseFromDetection(selectedAlert.id, teacherNote || 'Confirmed from alert inbox');
      setAlerts(prev => prev.filter(a => a.id !== selectedAlert.id));
      setSelectedAlert(null);
      setTeacherNote('');
    } catch {
      setError('Failed to confirm alert');
    }
    setSaving(false);
  };

  const handleDismiss = async () => {
    if (!selectedAlert) return;
    setSaving(true);
    try {
      await api.dismissDetection(selectedAlert.id);
      setAlerts(prev => prev.filter(a => a.id !== selectedAlert.id));
      setSelectedAlert(null);
      setTeacherNote('');
    } catch {
      setError('Failed to dismiss alert');
    }
    setSaving(false);
  };

  const columns: Column<DetectionEvent>[] = [
    { key: 'detectedAt', header: 'Time', sortable: true, width: '100px', render: (a) => (
      <span className="text-body-sm text-(--color-text-muted) tabular-nums">
        {new Date(a.detectedAt).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
      </span>
    )},
    { key: 'studentName', header: 'Student', sortable: true, render: (a) => (
      <div><span className="font-medium text-(--color-text-primary)">{a.studentName}</span><br /><span className="text-label text-(--color-text-muted)">Seat {a.seatNumber}</span></div>
    )},
    { key: 'behaviourTypes', header: 'Behaviors', render: (a) => (
      <div className="flex flex-wrap gap-1">{a.behaviourTypes.map(b => <BehaviorChip key={b} type={b} />)}</div>
    )},
    { key: 'compositeScore', header: 'Confidence', width: '140px', render: (a) => <ConfidenceBar value={a.compositeScore} /> },
  ];

  return (
    <div>
      <h1 className="text-display-lg text-(--color-text-primary) mb-6">Alert Inbox</h1>
      
      <DataTable 
        columns={columns} 
        data={alerts} 
        loading={loading} 
        error={error} 
        onRetry={load}
        emptyMessage="No pending alerts. All clear!"
        onRowClick={a => setSelectedAlert(a)}
        rowKey={a => a.id}
      />

      <Modal 
        isOpen={!!selectedAlert} 
        onClose={() => { setSelectedAlert(null); setTeacherNote(''); }} 
        title="Review Alert"
        size="lg"
        footer={
          <>
            <Button variant="secondary" onClick={() => setSelectedAlert(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDismiss} loading={saving}>Dismiss</Button>
            <Button onClick={handleConfirm} loading={saving}>Confirm as Case</Button>
          </>
        }
      >
        {selectedAlert && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Evidence */}
              <div className="self-start rounded-[6px] border border-(--color-border-default) overflow-hidden">
                <EvidenceViewer
                  detectionId={selectedAlert.id}
                  subjectLabel={`seat ${selectedAlert.seatNumber}, ${selectedAlert.studentName}`}
                />
              </div>

              {/* Alert Details */}
              <div className="space-y-4">
                <div className="bg-(--color-bg-surface-raised) p-3 rounded-[6px]">
                  <p className="text-label text-(--color-text-muted) mb-1">Student</p>
                  <p className="font-medium">{selectedAlert.studentName} (Seat {selectedAlert.seatNumber})</p>
                </div>
                
                <div>
                  <p className="text-label text-(--color-text-muted) mb-2">Detected Behaviors</p>
                  <div className="space-y-2">
                    {selectedAlert.behaviourTypes.map(b => (
                       <div key={b} className="flex items-center gap-3">
                         <div className="w-40"><BehaviorChip type={b} /></div>
                         <div className="flex-1"><ConfidenceBar value={selectedAlert.perSignal[b] || 0} showLabel={false} /></div>
                         <span className="text-label w-8 text-right">{Math.round((selectedAlert.perSignal[b] || 0)*100)}%</span>
                       </div>
                    ))}
                  </div>
                </div>

                <div className="pt-2 border-t border-(--color-border-default)">
                   <div className="flex items-center gap-3">
                     <span className="text-body font-medium w-40">Composite Score</span>
                     <div className="flex-1"><ConfidenceBar value={selectedAlert.compositeScore} /></div>
                   </div>
                </div>
              </div>
            </div>

            <FormField label="Invigilator Note (Optional)">
              <TextArea 
                value={teacherNote} 
                onChange={e => setTeacherNote(e.target.value)}
                placeholder="Add contextual notes for the HOD if confirming this as a case..."
                rows={3}
              />
            </FormField>
          </div>
        )}
      </Modal>
    </div>
  );
}
