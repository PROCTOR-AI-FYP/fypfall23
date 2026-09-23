import { useEffect, useState } from 'react';
import { Users, Building2, ShieldCheck, Activity } from 'lucide-react';
import { StatCard } from '@/components/ui/DataDisplay';
import * as api from '@/lib/api';
import { type AuditLogEntry, SessionStatus } from '@/lib/types';

interface AdminStats {
  users: number;
  userGrowth?: number;
  activeSessions: number;
  casesToday: number;
  caseTrend?: number;
  camerasOnline: string;
}

function percentChange(current: number, previous: number): number | undefined {
  return previous > 0 ? Math.round(((current - previous) / previous) * 100) : undefined;
}

function sameDay(iso: string, day: Date): boolean {
  return new Date(iso).toDateString() === day.toDateString();
}

export function AdminDashboard() {
  const [recentActivity, setRecentActivity] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<AdminStats | null>(null);

  useEffect(() => {
    api.getAuditLog().then(res => {
      setRecentActivity(res.data.slice(0, 5));
      setLoading(false);
    }).catch(() => setLoading(false));

    Promise.all([api.getUsers(), api.getSessions({ status: SessionStatus.InProgress }), api.getCases(), api.getClassrooms()])
      .then(([usersRes, sessionsRes, casesRes, classroomsRes]) => {
        const now = new Date();
        const yesterday = new Date(now.getTime() - 86_400_000);
        const newThisMonth = usersRes.data.filter(u => {
          const created = new Date(u.createdAt);
          return created.getFullYear() === now.getFullYear() && created.getMonth() === now.getMonth();
        }).length;
        const casesToday = casesRes.data.filter(c => sameDay(c.createdAt, now)).length;
        const casesYesterday = casesRes.data.filter(c => sameDay(c.createdAt, yesterday)).length;
        const online = classroomsRes.data.filter(c => c.cameraStatus === 'Online').length;
        setStats({
          users: usersRes.total,
          userGrowth: percentChange(usersRes.total, usersRes.total - newThisMonth),
          activeSessions: sessionsRes.total,
          casesToday,
          caseTrend: percentChange(casesToday, casesYesterday),
          camerasOnline: `${online}/${classroomsRes.total}`,
        });
      })
      .catch(() => { /* cards keep their placeholder */ });
  }, []);

  return (
    <div>
      <h1 className="text-display-lg text-(--color-text-primary) mb-6">Admin Dashboard</h1>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={<Users size={18} />} label="Total users" value={stats?.users ?? '—'} trend={stats?.userGrowth !== undefined ? { value: stats.userGrowth, label: 'this month' } : undefined} />
        <StatCard icon={<Activity size={18} />} label="Active sessions" value={stats?.activeSessions ?? '—'} color="var(--color-success)" />
        <StatCard icon={<ShieldCheck size={18} />} label="Cases today" value={stats?.casesToday ?? '—'} color="var(--color-warning)" trend={stats?.caseTrend !== undefined ? { value: stats.caseTrend, label: 'vs yesterday' } : undefined} />
        <StatCard icon={<Building2 size={18} />} label="Classrooms online" value={stats?.camerasOnline ?? '—'} color="var(--color-behavior-head)" />
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
