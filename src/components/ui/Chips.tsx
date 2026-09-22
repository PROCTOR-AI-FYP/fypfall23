import { CaseStatus, BehaviorType } from '@/lib/types';
import {
  Eye, RotateCcw, AudioLines, Smartphone, ShieldAlert,
  Circle, CircleDot, CircleSlash, ArrowUpCircle,
} from 'lucide-react';
import type { ReactNode } from 'react';

// ── Behavior Chip ──────────────────────────

const behaviorConfig: Record<BehaviorType, { color: string; bg: string; icon: ReactNode }> = {
  [BehaviorType.GazeDeviation]: {
    color: 'var(--color-behavior-gaze)',
    bg: 'var(--color-behavior-gaze-subtle)',
    icon: <Eye size={12} />,
  },
  [BehaviorType.HeadPoseViolation]: {
    color: 'var(--color-behavior-head)',
    bg: 'var(--color-behavior-head-subtle)',
    icon: <RotateCcw size={12} />,
  },
  [BehaviorType.LipMovement]: {
    color: 'var(--color-behavior-lip)',
    bg: 'var(--color-behavior-lip-subtle)',
    icon: <AudioLines size={12} />,
  },
  [BehaviorType.PhoneDetected]: {
    color: 'var(--color-behavior-phone)',
    bg: 'var(--color-behavior-phone-subtle)',
    icon: <Smartphone size={12} />,
  },
  [BehaviorType.UnauthorisedObject]: {
    color: 'var(--color-behavior-object)',
    bg: 'var(--color-behavior-object-subtle)',
    icon: <ShieldAlert size={12} />,
  },
};

export function BehaviorChip({ type }: { type: BehaviorType }) {
  const config = behaviorConfig[type];
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[2px] text-label font-medium whitespace-nowrap"
      style={{ color: config.color, backgroundColor: config.bg }}
    >
      {config.icon}
      {type}
    </span>
  );
}

// ── Status Chip ────────────────────────────

const statusConfig: Record<CaseStatus, { color: string; bg: string; icon: ReactNode }> = {
  [CaseStatus.PendingReview]: {
    color: 'var(--color-status-pending)',
    bg: 'var(--color-status-pending-subtle)',
    icon: <CircleDot size={12} />,
  },
  [CaseStatus.Confirmed]: {
    color: 'var(--color-status-confirmed)',
    bg: 'var(--color-status-confirmed-subtle)',
    icon: <Circle size={12} fill="currentColor" />,
  },
  [CaseStatus.Dismissed]: {
    color: 'var(--color-status-dismissed)',
    bg: 'var(--color-status-dismissed-subtle)',
    icon: <CircleSlash size={12} />,
  },
  [CaseStatus.Escalated]: {
    color: 'var(--color-status-escalated)',
    bg: 'var(--color-status-escalated-subtle)',
    icon: <ArrowUpCircle size={12} />,
  },
};

export function StatusChip({ status }: { status: CaseStatus }) {
  const config = statusConfig[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[2px] text-label font-medium whitespace-nowrap"
      style={{ color: config.color, backgroundColor: config.bg }}
    >
      {config.icon}
      {status}
    </span>
  );
}
