"""
composite_scorer.py — combines individual signal events (phone, head
pose, etc.) into a single composite suspicion score using a rolling
buffer, to smooth out single-frame noise before firing a real alert.

Logic:
- Each signal type has its own rolling buffer of the last BUFFER_SIZE
  frames' worth of "was this signal active in this frame" booleans.
- A signal counts as "active" for scoring purposes if it was present in
  more than ACTIVE_RATIO of the buffer (e.g. >60% of the last 18 frames).
- The composite score is the MAX weight among currently-active signals
  (not a sum) — this matches the project spec's "weighted-max" design.
- An alert fires when the composite score crosses ALERT_THRESHOLD.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


# --------------------------------------------------------------------------
# Tunable constants
# --------------------------------------------------------------------------

BUFFER_SIZE = 18          # ~3 seconds at 6 fps effective sampling rate
ACTIVE_RATIO = 0.60       # signal must be present in >60% of buffer frames
ALERT_THRESHOLD = 0.75    # composite score must reach this to fire an alert

SIGNAL_WEIGHTS = {
    "PHONE_DETECTED": 0.90,
    "CELL_PHONE": 0.90,       # alias, in case a detector emits this type name
    "HEAD_POSE_VIOLATION": 0.65,
    "UNAUTHORISED_OBJECT": 0.75,
    # Add more signal types + weights here as more detectors come online,
    # e.g. "GAZE_DEVIATION": 0.70, "LIP_MOVEMENT": 0.60
}


@dataclass
class CompositeAlert:
    score: float
    active_signals: list[str]
    timestamp: float


class CompositeScorer:
    def __init__(
        self,
        buffer_size: int = BUFFER_SIZE,
        active_ratio: float = ACTIVE_RATIO,
        alert_threshold: float = ALERT_THRESHOLD,
        signal_weights: dict[str, float] | None = None,
        window_seconds: float | None = None,
    ):
        self.buffer_size = buffer_size
        self.active_ratio = active_ratio
        self.alert_threshold = alert_threshold
        self.signal_weights = signal_weights or dict(SIGNAL_WEIGHTS)
        if window_seconds is not None and window_seconds <= 0:
            raise ValueError('window_seconds must be positive')
        self.window_seconds = window_seconds
        self._history = deque()
        self._started_at = None

        # One rolling buffer per known signal type. Each buffer holds
        # True/False for "was this signal reported as present this frame".
        self._buffers: dict[str, deque[bool]] = {
            signal_type: deque(maxlen=self.buffer_size)
            for signal_type in self.signal_weights
        }

    def _ensure_buffer(self, signal_type: str) -> deque[bool]:
        """Lazily creates a buffer for a signal type not in the initial
        weights dict, so unexpected signal types don't crash — they just
        won't have a weight and will be ignored for scoring."""
        if signal_type not in self._buffers:
            self._buffers[signal_type] = deque(maxlen=self.buffer_size)
        return self._buffers[signal_type]

    def update(self, present_signal_types: set[str], timestamp: float) -> CompositeAlert | None:
        """
        Call this once per processed frame.

        present_signal_types: the set of signal type strings that fired
            in THIS frame (e.g. {"PHONE_DETECTED"} or {} if nothing fired).
        timestamp: the current time (e.g. time.time()).

        Returns a CompositeAlert if the composite score crosses
        alert_threshold this frame, else None.
        """
        if self.window_seconds is not None:
            return self._update_timed(present_signal_types, timestamp)
        # Update every known buffer, including ones not present this frame
        # (they get a False appended, which is what lets a lingering
        # signal "expire" out of the buffer over time).
        all_signal_types = set(self._buffers.keys()) | present_signal_types
        for signal_type in all_signal_types:
            buf = self._ensure_buffer(signal_type)
            buf.append(signal_type in present_signal_types)

        active_signals = []
        for signal_type, buf in self._buffers.items():
            # Require the buffer to actually be full before a signal can
            # count as "active" — otherwise a single True frame trivially
            # satisfies ">60% of history" (1/1 = 100%) on frame one, which
            # defeats the entire point of temporal smoothing.
            if len(buf) < self.buffer_size:
                continue
            active_fraction = sum(buf) / len(buf)
            if active_fraction > self.active_ratio:
                active_signals.append(signal_type)

        if not active_signals:
            return None

        composite_score = max(
            self.signal_weights.get(signal_type, 0.0)
            for signal_type in active_signals
        )

        if composite_score >= self.alert_threshold:
            return CompositeAlert(
                score=composite_score,
                active_signals=active_signals,
                timestamp=timestamp,
            )

        return None

    def _update_timed(self, present, timestamp):
        """Real observations covering a time window; never invent 6-fps samples.

        This keeps CPU inference from turning the intended 3-second smoothing
        window into 18 slow inferences. Require two observations, full warmup,
        and current evidence. Long gaps or a clock reset restart the warmup.
        """
        if self._history and (timestamp < self._history[-1][0] or
                              timestamp - self._history[-1][0] > self.window_seconds * 2):
            self.reset()
        if self._started_at is None:
            self._started_at = timestamp
        self._history.append((timestamp, set(present)))
        # Keep the observation preceding the window boundary. At <1 fps,
        # dropping it would leave just one observation and suppress every
        # alert even for a continuously present, confirmed object.
        while len(self._history) > 2 and self._history[1][0] <= timestamp - self.window_seconds:
            self._history.popleft()
        if timestamp - self._started_at < self.window_seconds or len(self._history) < 2:
            return None
        active = sorted(signal for signal in present if signal in self.signal_weights and
                        sum(signal in signals for _, signals in self._history) / len(self._history) > self.active_ratio)
        score = max((self.signal_weights[signal] for signal in active), default=0.0)
        return CompositeAlert(score, active, timestamp) if score >= self.alert_threshold else None

    def reset(self) -> None:
        """Clears all buffers — useful between test cases or sessions."""
        for buf in self._buffers.values():
            buf.clear()
        self._history.clear()
        self._started_at = None
