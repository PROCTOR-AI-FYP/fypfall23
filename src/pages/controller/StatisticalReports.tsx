import { useEffect, useState } from 'react';
import { Download, Users, Briefcase, FileText } from 'lucide-react';
import { StatCard, LoadingState } from '@/components/ui/DataDisplay';
import { Button } from '@/components/ui/Button';
import * as api from '@/lib/api';
import type { StatisticalReport } from '@/lib/types';
import { BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Legend } from 'recharts';

export function StatisticalReports() {
  const [report, setReport] = useState<StatisticalReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getStatisticalReports().then(r => { setReport(r.data); setLoading(false); });
  }, []);

  if (loading) return <LoadingState />;
  if (!report) return <div className="text-center py-16">Failed to load report</div>;

  const COLORS = ['#2B5EA7', '#DC2626', '#D97706', '#059669', '#7C3AED'];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-display-lg text-(--color-text-primary)">Statistical Reports</h1>
          <p className="text-body-sm text-(--color-text-secondary)">Institutional overview of academic integrity metrics</p>
        </div>
        <Button variant="secondary"><Download size={16} /> Export Full PDF</Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={<FileText size={18} />} label="Total Cases" value={report.totalCases} />
        <StatCard icon={<Briefcase size={18} />} label="Appeals Filed" value={report.totalAppeals} />
        <StatCard icon={<Users size={18} />} label="Appeal Success Rate" value={`${Math.round(report.appealSuccessRate * 100)}%`} color="var(--color-success)" />
        <StatCard icon={<Download size={18} />} label="Avg Resolution Time" value={`${report.averageResolutionDays} days`} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Incidents by Department */}
        <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
          <h2 className="text-heading text-(--color-text-primary) mb-4">Incidents by Department</h2>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={report.incidentsByDepartment} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
              <XAxis type="number" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <YAxis dataKey="department" type="category" tick={{ fontSize: 11, fill: 'var(--color-text-secondary)' }} width={120} />
              <RechartsTooltip contentStyle={{ backgroundColor: 'var(--color-bg-surface-overlay)', border: '1px solid var(--color-border-default)', borderRadius: '6px' }} />
              <Bar dataKey="count" fill="var(--color-accent-primary)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Behavior Distribution */}
        <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
          <h2 className="text-heading text-(--color-text-primary) mb-4">Integrity Violation Distribution</h2>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie data={report.behaviorDistribution} innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="count" nameKey="behavior">
                {report.behaviorDistribution.map((_, i) => <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <RechartsTooltip contentStyle={{ backgroundColor: 'var(--color-bg-surface-overlay)', border: '1px solid var(--color-border-default)', borderRadius: '6px' }} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Incidents Over Time */}
        <div className="col-span-1 lg:col-span-2 bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
          <h2 className="text-heading text-(--color-text-primary) mb-4">Incidents Over Time (Last 30 Days)</h2>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={report.incidentsOverTime}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-default)" />
              <XAxis dataKey="date" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} tickFormatter={(val) => new Date(val).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} />
              <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <RechartsTooltip contentStyle={{ backgroundColor: 'var(--color-bg-surface-overlay)', border: '1px solid var(--color-border-default)', borderRadius: '6px' }} />
              <Line type="monotone" dataKey="count" stroke="var(--color-error)" strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 6 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
