import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Archive, ExternalLink, Film, Hourglass, ImageOff, RefreshCw, RotateCw, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import * as api from '@/lib/api';
import type { CaseMedia } from '@/lib/types';

// ── Props ──────────────────────────────────

type EvidenceTarget =
  | { caseId: string; detectionId?: never }
  | { detectionId: string; caseId?: never };

type EvidenceViewerProps = EvidenceTarget & {
  /** Blurs the media and removes it from the tab order (privacy toggle). */
  concealed?: boolean;
  /** Who/where the evidence is of, e.g. "Seat 14, Ahmed Raza". Used in accessible names. */
  subjectLabel?: string;
  className?: string;
};

type TargetKind = 'case' | 'detection';

/**
 * Shows the review evidence for a case or a detection: the short review clip
 * while it exists, a "still processing" notice before upload finishes, and the
 * permanent record image once the clip has been deleted after review.
 */
export function EvidenceViewer(props: EvidenceViewerProps) {
  const kind: TargetKind = props.caseId !== undefined ? 'case' : 'detection';
  const id = props.caseId ?? props.detectionId ?? '';
  // Keyed so all fetch and recovery state resets when the target changes.
  return (
    <EvidenceViewerInner
      key={`${kind}:${id}`}
      kind={kind}
      id={id}
      concealed={props.concealed ?? false}
      subjectLabel={props.subjectLabel}
      className={props.className}
    />
  );
}

// ── Helpers ────────────────────────────────

// Signed media URLs expire. A media error triggers one silent refetch; a second
// error inside this window is treated as a real failure and needs a manual
// reload. Outside the window (e.g. the refreshed link expired later in a long
// review) the silent refetch is allowed again.
const AUTO_RETRY_WINDOW_MS = 30_000;

function fetchMedia(kind: TargetKind, id: string) {
  return kind === 'case' ? api.getCaseMedia(id) : api.getDetectionMedia(id);
}

function errorMessage(e: unknown): string {
  if (e && typeof e === 'object' && 'message' in e && typeof e.message === 'string') return e.message;
  return 'The server did not respond.';
}

