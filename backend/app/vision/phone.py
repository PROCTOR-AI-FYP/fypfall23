"""Phone/book detection with full-frame context, focused verification and tracking.

Books emit UNAUTHORISED_OBJECT. process_frame analyses the frame once;
annotate_frame only draws cached results. Run prepare_models.py for offline use.
"""
from __future__ import annotations

import argparse
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2

PHONE = 'PHONE_DETECTED'
BOOK = 'UNAUTHORISED_OBJECT'
MODEL_DIR = Path(__file__).parent / 'models'
DEFAULT_MODEL = MODEL_DIR / 'grounding-dino-tiny'
CLASS_SIGNALS = {'cell phone': PHONE, 'phone': PHONE, 'mobile phone': PHONE,
                 'smartphone': PHONE, 'book': BOOK, 'books': BOOK,
                 'textbook': BOOK, 'novel': BOOK, 'paperback book': BOOK,
                 'hardcover book': BOOK, 'book cover': BOOK, 'open book': BOOK}


@dataclass(frozen=True)
class ObjectDetection:
    type: str
    confidence: float
    box: tuple[float, float, float, float]
    label: str


@dataclass(frozen=True)
class DetectionEvent:
    type: str
    confidence: float
    timestamp: float
    box: tuple[float, float, float, float]
    label: str
    track_id: int
    semantic_hits: int = 0


@dataclass
class _Track:
    id: int
    detection: ObjectDetection
    last_seen: float
    hits: deque = field(default_factory=lambda: deque(maxlen=5))
    confirmed: bool = False
    missed_frames: int = 0


def overlap(a, b, *, smaller=False):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    aa, ab = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    denominator = min(aa, ab) if smaller else aa + ab - intersection
    return intersection / denominator if denominator > 0 else 0.0


def tile_regions(width, height, tile_size=640, overlap_ratio=0.25):
    """Native-resolution crops, including both far edges without duplicate tiles."""
    def starts(length):
        size = min(tile_size, length)
        stride = max(1, round(size * (1 - overlap_ratio)))
        return sorted(set(range(0, max(1, length - size + 1), stride)) | {length - size})
    return [(x, y, min(x + tile_size, width), min(y + tile_size, height))
            for y in starts(height) for x in starts(width)]


def merge_detections(detections, iou_threshold=0.45):
    """Merge tile duplicates per signal, including contained crop-edge fragments."""
    kept = []
    for detection in sorted(detections, key=lambda item: -item.confidence):
        if not any(detection.type == other.type and
                   (overlap(detection.box, other.box) > iou_threshold or
                    overlap(detection.box, other.box, smaller=True) > 0.85) for other in kept):
            kept.append(detection)
    return kept


