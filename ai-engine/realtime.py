"""Latest-frame AI worker plus fast, appearance-checked optical-flow tracking.

Camera/UI work never waits for neural inference. Delayed detections are moved
through a short frame history before appearing on the current camera image.
Tracks require current image evidence and expire without semantic refresh.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from phone_detector import BOOK, DetectionEvent, PHONE, overlap


def gray_frame(frame, max_size=640):
    h, w = frame.shape[:2]
    ratio = min(1, max_size / max(h, w))
    small = cv2.resize(frame, (round(w * ratio), round(h * ratio))) if ratio < 1 else frame
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def patch(gray, box, size=(40, 56)):
    h, w = gray.shape
    x1, y1, x2, y2 = box
    x1, y1 = max(0, round(x1)), max(0, round(y1))
    x2, y2 = min(w, round(x2)), min(h, round(y2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    crop = gray[y1:y2, x1:x2]
    return (cv2.resize(crop, size) if size else crop).astype(np.float32)


def corners(gray, box):
    mask = np.zeros_like(gray)
    h, w = gray.shape
    x1, y1, x2, y2 = map(round, box)
    mask[max(0, y1 + 1):min(h, y2 - 1), max(0, x1 + 1):min(w, x2 - 1)] = 255
    return cv2.goodFeaturesToTrack(gray, maxCorners=60, qualityLevel=0.01,
                                  minDistance=3, mask=mask, blockSize=3)


@dataclass
class VisualTrack:
    event: DetectionEvent
    box: tuple
    points: np.ndarray
    template: np.ndarray
    verified_at: float
    semantic_hits: int = 0
    reference: np.ndarray | None = None

    @classmethod
    def create(cls, event, source, source_shape, timestamp):
        gh, gw = source.shape
        h, w = source_shape[:2]
        box = tuple(v * (gw / w if k % 2 == 0 else gh / h) for k, v in enumerate(event.box))
        points, template = corners(source, box), patch(source, box)
        if points is None or len(points) < 4 or template is None:
            return None
        return cls(event, box, points, template, timestamp, reference=patch(source, box, None))

    def advance(self, previous, current):
        if self._advance_flow(previous, current):
            return True
        return self._reacquire(current) or self._reacquire_features(previous, current)

    def _reacquire_features(self, source, current):
        # Rotation/scale changes invalidate a rigid template. Match local
        # descriptors inside the recognised object to the current image and
        # require a consistent geometric transform before accepting a box.
        orb = cv2.ORB_create(nfeatures=1800, edgeThreshold=5, patchSize=15, fastThreshold=5)
        mask = np.zeros_like(source)
        h, w = source.shape
        x1, y1, x2, y2 = map(round, self.box)
        mask[max(0,y1):min(h,y2),max(0,x1):min(w,x2)] = 255
        before, old_descriptors = orb.detectAndCompute(source, mask)
        after, new_descriptors = orb.detectAndCompute(current, None)
        if old_descriptors is None or new_descriptors is None or len(after) < 2:
            return False
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(old_descriptors, new_descriptors, k=2)
        matches = [pair[0] for pair in pairs if len(pair)==2 and
                   pair[0].distance < .75*pair[1].distance and pair[0].distance < 55]
        if len(matches) < 6:
            return False
        old = np.float32([before[m.queryIdx].pt for m in matches])
        new = np.float32([after[m.trainIdx].pt for m in matches])
        transform, inliers = cv2.estimateAffinePartial2D(old,new,method=cv2.RANSAC,ransacReprojThreshold=3)
        if transform is None or inliers is None or inliers.sum() < 6 or inliers.mean() < .35:
            return False
        scale = math.hypot(transform[0,0],transform[1,0])
        if not np.isfinite(transform).all() or not .5 < scale < 2:
            return False
        support = old[inliers.ravel()>0]
        if np.ptp(support[:,0]) < (x2-x1)*.15 or np.ptp(support[:,1]) < (y2-y1)*.1:
            return False
        bounds = np.float32([[x1,y1],[x2,y1],[x2,y2],[x1,y2]])
        moved = cv2.transform(bounds[None],transform)[0]
        box = (*moved.min(axis=0),*moved.max(axis=0))
        points, template = corners(current,box), patch(current,box)
        if points is None or len(points)<4 or template is None or template.std()<3:
            return False
        self.box, self.points, self.template = tuple(map(float,box)), points, template
        self.reference = patch(current,box,None)
        return True

    def _reacquire(self, current):
        # Abrupt movement can exceed optical flow's search window. Require a
        # strong appearance match in today's frame; never keep an old box just
        # because the AI previously recognised it.
        if self.reference is None or self.reference.std() < 3:
            return False
        best = None
        for scale in (.8, 1., 1.2):
            h, w = self.reference.shape
            template = cv2.resize(self.reference, (max(4, round(w*scale)), max(4, round(h*scale))))
            th, tw = template.shape
            if th >= current.shape[0] or tw >= current.shape[1]:
                continue
            values = cv2.matchTemplate(current.astype(np.float32), template, cv2.TM_CCOEFF_NORMED)
            _, quality, _, location = cv2.minMaxLoc(values)
            if best is None or quality > best[0]:
                best = quality, location, tw, th
        if best is None or not math.isfinite(best[0]) or best[0] < .75:
            return False
        _, (x, y), w, h = best
        box = (x, y, x+w, y+h)
        points = corners(current, box)
        if points is None or len(points) < 4:
            return False
        self.box, self.points = box, points
        return True

    def _advance_flow(self, previous, current):
        forward, status, _ = cv2.calcOpticalFlowPyrLK(
            previous, current, self.points, None, winSize=(21, 21), maxLevel=3)
        if forward is None:
            return False
        backward, back_status, _ = cv2.calcOpticalFlowPyrLK(
            current, previous, forward, None, winSize=(21, 21), maxLevel=3)
        if backward is None:
            return False
        error = np.linalg.norm(self.points.reshape(-1, 2) - backward.reshape(-1, 2), axis=1)
        valid = (status.ravel() > 0) & (back_status.ravel() > 0) & (error < 1.5)
        if valid.sum() < 4 or valid.mean() < 0.45:
            return False
        old, new = self.points[valid], forward[valid]
        transform, inliers = cv2.estimateAffinePartial2D(
            old, new, method=cv2.RANSAC, ransacReprojThreshold=2, maxIters=100)
        if transform is None or inliers.sum() < 4 or inliers.mean() < 0.55:
            return False
        scale = math.hypot(transform[0, 0], transform[1, 0])
        if not 0.65 < scale < 1.5 or not np.isfinite(transform).all():
            return False
        x1, y1, x2, y2 = self.box
        bounds = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], np.float32)
        moved = cv2.transform(bounds[None], transform)[0]
        box = (*moved.min(axis=0), *moved.max(axis=0))
        candidate = patch(current, box)
        if candidate is None or candidate.std() < 3 or self.template.std() < 3:
            return False
        similarity = float(np.corrcoef(self.template.ravel(), candidate.ravel())[0, 1])
        if not math.isfinite(similarity) or similarity < 0.25:
            return False
        self.box, self.points = tuple(map(float, box)), new[inliers.ravel() > 0]
        if len(self.points) < 12:
            self.points = corners(current, self.box)
            if self.points is None or len(self.points) < 4:
                return False
        return True


@dataclass(frozen=True)
class InferenceSnapshot:
    captured_at: float
    source: np.ndarray
    source_shape: tuple
    events: tuple
    inference_seconds: float
    candidates: tuple = ()


class RealtimeEngine:
    def __init__(self, detector_factory, *, history_seconds=8, track_ttl=8, min_semantic_hits=2,
                 max_result_age=30):
        cv2.setNumThreads(1)  # leave CPU capacity for the AI worker
        self._factory = detector_factory
        self._history_seconds, self._track_ttl = history_seconds, track_ttl
        self._min_semantic_hits = min_semantic_hits
        self._max_result_age = max_result_age
        self.thresholds = {PHONE: .5, BOOK: .6}
        self._condition = threading.Condition()
        self._pending = self._result = None
        self._stopped = False
        self._ready = threading.Event()
        self.error = None
        self._history = deque()
        self._tracks = []
        self._previous = None
        self._previous_shape = None
        self._last_result_time = -float('inf')
        self._next_id = 1
        self.last_events = []
        self.last_inference_seconds = 0.0
        self.last_semantic_at = None
        self.last_ai_events = ()
        self.last_ai_candidates = ()
        self.completed_checks = 0
        self.last_completed_at = None
        self.last_result_age = 0.
        self.rejected_alignment = 0
        self.rejected_age = 0
        self._thread = threading.Thread(target=self._worker, name='proctorai-detection', daemon=True)
        self._thread.start()

    @property
    def ready(self):
        return self._ready.is_set() and self.error is None

    def wait_ready(self, timeout=30):
        return self._ready.wait(timeout) and self.error is None

    @property
    def checking_labels(self):
        return sorted({t.event.label for t in self._tracks if t.semantic_hits < self._min_semantic_hits})

    def _worker(self):
        try:
            detector = self._factory()
            self.thresholds = getattr(detector, 'thresholds', self.thresholds)
            self._ready.set()
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._stopped or self._pending is not None)
                    if self._stopped:
                        return
                    frame, timestamp = self._pending
                    self._pending = None
                source = gray_frame(frame)
                events = tuple(detector.process_frame(frame, timestamp=timestamp))
                snapshot = InferenceSnapshot(timestamp, source, frame.shape, events,
                                             detector.last_inference_seconds, tuple(getattr(detector, 'last_detections', ())))
                with self._condition:
                    self._result = snapshot  # one result slot, never a backlog
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            self._ready.set()

    def _accept(self, result, current, shape, timestamp):
        self.last_inference_seconds = result.inference_seconds
        self.last_ai_events, self.last_ai_candidates = result.events, result.candidates
        self.completed_checks += 1
        self.last_completed_at = timestamp
        self.last_result_age = timestamp-result.captured_at
        self.rejected_alignment = 0
        if result.source_shape != shape or result.captured_at <= self._last_result_time:
            return
        self._last_result_time = result.captured_at
        self.last_semantic_at = result.captured_at
        if timestamp - result.captured_at > self._max_result_age:
            self.rejected_age += 1
            return
        # Move old AI coordinates to today's camera frame. Never draw an old
        # box directly on a newer image, or resurrect an object that vanished.
        steps = ([(t, image) for t, image in self._history if result.captured_at < t < timestamp]
                 if timestamp-result.captured_at <= self._history_seconds else [])
        steps.append((timestamp, current))
        for event in result.events:
            track = VisualTrack.create(event, result.source, result.source_shape, result.captured_at)
            if track is None:
                self.rejected_alignment += 1
                continue
            previous = result.source
            for _, image in steps:
                if not track.advance(previous, image):
                    track = None
                    break
                previous = image
            if track is None:
                # A blurred intermediate frame must not veto a visible object
                # now. Reconcile source directly against current image evidence.
                track = VisualTrack.create(event, result.source, result.source_shape, result.captured_at)
                if track is None or not track.advance(result.source, current):
                    self.rejected_alignment += 1
                    continue
            # A slow model does not consume the entire visibility lifetime:
            # this box has just been verified against the current image.
            track.verified_at = timestamp
            matches = [(max(overlap(track.box, other.box),
                            .3 if overlap(track.box, other.box, smaller=True) >= .85 else 0), other)
                       for other in self._tracks
                       if other.event.type == event.type]
            quality, match = max(matches, key=lambda pair: pair[0], default=(0, None))
            if quality >= 0.3:
                visual_id = match.event.track_id
                track.semantic_hits = match.semantic_hits
                self._tracks.remove(match)
            else:
                visual_id = self._next_id
                self._next_id += 1
            track.semantic_hits = max(track.semantic_hits +
                int(event.confidence >= self.thresholds.get(event.type, 1)), event.semantic_hits)
            track.event = DetectionEvent(event.type, event.confidence, event.timestamp,
                                         event.box, event.label, visual_id)
            self._tracks.append(track)

    def update(self, frame, timestamp=None):
        timestamp = time.monotonic() if timestamp is None else timestamp
        current = gray_frame(frame)
        if self._previous_shape != frame.shape:
            self._tracks.clear()
            self._history.clear()
            self._previous = None
        if self._previous is not None:
            self._tracks = [track for track in self._tracks
                            if timestamp - track.verified_at <= self._track_ttl and
                            track.advance(self._previous, current)]
        with self._condition:
            result, self._result = self._result, None
            # Replace pending work with the latest frame; do not queue 30 fps
            # behind a slower neural model.
            self._pending = (frame.copy(), timestamp)
            self._condition.notify()
        if result is not None:
            self._accept(result, current, frame.shape, timestamp)
        self._previous, self._previous_shape = current, frame.shape
        if not self._history or timestamp - self._history[-1][0] >= 0.12:
            self._history.append((timestamp, current))
        while self._history and timestamp - self._history[0][0] > self._history_seconds:
            self._history.popleft()
        gh, gw = current.shape
        h, w = frame.shape[:2]
        self.last_events = [DetectionEvent(track.event.type, track.event.confidence, time.time(),
                            tuple(v * (w / gw if k % 2 == 0 else h / gh)
                                  for k, v in enumerate(track.box)), track.event.label, track.event.track_id)
                            for track in self._tracks if timestamp - track.verified_at <= self._track_ttl
                            and track.semantic_hits >= self._min_semantic_hits]
        return self.last_events

    def annotate_frame(self, frame):
        annotated = frame.copy()
        h, w = frame.shape[:2]
        gh, gw = self._previous.shape if self._previous is not None else (h, w)
        for track in self._tracks:
            event = track.event
            x1, y1, x2, y2 = [round(v * (w/gw if k % 2 == 0 else h/gh)) for k,v in enumerate(track.box)]
            confirmed = track.semantic_hits >= self._min_semantic_hits
            color = (0, 0, 255) if event.type == PHONE else (0, 165, 255)
            if not confirmed:
                color = (200, 200, 200)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = f'{event.label} #{event.track_id}' if confirmed else f'Checking {event.label}'
            cv2.putText(annotated, label, (x1, max(20, y1-7)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        return annotated

    def close(self):
        with self._condition:
            self._stopped = True
            self._pending = None
            self._condition.notify()
        self._thread.join(timeout=30)


def run_preview(source, factory):
    from camera import open_camera
    cap = open_camera(source)
    engine = RealtimeEngine(factory)
    frames, fps, started = 0, 0.0, time.monotonic()
    reported_ready = reported_check = False
    title = 'ProctorAI real-time phones and books - q to quit'
    print('Live preview starting; AI loads in the background. Press q to quit.', flush=True)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            engine.update(frame)
            if engine.error:
                raise RuntimeError(engine.error)
            if engine.ready and not reported_ready:
                print('Object AI ready; camera and tracking continue during recognition.', flush=True)
                reported_ready = True
            if engine.last_semantic_at is not None and not reported_check:
                print(f'First AI check: {engine.last_inference_seconds:.2f}s; live preview remains independent.', flush=True)
                reported_check = True
            annotated = engine.annotate_frame(frame)
            frames += 1
            elapsed = time.monotonic() - started
            if elapsed >= 1:
                fps, frames, started = frames / elapsed, 0, time.monotonic()
            status = f'Live: {fps:.0f} fps | AI check: {engine.last_inference_seconds:.2f}s' if engine.ready else 'Live camera | Loading AI...'
            cv2.putText(annotated, status, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 0), 2)
            cv2.imshow(title, annotated)
            if cv2.waitKey(1) & 0xFF == ord('q') or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        engine.close()
