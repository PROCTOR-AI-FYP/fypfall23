// ── Confidence Bar ─────────────────────────

export function ConfidenceBar({ value, showLabel = true }: { value: number; showLabel?: boolean }) {
  const percentage = Math.round(value * 100);
  const color =
    percentage >= 80 ? 'var(--color-error)' :
    percentage >= 60 ? 'var(--color-warning)' :
    'var(--color-success)';

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-(--color-bg-surface-raised) rounded-[2px] overflow-hidden min-w-[60px]">
        <div
          className="h-full rounded-[2px] transition-all duration-300"
          style={{ width: `${percentage}%`, backgroundColor: color }}
        />
      </div>
      {showLabel && (
        <span className="text-label font-medium tabular-nums min-w-[36px] text-right" style={{ color }}>
          {percentage}%
        </span>
      )}
    </div>
  );
}

// ── Stat Card ──────────────────────────────

import type { ReactNode } from 'react';

interface StatCardProps {
  icon: ReactNode;
  label: string;
  value: string | number;
  trend?: { value: number; label: string };
  color?: string;
}

export function StatCard({ icon, label, value, trend, color }: StatCardProps) {
  return (
    <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-5">
      <div className="flex items-start justify-between mb-3">
        <div
          className="w-9 h-9 rounded-[6px] flex items-center justify-center"
          style={{
            backgroundColor: color ? `${color}15` : 'var(--color-accent-primary-subtle)',
            color: color || 'var(--color-accent-primary)',
          }}
        >
          {icon}
        </div>
        {trend && (
          <span
            className={`text-label font-medium ${trend.value >= 0 ? 'text-(--color-success)' : 'text-(--color-error)'}`}
          >
            {trend.value >= 0 ? '+' : ''}{trend.value}% {trend.label}
          </span>
        )}
      </div>
      <p className="text-stat text-(--color-text-primary)">{value}</p>
      <p className="text-body-sm text-(--color-text-secondary) mt-1">{label}</p>
    </div>
  );
}

// ── Empty State ────────────────────────────

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      {icon && (
        <div className="w-12 h-12 rounded-full bg-(--color-bg-surface-raised) flex items-center justify-center text-(--color-text-muted) mb-4">
          {icon}
        </div>
      )}
      <h3 className="text-heading text-(--color-text-primary) mb-1">{title}</h3>
      <p className="text-body-sm text-(--color-text-muted) max-w-sm">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ── Error State ────────────────────────────

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <div className="w-12 h-12 rounded-full bg-(--color-error-subtle) flex items-center justify-center text-(--color-error) mb-4 text-xl font-bold">
        !
      </div>
      <h3 className="text-heading text-(--color-text-primary) mb-1">Something went wrong</h3>
      <p className="text-body-sm text-(--color-text-muted) max-w-sm">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-4 px-4 py-2 text-body-sm font-medium text-(--color-accent-primary) hover:bg-(--color-accent-primary-subtle) rounded-[6px] transition-colors cursor-pointer"
        >
          Try again
        </button>
      )}
    </div>
  );
}

// ── Loading State ──────────────────────────

export function LoadingState({ message = 'Loading...' }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6">
      <div className="h-8 w-8 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin mb-4" />
      <p className="text-body-sm text-(--color-text-muted)">{message}</p>
    </div>
  );
}
