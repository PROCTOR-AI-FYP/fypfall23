import { useEffect, useState } from 'react';
import { Users, Building2, ShieldCheck, Activity } from 'lucide-react';
import { StatCard } from '@/components/ui/DataDisplay';
import * as api from '@/lib/api';
import type { AuditLogEntry } from '@/lib/types';

export function AdminDashboard() {
  const [recentActivity, setRecentActivity] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getAuditLog().then(res => {
      setRecentActivity(res.data.slice(0, 5));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="text-display-lg text-(--color-text-primary) mb-6">Admin Dashboard</h1>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={<Users size={18} />} label="Total users" value="22" trend={{ value: 8, label: 'this month' }} />
        <StatCard icon={<Activity size={18} />} label="Active sessions" value="1" color="var(--color-success)" />
        <StatCard icon={<ShieldCheck size={18} />} label="Cases today" value="4" color="var(--color-warning)" trend={{ value: 12, label: 'vs yesterday' }} />
        <StatCard icon={<Building2 size={18} />} label="Classrooms online" value="7/10" color="var(--color-behavior-head)" />
      </div>

      {/* Recent activity */}
      <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default)">
        <div className="px-5 py-4 border-b border-(--color-border-default)">
          <h2 className="text-heading text-(--color-text-primary)">Recent activity</h2>
        </div>
        <div className="divide-y divide-(--color-border-default)">
          {loading ? (
            <div className="px-5 py-8 flex justify-center">
              <div className="h-6 w-6 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" />
            </div>
          ) : recentActivity.length === 0 ? (
            <div className="px-5 py-8 text-center text-body-sm text-(--color-text-muted)">No recent activity</div>
          ) : (
            recentActivity.map(entry => (
              <div key={entry.id} className="px-5 py-3 flex items-start gap-4">
                <div className="w-8 h-8 rounded-full bg-(--color-bg-surface-raised) flex items-center justify-center text-(--color-text-muted) shrink-0 mt-0.5">
                  <Activity size={14} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-body-sm text-(--color-text-primary)">
                    <span className="font-medium">{entry.userName}</span>
                    {' '}{entry.action.toLowerCase()}
                  </p>
                  <p className="text-label text-(--color-text-muted) mt-0.5">{entry.details}</p>
                </div>
                <span className="text-label text-(--color-text-muted) whitespace-nowrap shrink-0">
                  {new Date(entry.timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
