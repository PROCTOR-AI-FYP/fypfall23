"""Local camera bridge: one camera, latest-frame AI, JPEG feed and real alerts.

This belongs to the local SQLite demo (backend.main), not the hosted platform.
No GUI window or browser-to-cloud camera upload is involved.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path


def camera_factory():
    _add_engine_path()
    from camera import open_camera
    return open_camera(0)


def _add_engine_path():
    path = str(Path(__file__).resolve().parent.parent / 'ai-engine')
    if path not in sys.path:
        sys.path.insert(0, path)


def runtime_factory():
    _add_engine_path()
    from phone_detector import PhoneDetector
    from realtime import RealtimeEngine
    return RealtimeEngine(lambda: PhoneDetector(full_imgsz=640, min_hits=1))


class ObjectMonitor:
    def __init__(self, alert_sink, *, runtime=None, camera=None, scorer=None):
        self._sink = alert_sink
        self._runtime_factory = runtime or runtime_factory
        self._camera_factory = camera or camera_factory
        self._scorer_factory = scorer
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._jpeg = None
        self._sequence = 0
        self._generation = 0
        self._state = self._initial_state()

    @staticmethod
    def _initial_state():
        return dict(phase='stopped', session_id=None, fps=0., ai_seconds=0.,
                    objects=[], checking=[], error=None, alert_error=None,
                    last_alert=None, resolution=None, detector=None)

    def status(self):
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            return {**self._state, 'running': alive and not self._stop.is_set(),
                    'run_id': self._generation}

    def start(self, session_id, loop):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError('The camera is already running or still stopping.')
            self._generation += 1
            self._state = {**self._initial_state(), 'phase': 'loading', 'session_id': session_id}
            self._jpeg = None
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._capture, args=(session_id, loop),
                                            name='proctorai-web-camera', daemon=True)
            self._thread.start()
        return self.status()

    def stop(self, timeout=5):
        with self._lock:
            thread = self._thread
            if thread is not None and thread.is_alive():
                self._state['phase'] = 'stopping'
                self._stop.set()
            self._jpeg = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return self.status()

    def latest_frame(self):
        with self._lock:
            return self._sequence, self._jpeg

    def _publish(self, **values):
        with self._lock:
            self._state.update(values)

    def _capture(self, session_id, loop):
        import cv2
        cap = runtime = pending = None
        failed = False
        try:
            cap = self._camera_factory()
            runtime = self._runtime_factory()
            if self._scorer_factory:
                scorer = self._scorer_factory()
            else:
                _add_engine_path()
                from composite_scorer import CompositeScorer
                scorer = CompositeScorer(window_seconds=3)
            started = time.monotonic()
            frames = 0
            last_sample, last_sent, last_attempt = -float('inf'), {}, -float('inf')
            submitted = None
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError('Camera stopped delivering frames. Close other camera apps and restart monitoring.')
                now = time.monotonic()
                events = runtime.update(frame, now)
                if runtime.error:
                    raise RuntimeError(runtime.error)
                if pending is not None and pending.done():
                    try:
                        recorded = pending.result()
                        last_sent[submitted['type']] = now
                        self._publish(last_alert=recorded, alert_error=None)
                    except Exception:
                        self._publish(alert_error='Could not save the alert. Monitoring will retry.')
                    pending = None
                if now - last_sample >= 1/6:
                    last_sample = now
                    alert = scorer.update({e.type for e in events}, time.time())
                    if alert:
                        kind = '+'.join(sorted(alert.active_signals))
                        if (pending is None and now-last_sent.get(kind, -float('inf')) >= 20
                                and now-last_attempt >= 5):
                            submitted = dict(session_id=session_id, type=kind,
                                             confidence=alert.score, timestamp=alert.timestamp)
                            last_attempt = now
                            pending = asyncio.run_coroutine_threadsafe(self._sink(submitted), loop)
                annotated = runtime.annotate_frame(frame)
                height, width = frame.shape[:2]
                # AI sees the original camera resolution. Only transport is resized.
                if width > 960:
                    annotated = cv2.resize(annotated, (960, round(height*960/width)))
                encoded, jpeg = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not encoded:
                    raise RuntimeError('Could not encode the camera frame.')
                frames += 1
                elapsed = now-started
                values = dict(phase='ready' if runtime.ready else 'loading',
                              ai_seconds=runtime.last_inference_seconds,
                              resolution={'width': width, 'height': height},
                              objects=[dict(label=e.label, type=e.type, confidence=e.confidence,
                                            track_id=e.track_id) for e in events],
                              checking=runtime.checking_labels)
                if hasattr(runtime, 'completed_checks'):
                    values['detector'] = dict(
                        checks=runtime.completed_checks,
                        last_check_age=None if runtime.last_completed_at is None else now-runtime.last_completed_at,
                        result_age=runtime.last_result_age,
                        candidates=[dict(label=d.label, confidence=d.confidence) for d in runtime.last_ai_candidates],
                        recognised=[e.label for e in runtime.last_ai_events],
                        rejected_alignment=runtime.rejected_alignment,
                        rejected_age=runtime.rejected_age)
                if elapsed >= 1:
                    values['fps'] = frames/elapsed
                    frames, started = 0, now
                with self._lock:
                    if self._stop.is_set():
                        break
                    self._state.update(values)
                    self._sequence += 1
                    self._jpeg = jpeg.tobytes()
        except Exception as exc:
            failed = True
            self._stop.set()
            self._publish(phase='error', error=str(exc), objects=[], checking=[])
            with self._lock:
                self._jpeg = None
        finally:
            if cap is not None:
                cap.release()
            if runtime is not None:
                runtime.close()
            # An already-confirmed alert may finish saving, but a stopped camera
            # cannot retain current object indicators or a stale video frame.
            with self._lock:
                self._jpeg = None
                self._state.update(objects=[], checking=[], fps=0.)
                if not failed:
                    self._state['phase'] = 'stopped'
