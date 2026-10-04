"""
test_composite_scorer.py — unit tests for composite_scorer.py using
synthetic (fake) signal sequences. No camera or model required.

Run: pytest test_composite_scorer.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from composite_scorer import CompositeScorer


def test_time_window_smooths_real_cpu_samples_without_waiting_18_frames():
    scorer = CompositeScorer(window_seconds=3)
    assert scorer.update(set(), 0) is None
    assert scorer.update({'UNAUTHORISED_OBJECT'}, 2.5) is None
    assert scorer.update({'UNAUTHORISED_OBJECT'}, 5).score == 0.75
    assert scorer.update(set(), 7.5) is None


def test_time_window_single_flicker_and_long_gap_do_not_alert():
    scorer = CompositeScorer(window_seconds=3)
    assert scorer.update(set(), 0) is None
    assert scorer.update(set(), 2.5) is None
    assert scorer.update({'PHONE_DETECTED'}, 5) is None
    assert scorer.update({'PHONE_DETECTED'}, 30) is None


def test_time_window_requires_warmup_after_reset_or_clock_reversal():
    scorer = CompositeScorer(window_seconds=3)
    scorer.update({'PHONE_DETECTED'}, 0)
    scorer.update({'PHONE_DETECTED'}, 2.5)
    assert scorer.update({'PHONE_DETECTED'}, 5)
    scorer.reset()
    assert scorer.update({'PHONE_DETECTED'}, 6) is None
    assert scorer.update({'PHONE_DETECTED'}, 0) is None


def test_time_window_can_alert_when_refinement_takes_longer_than_window():
    scorer = CompositeScorer(window_seconds=3)
    assert scorer.update(set(), 0) is None
    assert scorer.update({'UNAUTHORISED_OBJECT'}, 4.4) is None
    assert scorer.update({'UNAUTHORISED_OBJECT'}, 8.8).score == .75
    assert scorer.update(set(), 13.2) is None


def test_single_signal_below_threshold_never_fires():
    """HEAD_POSE_VIOLATION alone has weight 0.65, below the 0.75 default
    threshold, so it should never fire an alert even if sustained the
    entire buffer."""
    scorer = CompositeScorer()
    alert = None
    for i in range(30):
        alert = scorer.update({"HEAD_POSE_VIOLATION"}, timestamp=float(i))
    assert alert is None


def test_single_signal_above_threshold_fires_once_buffer_fills():
    """PHONE_DETECTED alone has weight 0.90, above threshold, so it
    should fire once it's been present in >60% of the buffer."""
    scorer = CompositeScorer()
    fired = False
    for i in range(30):
        alert = scorer.update({"PHONE_DETECTED"}, timestamp=float(i))
        if alert is not None:
            fired = True
            assert alert.score == 0.90
            assert "PHONE_DETECTED" in alert.active_signals
    assert fired, "Expected PHONE_DETECTED to eventually cross the alert threshold"


def test_signal_does_not_fire_before_buffer_has_enough_active_frames():
    """With buffer_size=18 and active_ratio=0.60, we need >60% of 18
    frames (i.e. at least 11 True frames) before a signal counts as
    active. Confirm it does NOT fire on frame 1."""
    scorer = CompositeScorer()
    alert = scorer.update({"PHONE_DETECTED"}, timestamp=0.0)
    assert alert is None, "Should not fire on the very first frame"


def test_combined_signals_use_max_not_sum():
    """If both PHONE_DETECTED (0.90) and HEAD_POSE_VIOLATION (0.65) are
    simultaneously active, the composite score should be the MAX of the
    two (0.90), not their sum (1.55) or average."""
    scorer = CompositeScorer()
    alert = None
    for i in range(30):
        alert = scorer.update(
            {"PHONE_DETECTED", "HEAD_POSE_VIOLATION"}, timestamp=float(i)
        )
    assert alert is not None
    assert alert.score == 0.90, "Composite score should be max(0.90, 0.65), not a sum"
    assert set(alert.active_signals) == {"PHONE_DETECTED", "HEAD_POSE_VIOLATION"}


def test_single_frame_flicker_is_smoothed_out():
    """A signal present for only 1 out of 18 frames should NOT count as
    active (far below the 60% ratio) — this proves the smoothing
    actually suppresses single-frame noise/flicker."""
    scorer = CompositeScorer()
    alert = None
    for i in range(18):
        # Only frame index 0 has the signal present; rest are empty.
        signals = {"PHONE_DETECTED"} if i == 0 else set()
        alert = scorer.update(signals, timestamp=float(i))
    assert alert is None, "A single-frame flicker should be smoothed out, not fire an alert"


def test_signal_expires_out_of_buffer_over_time():
    """If a signal was active long enough to fire, then stops entirely,
    it should eventually drop back below the active ratio as stale
    True frames age out of the rolling buffer, and stop firing."""
    scorer = CompositeScorer()

    # Fill buffer with PHONE_DETECTED present every frame — should fire.
    fired_initially = False
    for i in range(20):
        alert = scorer.update({"PHONE_DETECTED"}, timestamp=float(i))
        if alert is not None:
            fired_initially = True
    assert fired_initially

    # Now stop reporting it entirely for enough frames to age out the
    # buffer (buffer_size=18, so 18 empty frames fully flushes it).
    alert_after_stopping = None
    for i in range(20, 20 + 18):
        alert_after_stopping = scorer.update(set(), timestamp=float(i))

    assert alert_after_stopping is None, (
        "Signal should stop being 'active' once it has aged out of the "
        "rolling buffer after no longer being reported"
    )


def test_unknown_signal_type_does_not_crash_and_is_ignored():
    """A signal type not in SIGNAL_WEIGHTS should not crash the scorer,
    and should never contribute to the composite score (treated as
    weight 0)."""
    scorer = CompositeScorer()
    alert = None
    for i in range(30):
        alert = scorer.update({"SOME_UNKNOWN_SIGNAL"}, timestamp=float(i))
    assert alert is None


def test_custom_weights_and_threshold_are_respected():
    """Confirm the scorer isn't hardcoded to the module-level defaults —
    passing custom weights/threshold should change behavior."""
    scorer = CompositeScorer(
        signal_weights={"LOW_SIGNAL": 0.50},
        alert_threshold=0.40,
    )
    alert = None
    for i in range(30):
        alert = scorer.update({"LOW_SIGNAL"}, timestamp=float(i))
    assert alert is not None, "0.50 weight should clear a lowered 0.40 threshold"
    assert alert.score == 0.50


def test_reset_clears_buffers():
    scorer = CompositeScorer()
    for i in range(30):
        scorer.update({"PHONE_DETECTED"}, timestamp=float(i))

    scorer.reset()

    # Immediately after reset, a single frame should behave like a fresh
    # scorer — i.e. not fire yet.
    alert = scorer.update({"PHONE_DETECTED"}, timestamp=100.0)
    assert alert is None, "reset() should clear prior buffer history"