function formatDuration(totalSeconds: number): string {
  const rounded = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(rounded / 60);
  const seconds = rounded % 60;
  const secPart = `${seconds} ${seconds === 1 ? 'second' : 'seconds'}`;
  if (minutes === 0) return secPart;
  const minPart = `${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`;
  return seconds === 0 ? minPart : `${minPart} ${secPart}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

// ── Inner component ────────────────────────

type LoadResult =
  | { attempt: number; status: 'ok'; media: CaseMedia }
  | { attempt: number; status: 'error'; message: string };

type Recovery = 'idle' | 'refreshing' | 'failed';

interface InnerProps {
  kind: TargetKind;
  id: string;
  concealed: boolean;
  subjectLabel?: string;
  className?: string;
}

function EvidenceViewerInner({ kind, id, concealed, subjectLabel, className = '' }: InnerProps) {
  const captionId = useId();
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<LoadResult | null>(null);
  const [recovery, setRecovery] = useState<Recovery>('idle');
  // Bumped on every in-place refresh so the media element remounts with the new URL.
  const [mediaVersion, setMediaVersion] = useState(0);
  const lastAutoRetryAt = useRef<number | null>(null);
  const resumeAt = useRef(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMedia(kind, id)
      .then(r => { if (!cancelled) setResult({ attempt, status: 'ok', media: r.data }); })
      .catch(e => { if (!cancelled) setResult({ attempt, status: 'error', message: errorMessage(e) }); });
    return () => { cancelled = true; };
  }, [kind, id, attempt]);

  // Never keep playing behind the privacy blur.
  useEffect(() => {
    if (concealed) videoRef.current?.pause();
  }, [concealed]);

  const loading = result === null || result.attempt !== attempt;

  const reload = () => {
    setRecovery('idle');
    lastAutoRetryAt.current = null;
    resumeAt.current = 0;
    setAttempt(a => a + 1);
  };

  // Refetch without dropping back to the loading skeleton, then swap the URL.
  const refreshInPlace = async () => {
    const forAttempt = attempt;
    setRecovery('refreshing');
    try {
      const r = await fetchMedia(kind, id);
      setResult(prev => (prev && prev.attempt === forAttempt ? { attempt: forAttempt, status: 'ok', media: r.data } : prev));
      setMediaVersion(v => v + 1);
      setRecovery('idle');
    } catch {
      setRecovery('failed');
    }
  };

  const handleMediaError = () => {
    if (recovery === 'refreshing') return;
    if (videoRef.current) resumeAt.current = videoRef.current.currentTime;
    const now = Date.now();
    const canAutoRetry = lastAutoRetryAt.current === null || now - lastAutoRetryAt.current > AUTO_RETRY_WINDOW_MS;
    if (canAutoRetry) {
      lastAutoRetryAt.current = now;
      void refreshInPlace();
    } else {
      setRecovery('failed');
    }
  };

  const manualMediaReload = () => {
    lastAutoRetryAt.current = Date.now();
    void refreshInPlace();
  };

  const handleLoadedMetadata = () => {
    const video = videoRef.current;
    if (video && resumeAt.current > 0) {
      video.currentTime = Math.min(resumeAt.current, video.duration || resumeAt.current);
      resumeAt.current = 0;
    }
  };

  // ── Loading ──
  if (loading) {
    return (
      <div className={className} role="status" aria-busy="true">
        <div className="aspect-video bg-(--color-bg-surface-raised) flex flex-col items-center justify-center gap-3">
          <div className="h-6 w-6 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" aria-hidden="true" />
          <p className="text-body-sm text-(--color-text-muted)">Loading evidence...</p>
        </div>
        <div className="px-4 py-3 flex gap-3" aria-hidden="true">
          <div className="h-3 w-24 rounded-[2px] bg-(--color-bg-surface-raised)" />
          <div className="h-3 w-16 rounded-[2px] bg-(--color-bg-surface-raised)" />
        </div>
      </div>
    );
  }

  // ── Fetch error ──
  if (result.status === 'error') {
    return (
      <div className={className}>
        <StatePanel
          role="alert"
          icon={<TriangleAlert size={20} aria-hidden="true" />}
          tone="error"
          title="Evidence could not be loaded"
          description={result.message}
          action={
            <Button variant="secondary" size="sm" onClick={reload}>
              <RotateCw size={14} aria-hidden="true" />
              Try again
            </Button>
          }
        />
      </div>
    );
  }

  const { media } = result;
  const subject = subjectLabel ? ` for ${subjectLabel}` : '';

  // ── Pending upload ──
  if (media.clipStatus === 'pending_upload') {
    return (
      <div className={className}>
        <StatePanel
          role="status"
          icon={<Hourglass size={20} aria-hidden="true" />}
          tone="warning"
          title="Clip still processing"
          description="The review clip for this detection is still being compressed and uploaded. It will appear here once processing finishes."
          action={
            <Button variant="secondary" size="sm" onClick={reload}>
              <RefreshCw size={14} aria-hidden="true" />
              Check again
            </Button>
          }
        />
      </div>
    );
  }

  // ── Deleted after review: permanent record image ──
  if (media.clipStatus === 'deleted_after_review') {
    const imageUrl = media.recordImageUrl;
    return (
      <div className={className}>
        {!imageUrl ? (
          <StatePanel
            icon={<ImageOff size={20} aria-hidden="true" />}
            tone="neutral"
            title="No record image available"
            description="The server did not return a record image for this detection."
          />
        ) : recovery === 'failed' ? (
          <MediaFailedPanel noun="record image" onReload={manualMediaReload} />
        ) : (
          <ConcealableFrame concealed={concealed} refreshing={recovery === 'refreshing'} refreshingLabel="Refreshing the image link...">
            <img
              key={mediaVersion}
              src={imageUrl}
              alt={`Record image${subject}: four frames from the deleted review clip, arranged in a two by two grid.`}
              onError={handleMediaError}
              className="w-full h-full object-contain"
            />
          </ConcealableFrame>
        )}
        <div className="px-4 py-3 flex items-start gap-2.5 border-t border-(--color-border-default)">
          <Archive size={16} className="mt-0.5 shrink-0 text-(--color-text-secondary)" aria-hidden="true" />
          <div className="text-body-sm">
            <p className="font-medium text-(--color-text-primary)">Clip deleted after review</p>
            <p className="text-(--color-text-secondary) mt-0.5">
              The video clip was deleted when the review was finalised
              {media.clipDeletedAt ? (
                <> on <time dateTime={media.clipDeletedAt}>{formatDate(media.clipDeletedAt)}</time></>
              ) : null}
              . This still image, made from frames of the clip, is kept as the record.
            </p>
            {imageUrl && recovery !== 'failed' && !concealed && (
              <a
                href={imageUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-2 inline-flex items-center gap-1.5 text-label text-(--color-accent-primary) hover:underline rounded-[2px]"
              >
                <ExternalLink size={13} aria-hidden="true" />
                Open full-size image
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Available: review clip ──
  const clip = media.clip;
  if (!clip) {
    return (
      <div className={className}>
        <StatePanel
          role="alert"
          icon={<TriangleAlert size={20} aria-hidden="true" />}
          tone="error"
          title="Clip details missing"
          description="The server reported the clip as available but did not include it."
          action={
            <Button variant="secondary" size="sm" onClick={reload}>
              <RotateCw size={14} aria-hidden="true" />
              Try again
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className={className}>
      {recovery === 'failed' ? (
        <MediaFailedPanel noun="clip" onReload={manualMediaReload} />
      ) : (
        <ConcealableFrame concealed={concealed} refreshing={recovery === 'refreshing'} refreshingLabel="Refreshing the clip link...">
          <video
            key={mediaVersion}
            ref={videoRef}
            src={clip.url}
            controls
            preload="metadata"
            playsInline
            aria-label={`Evidence clip${subject}`}
            aria-describedby={captionId}
            onError={handleMediaError}
            onLoadedMetadata={handleLoadedMetadata}
            className="w-full h-full object-contain bg-(--color-bg-surface-raised)"
          >
            Your browser cannot play this video.
          </video>
        </ConcealableFrame>
      )}
      <div id={captionId} className="px-4 py-3 border-t border-(--color-border-default) text-body-sm">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
          <p className="flex items-center gap-1.5 font-medium text-(--color-text-primary)">
            <Film size={14} aria-hidden="true" />
            Review clip
          </p>
          <dl className="flex flex-wrap gap-x-6 gap-y-1">
            <div className="flex gap-1.5">
              <dt className="text-(--color-text-muted)">Length</dt>
              <dd className="text-(--color-text-primary) tabular-nums">{formatDuration(clip.durationSeconds)}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-(--color-text-muted)">File size</dt>
              <dd className="text-(--color-text-primary) tabular-nums">{formatFileSize(clip.sizeBytes)}</dd>
            </div>
          </dl>
        </div>
        <p className="text-(--color-text-muted) mt-1">
          The clip is kept only while the case is under review. Once the review is finalised it is replaced by a still record image.
        </p>
      </div>
    </div>
  );
}

// ── Presentational pieces ──────────────────

const toneClasses = {
  error: 'bg-(--color-error-subtle) text-(--color-error)',
  warning: 'bg-(--color-warning-subtle) text-(--color-warning)',
  neutral: 'bg-(--color-bg-surface) text-(--color-text-muted)',
} as const;

function StatePanel({
  icon,
  tone,
  title,
  description,
  action,
  role,
}: {
  icon: ReactNode;
  tone: keyof typeof toneClasses;
  title: string;
  description: string;
  action?: ReactNode;
  role?: 'alert' | 'status';
}) {
  return (
    <div
      role={role}
      className="aspect-video bg-(--color-bg-surface-raised) flex flex-col items-center justify-center gap-2 px-6 py-6 text-center"
    >
      <div className={`w-10 h-10 rounded-full flex items-center justify-center ${toneClasses[tone]}`}>{icon}</div>
      <p className="text-body font-medium text-(--color-text-primary)">{title}</p>
      <p className="text-body-sm text-(--color-text-muted) max-w-sm">{description}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

function MediaFailedPanel({ noun, onReload }: { noun: 'clip' | 'record image'; onReload: () => void }) {
  return (
    <StatePanel
      role="alert"
      icon={<TriangleAlert size={20} aria-hidden="true" />}
      tone="error"
      title={`The ${noun} could not be played`}
      description={`The link to the ${noun} may have expired, or the connection dropped. Reloading requests a fresh link.`}
      action={
        <Button variant="secondary" size="sm" onClick={onReload}>
          <RotateCw size={14} aria-hidden="true" />
          {noun === 'clip' ? 'Reload clip' : 'Reload image'}
        </Button>
      }
    />
  );
}

function ConcealableFrame({
  concealed,
  refreshing,
  refreshingLabel,
  children,
}: {
  concealed: boolean;
  refreshing: boolean;
  refreshingLabel: string;
  children: ReactNode;
}) {
  return (
    <div className="relative aspect-video bg-(--color-bg-surface-raised) overflow-hidden">
      <div
        inert={concealed || refreshing}
        className={`w-full h-full transition-[filter] duration-300 motion-reduce:transition-none ${concealed ? 'blur-lg' : ''}`}
      >
        {children}
      </div>
      {concealed && (
        <div className="absolute inset-0 flex items-center justify-center p-4">
          <p className="text-body-sm text-(--color-text-secondary) bg-(--color-bg-surface)/90 px-4 py-2 rounded-[6px] text-center">
            Evidence is blurred for privacy. Use the reveal control above to view it.
          </p>
        </div>
      )}
      {refreshing && !concealed && (
        <div role="status" className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-(--color-bg-surface)/80">
          <div className="h-6 w-6 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" aria-hidden="true" />
          <p className="text-body-sm text-(--color-text-secondary)">{refreshingLabel}</p>
        </div>
      )}
    </div>
  );
}
