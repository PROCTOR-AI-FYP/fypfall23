"""Measure current-frame processing separately from background AI latency.

Default: replay local positive images with controlled movement and removal.
--camera 0 measures real capture/display FPS; press q to stop a visible test.
"""
import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from camera import open_camera
from phone_detector import PhoneDetector
from realtime import RealtimeEngine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int)
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--show', action='store_true')
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'validation-output/realtime-benchmark.json')
    args = parser.parse_args()
    root = Path(__file__).parent / 'validation-output'
    base = cv2.imread(str(root / 'live-test/frame-45.jpg'))
    negative = cv2.imread(str(root / 'webcam-moderate.jpg'))
    if args.camera is None and (base is None or negative is None):
        raise ValueError('Replay requires the locally captured validation images; use --camera for live testing.')
    engine = RealtimeEngine(lambda: PhoneDetector(full_imgsz=args.imgsz, min_hits=1))
    print('Loading AI for benchmark...', flush=True)
    cap = None
    try:
        if not engine.wait_ready(60):
            raise RuntimeError(engine.error or 'AI did not finish loading')
        if args.camera is not None:
            cap = open_camera(args.camera)
        start = time.monotonic()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        next_snapshot = 0
        last_reported = None
        timings, samples, counts = [], [], []
        while time.monotonic() - start < args.seconds:
            elapsed = time.monotonic() - start
            if cap is not None:
                ok, frame = cap.read()
                if not ok:
                    break
            elif elapsed >= args.seconds - 1:
                frame = negative.copy()
            else:
                dx = round(30 * math.sin(elapsed * .6))
                dy = round(10 * math.sin(elapsed * .5))
                frame = cv2.warpAffine(base, np.float32([[1, 0, dx], [0, 1, dy]]),
                                       (base.shape[1], base.shape[0]))
            tick = time.perf_counter()
            events = engine.update(frame)
            display = engine.annotate_frame(frame)
            processing = time.perf_counter() - tick
            timings.append(processing)
            samples.append(dict(elapsed=elapsed, labels=[event.label for event in events],
                                boxes=[event.box for event in events], processing_ms=processing*1000,
                                ai_seconds=engine.last_inference_seconds,
                                ai_events=[(event.label,event.confidence) for event in engine.last_ai_events],
                                ai_candidates=[(event.label,event.confidence) for event in engine.last_ai_candidates]))
            counts.append(len(events))
            if elapsed >= next_snapshot:
                cv2.imwrite(str(args.output.parent / (args.output.stem + '-frame.jpg')), display)
                cv2.imwrite(str(args.output.parent / (args.output.stem + f'-raw-{round(elapsed):03d}.jpg')), frame)
                next_snapshot = elapsed + 3
            if engine.last_semantic_at is not None and engine.last_semantic_at != last_reported:
                last_reported = engine.last_semantic_at
                print(json.dumps(dict(elapsed=round(elapsed,1),
                    ai=[(event.label,round(event.confidence,3)) for event in engine.last_ai_events],
                    candidates=[(event.label,round(event.confidence,3)) for event in engine.last_ai_candidates],
                    visual=[(track.event.label,track.semantic_hits) for track in engine._tracks],
                    confirmed=[event.label for event in events])), flush=True)
            if engine.error:
                raise RuntimeError(engine.error)
            if args.show:
                cv2.putText(display, f'Live tracking {processing*1000:.1f}ms | AI {engine.last_inference_seconds:.2f}s',
                            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 0), 2)
                cv2.imshow('ProctorAI timed real-time test - q to exit', display)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            if cap is None:
                time.sleep(max(0, 1/30 - processing))
        duration = time.monotonic() - start
        both = [sample for sample in samples if set(sample['labels']) == {'phone', 'book'}]
        summary = dict(mode='live camera' if cap is not None else 'controlled image replay',
                       duration_seconds=duration, frames=len(samples), fps=len(samples)/duration,
                       median_processing_ms=float(np.median(timings))*1000,
                       p95_processing_ms=float(np.percentile(timings,95))*1000,
                       frames_with_both_objects=len(both),
                       first_both_seconds=both[0]['elapsed'] if both else None,
                       last_ai_seconds=engine.last_inference_seconds,
                       final_labels=samples[-1]['labels'] if samples else [])
        args.output.parent.mkdir(exist_ok=True, parents=True)
        args.output.write_text(json.dumps(dict(summary=summary,samples=samples),indent=2))
        print(json.dumps(summary,indent=2),flush=True)
    finally:
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()
        engine.close()


if __name__ == '__main__':
    main()