class PhoneDetector:
    def __init__(self, conf_threshold=0.50, *, book_threshold=0.60, candidate_threshold=0.15,
                 model_path=None, model=None, tile_size=640, overlap_ratio=0.25,
                 full_imgsz=640, batch_size=4, use_tiling=True, min_hits=2,
                 track_ttl=8.0, device='cpu'):
        if not 0 < candidate_threshold <= min(conf_threshold, book_threshold) <= 1:
            raise ValueError('Require 0 < candidate threshold <= phone/book thresholds <= 1.')
        if max(conf_threshold, book_threshold) > 1:
            raise ValueError('Confidence thresholds must be <= 1.')
        if tile_size < 64 or not 0 <= overlap_ratio < 0.75 or batch_size < 1 or full_imgsz < 64:
            raise ValueError('Invalid tile size, overlap, batch size or image size.')
        if not 1 <= min_hits <= 5 or track_ttl <= 0:
            raise ValueError('min_hits must be 1-5 and track_ttl positive.')
        if device == 'auto':
            import torch
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        if model is None:
            path = Path(model_path) if model_path else DEFAULT_MODEL
            if not path.exists():
                raise FileNotFoundError(f'Model missing: {path}. Run: python ai-engine/prepare_models.py')
            runtime = Path(__file__).parent / '.runtime'
            runtime.mkdir(exist_ok=True)
            os.environ.setdefault('YOLO_CONFIG_DIR', str(runtime))
            if path.is_dir():
                from .grounding import GroundingModel
                model = GroundingModel(path, device=device, book_threshold=book_threshold)
            else:
                from ultralytics import YOLO
                model = YOLO(str(path))
        self.model = model
        self.class_signals = {int(i): CLASS_SIGNALS[name.strip().lower().replace('_', ' ')]
                              for i, name in model.names.items()
                              if name.strip().lower().replace('_', ' ') in CLASS_SIGNALS}
        if set(self.class_signals.values()) != {PHONE, BOOK}:
            raise ValueError(f'The model must support phones AND books; classes: {model.names}')
        self.thresholds = {PHONE: conf_threshold, BOOK: book_threshold}
        self.candidate_threshold = candidate_threshold
        self.tile_size, self.overlap_ratio = tile_size, overlap_ratio
        self.full_imgsz, self.batch_size = full_imgsz, batch_size
        self.use_tiling, self.min_hits, self.track_ttl = use_tiling, min_hits, track_ttl
        self.device = device
        self._tracks = []
        self._next_id = 1
        self.last_detections = []
        self.last_events = []
        self.last_inference_seconds = 0.0
        self._last_timestamp = None

    def _predict(self, images, regions, imgsz, frame_shape):
        results = self.model.predict(images, conf=self.candidate_threshold,
                                     classes=list(self.class_signals), imgsz=imgsz,
                                     iou=0.45, verbose=False, device=self.device)
        if len(results) != len(regions):
            raise RuntimeError('The model returned an unexpected batch length.')
        detections = []
        height, width = frame_shape[:2]
        for result, (ox, oy, rx, ry) in zip(results, regions):
            if result.boxes is None:
                continue
            for box, cls, score in zip(result.boxes.xyxy.cpu().numpy(),
                                       result.boxes.cls.cpu().numpy(), result.boxes.conf.cpu().numpy()):
                signal = self.class_signals.get(int(cls))
                if signal is None or not math.isfinite(float(score)):
                    continue
                x1, y1, x2, y2 = map(float, box)
                if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
                    continue
                # YOLO boxes are in crop pixels already, not model-input pixels.
                bounds = (max(ox, min(rx, x1 + ox)), max(oy, min(ry, y1 + oy)),
                          min(width, rx, max(ox, x2 + ox)), min(height, ry, max(oy, y2 + oy)))
                if bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                    detections.append(ObjectDetection(signal, float(score), bounds,
                                                      'phone' if signal == PHONE else 'book'))
        return detections

    def detect(self, frame):
        """Raw merged candidates for evaluation; no temporal state is changed.

        Grounding DINO uses context plus a focused small-book check. Optional
        YOLO checkpoints use overlapping native-resolution slices instead.
        """
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
            raise ValueError('Expected a non-empty BGR camera frame.')
        h, w = frame.shape[:2]
        detections = self._predict([frame], [(0, 0, w, h)], self.full_imgsz, frame.shape)
        if self.use_tiling and getattr(self.model, 'supports_tiling', True) and max(h, w) > self.tile_size:
            regions = tile_regions(w, h, self.tile_size, self.overlap_ratio)
            for offset in range(0, len(regions), self.batch_size):
                batch = regions[offset:offset + self.batch_size]
                images = [frame[y1:y2, x1:x2] for x1, y1, x2, y2 in batch]
                detections.extend(self._predict(images, batch, self.tile_size, frame.shape))
        return merge_detections(detections)

    def process_frame(self, frame, timestamp=None):
        now = time.monotonic() if timestamp is None else timestamp
        if self._last_timestamp is not None and now < self._last_timestamp:
            self.reset()
        self._last_timestamp = now
        started = time.perf_counter()
        self.last_detections = self.detect(frame)
        self.last_inference_seconds = time.perf_counter() - started
        self._tracks = [track for track in self._tracks
                        if now - track.last_seen <= self.track_ttl and track.missed_frames < 3]
        unused = {track.id for track in self._tracks}
        events = []
        for detection in self.last_detections:
            matches = [(overlap(detection.box, track.detection.box), track) for track in self._tracks
                       if track.id in unused and track.detection.type == detection.type]
            similarity, track = max(matches, key=lambda item: item[0], default=(0, None))
            if similarity < 0.15:
                if detection.confidence < self.thresholds[detection.type]:
                    continue  # weak candidates may maintain a track, never start one
                track = _Track(self._next_id, detection, now)
                self._next_id += 1
                self._tracks.append(track)
            else:
                unused.remove(track.id)
            track.hits.append(detection.confidence >= self.thresholds[detection.type])
            track.confirmed = track.confirmed or sum(track.hits) >= self.min_hits
            track.detection, track.last_seen, track.missed_frames = detection, now, 0
            if track.confirmed:
                events.append(DetectionEvent(detection.type, detection.confidence,
                                             time.time(), detection.box, detection.label, track.id,
                                             sum(track.hits)))
        for track in self._tracks:
            if track.id in unused:
                track.missed_frames += 1
                track.hits.append(False)
        # Missing objects never produce events: stale boxes are not evidence.
        self.last_events = events
        return events

    def reset(self):
        self._tracks.clear()
        self.last_events, self.last_detections = [], []
        self._last_timestamp = None

    def annotate_frame(self, frame):
        annotated = frame.copy()
        for event in self.last_events:
            x1, y1, x2, y2 = map(round, event.box)
            color = (0, 0, 255) if event.type == PHONE else (0, 165, 255)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = f'{event.label} #{event.track_id} {event.confidence:.0%}'
            cv2.putText(annotated, label, (x1, max(18, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        return annotated


def main():
    from camera import open_camera
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='0', help='Camera index or video file')
    parser.add_argument('--model', type=Path)
    parser.add_argument('--phone-threshold', type=float, default=0.50)
    parser.add_argument('--book-threshold', type=float, default=0.60)
    parser.add_argument('--tile-size', type=int, default=640)
    parser.add_argument('--imgsz', type=int, default=640, help='AI input size; default 640 preserves accurate recognition')
    parser.add_argument('--device', default='cpu', help='cpu, cuda or auto')
    parser.add_argument('--sync', action='store_true', help='Original synchronous accuracy-check mode')
    args = parser.parse_args()
    image_size = args.imgsz
    def create_detector():
        return PhoneDetector(args.phone_threshold, book_threshold=args.book_threshold,
                             model_path=args.model, tile_size=args.tile_size,
                             full_imgsz=image_size, device=args.device, min_hits=2 if args.sync else 1)
    source = int(args.source) if args.source.isdigit() else args.source
    if not args.sync:
        from realtime import run_preview
        run_preview(source, create_detector)
        return
    detector = create_detector()
    cap = open_camera(source)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            detector.process_frame(frame)
            annotated = detector.annotate_frame(frame)
            cv2.putText(annotated, f'Inference: {detector.last_inference_seconds * 1000:.0f}ms', (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
            cv2.imshow('ProctorAI phones and books - q to quit', annotated)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
