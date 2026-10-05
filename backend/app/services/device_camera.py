"""Bounded server inference for authenticated browser-camera samples.

The browser owns camera capture; this service never opens a server webcam.
Runs are ephemeral, bound to the signed-in user and (for exams) the registered
student. Only server model observations can create object evidence.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.models import BehaviourType
from app.schemas import DetectionEventIn
from app.services.detection import DetectionConfig

logger = logging.getLogger('proctorai.device-camera')
MAX_IMAGE_BYTES = 1024 * 1024
IDLE_SECONDS = 90


def decode_frame(data: bytes):
    import cv2
    import numpy as np
    from PIL import Image
    from io import BytesIO
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, 'Camera sample exceeds the 1 MB limit.')
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if image.format != 'JPEG' or min(width, height) < 120 or max(width, height) > 1600 or width * height > 1920000:
                raise ValueError('Unsupported camera image')
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('Invalid camera image')
        return frame
    except Exception as exc:
        raise HTTPException(422, 'Send a valid JPEG camera sample, at most 1600 pixels per side.') from exc


@dataclass
class DeviceRun:
    owner_id: str
    session_id: str | None = None
    seat_number: int | None = None
    student_id: str | None = None
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    touched: float = field(default_factory=time.monotonic)
    detector: object | None = None
    busy: bool = False
    stopped: bool = False
    frame_index: int = -1
    histories: dict = field(default_factory=dict)

    def observe(self, events, now: float, config: DetectionConfig) -> dict[str, float] | None:
        """Three fresh matching recognitions spanning >=3 seconds; never fill gaps."""
        current = {}
        for event in events:
            signal = BehaviourType(event.type)
            if event.confidence >= config.thresholds[signal]:
                current[(event.type, event.track_id)] = event.confidence
        for key in list(self.histories):
            if key not in current:
                self.histories.pop(key)
        active = {}
        for key, confidence in current.items():
            history = self.histories.setdefault(key, [])
            if history and now - history[-1][0] > 10:
                history.clear()
            history.append((now, confidence))
            while history and now - history[0][0] > 12:
                history.pop(0)
            if len(history) >= 3 and now - history[0][0] >= 3:
                active[key[0]] = sum(value for _, value in history) / len(history)
        return active or None


class DeviceCameraService:
    def __init__(self):
        self.runs: dict[str, DeviceRun] = {}
        self.model = None
        self.inference_lock = asyncio.Lock()

    def start(self, owner_id, *, session_id=None, seat_number=None, student_id=None):
        now = time.monotonic()
        for key, run in list(self.runs.items()):
            if run.stopped or now - run.touched > IDLE_SECONDS:
                run.stopped = True
                self.runs.pop(key)
        for run in self.runs.values():
            if run.owner_id == owner_id and run.session_id == session_id:
                raise HTTPException(409, 'This camera is already open in another tab. Stop it there or retry after 90 seconds.')
        if len(self.runs) >= 16:
            raise HTTPException(429, 'Camera capacity is busy. Retry shortly.')
        run = DeviceRun(owner_id, session_id, seat_number, student_id)
        self.runs[run.run_id] = run
        return run

    def get(self, run_id, owner_id):
        run = self.runs.get(run_id)
        if run is None or run.owner_id != owner_id or run.stopped:
            raise HTTPException(404, 'Camera connection expired. Start the camera again.')
        if time.monotonic() - run.touched > IDLE_SECONDS:
            run.stopped = True
            self.runs.pop(run_id, None)
            raise HTTPException(410, 'Camera connection expired. Start the camera again.')
        run.touched = time.monotonic()
        return run

    def stop(self, run):
        run.stopped = True
        self.runs.pop(run.run_id, None)

    def _infer(self, run, data):
        from app.vision.grounding import GroundingModel
        from app.vision.phone import PhoneDetector
        frame = decode_frame(data)
        if self.model is None:
            from pathlib import Path
            model_path = Path(settings.device_camera_model_path)
            if not model_path.exists() and settings.app_env != 'production':
                local = Path(__file__).resolve().parents[3] / 'ai-engine/models/grounding-dino-tiny'
                if local.exists():
                    model_path = local
            self.model = GroundingModel(model_path)
        if run.detector is None:
            run.detector = PhoneDetector(model=self.model, use_tiling=False, full_imgsz=640,
                                         min_hits=2, track_ttl=10)
        events = run.detector.process_frame(frame)
        height, width = frame.shape[:2]
        confirmed = {event.track_id for event in events}
        objects = []
        for track in run.detector._tracks:
            detection = track.detection
            if track.missed_frames or detection.confidence < run.detector.thresholds[detection.type]:
                continue
            objects.append(dict(label=detection.label, type=detection.type, confidence=detection.confidence,
                                track_id=track.id, confirmed=track.id in confirmed,
                                box=[v / (width if i % 2 == 0 else height) for i, v in enumerate(detection.box)]))
        return frame, events, objects, run.detector.last_inference_seconds

    async def infer(self, run, data, frame_index):
        if run.busy or self.inference_lock.locked():
            raise HTTPException(429, 'Object checker is busy; the camera preview continues.', headers={'Retry-After': '1'})
        if frame_index <= run.frame_index:
            raise HTTPException(409, 'Camera sample is out of order.')
        run.busy = True
        run.frame_index = frame_index
        try:
            async with self.inference_lock:
                task = asyncio.create_task(asyncio.to_thread(self._infer, run, data))
                try:
                    result = await asyncio.shield(task)
                except asyncio.CancelledError:
                    # A browser disconnect cannot release the shared model lock
                    # while its CPU thread is still working.
                    await task
                    raise
            if run.stopped:
                raise HTTPException(410, 'Camera was stopped.')
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception('Device camera inference failed')
            raise HTTPException(503, 'Object model is unavailable. Retry shortly; head pose and preview remain on your device.') from exc
        finally:
            run.busy = False

    async def persist(self, run, frame, scores, config, conn):
        from app.redis_client import get_redis
        from app.services.detection import cooldown_key
        from app.services.storage import get_storage
        from app.routers.internal import save_detection
        import cv2
        score = config.composite({BehaviourType(k): v for k, v in scores.items() if k != 'HEAD_POSE_VIOLATION'})
        if score < .75:
            return None
        key = cooldown_key(run.session_id, run.seat_number)
        claim = str(uuid.uuid4())
        if not await get_redis().set(key, claim, nx=True, ex=20):
            return None
        path = f'{settings.supabase_snapshot_bucket}/{run.session_id}/{uuid.uuid4()}.jpg'
        storage = get_storage()
        uploaded = False
        try:
            encoded, jpeg = cv2.imencode('.jpg', run.detector.annotate_frame(frame), [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not encoded:
                raise RuntimeError('Evidence encoding failed')
            await storage.upload(path, jpeg.tobytes(), 'image/jpeg')
            uploaded = True
            body = DetectionEventIn(session_id=run.session_id, seat_number=run.seat_number,
                                   behaviour_types=list(scores), per_signal=scores, composite_score=score,
                                   snapshot_path=path, detected_at=datetime.now(timezone.utc))
            return await save_detection(body, conn, expected_student_id=run.student_id,
                                        expected_invigilator_id=run.owner_id)
        except Exception:
            if uploaded:
                await storage.delete([path])
            await get_redis().eval("if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0", 1, key, claim)
            raise


device_camera = DeviceCameraService()
