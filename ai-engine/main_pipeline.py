"""Live camera tracking, background object AI and nonblocking demo alerts."""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import requests

from camera import open_camera
from composite_scorer import CompositeScorer
from head_pose_detector import HeadPoseDetector
from phone_detector import PhoneDetector
from realtime import RealtimeEngine

BACKEND_URL = 'http://localhost:8000/detection-event'
COOLDOWN_SECONDS = 5.0


def post_alert(payload):
    response = requests.post(BACKEND_URL, json=payload, timeout=0.5)
    response.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='0')
    parser.add_argument('--device', default='auto')
    parser.add_argument('--imgsz', type=int, default=640)
    args = parser.parse_args()
    source = int(args.source) if args.source.isdigit() else args.source
    head = HeadPoseDetector()
    cap = open_camera(source)
    objects = RealtimeEngine(lambda: PhoneDetector(device=args.device, full_imgsz=args.imgsz, min_hits=1))
    scorer = CompositeScorer(window_seconds=3)
    http = ThreadPoolExecutor(max_workers=1, thread_name_prefix='proctorai-alert')
    pending = None
    last_alert, last_pose = -float('inf'), -float('inf')
    pose = None
    frames, fps, started = 0, 0.0, time.monotonic()
    title = 'ProctorAI real-time pipeline - q to quit'
    print('Live pipeline starting. Press q to quit.', flush=True)
    print('Press c in your normal exam posture to calibrate head pose.', flush=True)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            now = time.monotonic()
            if pending is not None and pending.done():
                try:
                    pending.result()
                    print('Alert posted to backend.', flush=True)
                except requests.RequestException as exc:
                    print(f'Backend alert failed: {exc}', flush=True)
                pending = None
            events = objects.update(frame, now)
            if objects.error:
                raise RuntimeError(objects.error)
            if now - last_pose >= 1 / 6:
                last_pose = now
                pose = head.process_frame(frame, now)
                signals = {event.type for event in events}
                if pose:
                    signals.add(pose.type)
                alert = scorer.update(signals, time.time())
                if alert and now - last_alert >= COOLDOWN_SECONDS and (pending is None or pending.done()):
                    payload = dict(session_id=1, type='+'.join(alert.active_signals),
                                   confidence=alert.score, timestamp=alert.timestamp)
                    pending = http.submit(post_alert, payload)
                    last_alert = now
                    print(f'Alert: {payload["type"]} | score {alert.score:.2f}', flush=True)
            annotated = head.annotate_frame(objects.annotate_frame(frame))
            frames += 1
            elapsed = now - started
            if elapsed >= 1:
                fps, frames, started = frames / elapsed, 0, now
            status = f'Live: {fps:.0f} fps | AI check: {objects.last_inference_seconds:.2f}s' if objects.ready else 'Live camera | Loading object AI...'
            cv2.putText(annotated, status, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 0), 2)
            cv2.imshow(title, annotated)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('c'):
                head.begin_calibration()
            if key == ord('q') or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        objects.close()
        head.close()
        http.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
