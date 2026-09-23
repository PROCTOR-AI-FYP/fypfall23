import { useEffect, useState } from 'react';
import { Shield, FileText, Scale, AlertTriangle } from 'lucide-react';
import { StatCard } from '@/components/ui/DataDisplay';
import * as api from '@/lib/api';
import { type Case, BehaviorType, CaseStatus } from '@/lib/types';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const TREND_DAYS = 8;

export function HodDashboard() {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({ pending: 0, confirmed: 0, appeals: 0, dismissed: 0 });
  const [cases, setCases] = useState<Case[]>([]);

  useEffect(() => {
    Promise.all([api.getCases(), api.getAppeals()]).then(([casesRes, appealsRes]) => {
      const cases = casesRes.data;
      setCases(cases);
      setStats({
        pending: cases.filter(c => c.status === CaseStatus.PendingReview).length,
        confirmed: cases.filter(c => c.status === CaseStatus.Confirmed).length,
        appeals: appealsRes.data.filter(a => a.status === 'Open').length,
        dismissed: cases.filter(c => c.status === CaseStatus.Dismissed).length,
      });
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const countBehavior = (type: BehaviorType) => cases.filter(c => c.behaviourTypes.includes(type)).length;

  const statusData = [
    { name: 'Pending', value: stats.pending, color: 'var(--color-status-pending)' },
    { name: 'Confirmed', value: stats.confirmed, color: 'var(--color-status-confirmed)' },
    { name: 'Dismissed', value: stats.dismissed, color: 'var(--color-status-dismissed)' },
  ];

  const trendData = Array.from({ length: TREND_DAYS }, (_, i) => {
    const day = new Date(Date.now() - (TREND_DAYS - 1 - i) * 86_400_000);
    return {
      date: day.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
      cases: cases.filter(c => new Date(c.createdAt).toDateString() === day.toDateString()).length,
    };
  });

  const behaviorData = [
    { name: 'Gaze', count: countBehavior(BehaviorType.GazeDeviation), color: 'var(--color-behavior-gaze)' },
    { name: 'Head Pose', count: countBehavior(BehaviorType.HeadPoseViolation), color: 'var(--color-behavior-head)' },
    { name: 'Lip Mvmt', count: countBehavior(BehaviorType.LipMovement), color: 'var(--color-behavior-lip)' },
    { name: 'Phone', count: countBehavior(BehaviorType.PhoneDetected), color: 'var(--color-behavior-phone)' },
    { name: 'Object', count: countBehavior(BehaviorType.UnauthorisedObject), color: 'var(--color-behavior-object)' },
  ];

  if (loading) return <div className="flex justify-center py-16"><div className="h-8 w-8 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div>
      <h1 className="text-display-lg text-(--color-text-primary) mb-6">HOD Dashboard</h1>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={<AlertTriangle size={18} />} label="Pending review" value={stats.pending} color="var(--color-warning)" />
        <StatCard icon={<Shield size={18} />} label="Confirmed cases" value={stats.confirmed} color="var(--color-error)" />
        <StatCard icon={<Scale size={18} />} label="Open appeals" value={stats.appeals} color="var(--color-behavior-gaze)" />
        <StatCard icon={<FileText size={18} />} label="Dismissed" value={stats.dismissed} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Cases by status */}
        <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
          <h2 className="text-heading text-(--color-text-primary) mb-4">Cases by status</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={statusData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} allowDecimals={false} />
              <Tooltip contentStyle={{ backgroundColor: 'var(--color-bg-surface-overlay)', border: '1px solid var(--color-border-default)', borderRadius: '6px', fontSize: '13px' }} />
              <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                {statusData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Cases over time */}
        <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
          <h2 className="text-heading text-(--color-text-primary) mb-4">Cases over time</h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={trendData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
              <XAxis dataKey="date" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} allowDecimals={false} />
              <Tooltip contentStyle={{ backgroundColor: 'var(--color-bg-surface-overlay)', border: '1px solid var(--color-border-default)', borderRadius: '6px', fontSize: '13px' }} />
              <Line type="monotone" dataKey="cases" stroke="var(--color-accent-primary)" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Behavior distribution */}
      <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
        <h2 className="text-heading text-(--color-text-primary) mb-4">Cases by behavior type</h2>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={behaviorData} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
            <XAxis type="number" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} allowDecimals={false} />
            <YAxis dataKey="name" type="category" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} width={80} />
            <Tooltip contentStyle={{ backgroundColor: 'var(--color-bg-surface-overlay)', border: '1px solid var(--color-border-default)', borderRadius: '6px', fontSize: '13px' }} />
            <Bar dataKey="count" radius={[0, 3, 3, 0]}>
              {behaviorData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
