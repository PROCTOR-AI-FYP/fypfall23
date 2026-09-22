import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ConfidenceBar } from '@/components/ui/DataDisplay';
import * as api from '@/lib/api';
import { type ThresholdConfig, BehaviorType } from '@/lib/types';

const behaviorLabels: Record<BehaviorType, { label: string; description: string }> = {
  [BehaviorType.GazeDeviation]: { label: 'Gaze Deviation', description: 'Detects sustained off-paper eye direction' },
  [BehaviorType.HeadPoseViolation]: { label: 'Head Pose Violation', description: 'Monitors head orientation beyond threshold angles' },
  [BehaviorType.LipMovement]: { label: 'Lip Movement', description: 'Active during silent-mode exams only' },
  [BehaviorType.PhoneDetected]: { label: 'Phone Detected', description: 'Mobile device presence on desk or in hand' },
  [BehaviorType.UnauthorisedObject]: { label: 'Unauthorised Object', description: 'Non-permitted items in desk area' },
};

export function ThresholdConfiguration() {
  const [configs, setConfigs] = useState<ThresholdConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.getThresholds().then(r => { setConfigs(r.data); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, []);

  const updateConfig = (id: string, field: 'sensitivity' | 'weight', value: number) => {
    setConfigs(prev => prev.map(c => c.id === id ? { ...c, [field]: value } : c));
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateThresholds(configs);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch { setError('Failed to save'); }
    setSaving(false);
  };

  if (loading) return <div className="flex justify-center py-16"><div className="h-8 w-8 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-display-lg text-(--color-text-primary)">Threshold Configuration</h1>
          <p className="text-body-sm text-(--color-text-secondary) mt-1">Configure detection sensitivity and signal weights for the composite score</p>
        </div>
        <Button onClick={handleSave} loading={saving}>
          <Save size={16} /> {saved ? 'Saved' : 'Save changes'}
        </Button>
      </div>

      {error && <div className="mb-4 px-4 py-3 bg-(--color-error-subtle) rounded-[6px] text-body-sm text-(--color-error)">{error}</div>}

      {/* Sensitivity Sliders */}
      <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) mb-6">
        <div className="px-5 py-4 border-b border-(--color-border-default)">
          <h2 className="text-heading text-(--color-text-primary)">Detection sensitivity</h2>
          <p className="text-body-sm text-(--color-text-muted) mt-0.5">Higher values increase detection rate but may produce more false positives</p>
        </div>
        <div className="divide-y divide-(--color-border-default)">
          {configs.map(config => {
            const info = behaviorLabels[config.behaviorType];
            return (
              <div key={config.id} className="px-5 py-4">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <p className="text-body font-medium text-(--color-text-primary)">{info.label}</p>
                    <p className="text-body-sm text-(--color-text-muted)">{info.description}</p>
                  </div>
                  <span className="text-heading text-(--color-accent-primary) tabular-nums min-w-[40px] text-right">{config.sensitivity}%</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={config.sensitivity}
                  onChange={e => updateConfig(config.id, 'sensitivity', parseInt(e.target.value))}
                  className="w-full h-2 rounded-full appearance-none cursor-pointer accent-[var(--color-accent-primary)] bg-(--color-bg-surface-raised)"
                />
              </div>
            );
          })}
        </div>
      </div>

      {/* Weight Table */}
      <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) mb-6">
        <div className="px-5 py-4 border-b border-(--color-border-default)">
          <h2 className="text-heading text-(--color-text-primary)">Signal weights</h2>
          <p className="text-body-sm text-(--color-text-muted) mt-0.5">Each signal's contribution to the composite suspicion score (must sum to 1.0)</p>
        </div>
        <table className="w-full">
          <thead><tr className="bg-(--color-bg-surface-raised)">
            <th className="px-5 py-3 text-left text-label text-(--color-text-secondary)">Signal</th>
            <th className="px-5 py-3 text-left text-label text-(--color-text-secondary)">Weight</th>
            <th className="px-5 py-3 text-left text-label text-(--color-text-secondary)" style={{ width: '200px' }}>Proportion</th>
          </tr></thead>
          <tbody>
            {configs.map(config => (
              <tr key={config.id} className="border-t border-(--color-border-default)">
                <td className="px-5 py-3 text-body font-medium text-(--color-text-primary)">{config.behaviorType}</td>
                <td className="px-5 py-3">
                  <input
                    type="number"
                    min={0} max={1} step={0.05}
                    value={config.weight}
                    onChange={e => updateConfig(config.id, 'weight', parseFloat(e.target.value) || 0)}
                    className="w-20 px-2 py-1 text-body bg-(--color-bg-surface-raised) border border-(--color-border-default) rounded-[4px] text-(--color-text-primary) tabular-nums"
                  />
                </td>
                <td className="px-5 py-3"><ConfidenceBar value={config.weight} /></td>
              </tr>
            ))}
            <tr className="border-t border-(--color-border-strong) bg-(--color-bg-surface-raised)">
              <td className="px-5 py-3 text-body font-medium text-(--color-text-primary)">Total</td>
              <td className="px-5 py-3 text-body font-medium text-(--color-text-primary) tabular-nums">
                {configs.reduce((s, c) => s + c.weight, 0).toFixed(2)}
              </td>
              <td className="px-5 py-3">
                {Math.abs(configs.reduce((s, c) => s + c.weight, 0) - 1) > 0.01 && (
                  <span className="text-label text-(--color-warning)">Weights should sum to 1.00</span>
                )}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Calibration Card */}
      <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
        <h2 className="text-heading text-(--color-text-primary) mb-3">Calibration provenance</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-body-sm">
          <div>
            <p className="text-(--color-text-muted) mb-1">Last calibrated</p>
            <p className="text-(--color-text-primary) font-medium">{new Date(configs[0]?.lastCalibrated || '').toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}</p>
          </div>
          <div>
            <p className="text-(--color-text-muted) mb-1">Calibrated by</p>
            <p className="text-(--color-text-primary) font-medium">{configs[0]?.calibratedBy || 'N/A'}</p>
          </div>
          <div>
            <p className="text-(--color-text-muted) mb-1">Model version</p>
            <p className="text-(--color-text-primary) font-medium">ProctorAI v2.1.4</p>
          </div>
        </div>
      </div>
    </div>
  );
}
