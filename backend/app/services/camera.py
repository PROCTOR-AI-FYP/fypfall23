"""One local camera bound explicitly to one registered exam seat.

Inference runs in the camera thread; persistence uses the platform's existing
case ingestion transaction. Camera images stay on this PC.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from app.config import settings
from app.db import acquire_connection
from app.models import BehaviourType
from app.schemas import DetectionEventIn
from app.services.detection import DetectionConfig, get_detection_config
from app.services.signal_policy import object_signal_score

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = PROJECT_ROOT / 'ai-engine/.runtime/platform-evidence'


def local_snapshot_path(path: str) -> Path | None:
    parts = path.split('/')
    if len(parts) != 3 or parts[0] != settings.supabase_snapshot_bucket or not parts[2].startswith('local-'):
        return None
    try:
        uuid.UUID(parts[1])
        uuid.UUID(parts[2].removeprefix('local-').removesuffix('.jpg'))
    except ValueError:
        return None
    if not parts[2].endswith('.jpg'):
        return None
    return EVIDENCE_ROOT / parts[1] / parts[2]


@dataclass(frozen=True)
class CameraAlert:
    score: float
    active_signals: list[str]
    timestamp: float
    per_signal: dict[str, float]


class CameraScorer:
    def __init__(self, config: DetectionConfig):
        self.config = config
        self.history = deque()
        self.started = None

    def update_scores(self, scores, now):
        if not math.isfinite(now):
            raise ValueError('Invalid camera observation time')
        verified = {}
        for signal, raw in scores.items():
            if not math.isfinite(raw) or not 0 <= raw <= 1:
                raise ValueError('Invalid camera signal confidence')
            if signal in ('PHONE_DETECTED', 'UNAUTHORISED_OBJECT'):
                floor = .50 if signal == 'PHONE_DETECTED' else .60
                if raw >= floor:
                    verified[signal] = object_signal_score(signal, raw)
            elif signal == 'HEAD_POSE_VIOLATION' and raw >= .65:
                # The calibrated head estimator only emits this event after its
                # own uninterrupted two-second violation timer has completed.
                verified[signal] = .85
        duplicate = bool(self.history and now <= self.history[-1][0])
        if self.history and (duplicate or now-self.history[-1][0] > .5):
            self.history.clear()
            self.started = None
        if self.started is None:
            self.started = now
        self.history.append((now, verified))
        while len(self.history)>1 and self.history[1][0] < now-3:
            self.history.popleft()
        if duplicate:
            return None
        active = {}
        for signal in verified:
            behaviour = BehaviourType(signal)
            threshold = self.config.thresholds[behaviour]
            if behaviour == BehaviourType.HEAD_POSE_VIOLATION:
                if verified[signal] >= threshold:
                    active[behaviour] = verified[signal]
                continue
            if now-self.started < 3 or len(self.history)<2:
                continue
            values = [sample.get(signal,0.) for _,sample in self.history]
            qualifying = [value for value in values if value >= threshold and value > 0]
            if len(qualifying)/len(values) >= .6:
                active[behaviour] = sum(qualifying)/len(qualifying)
        if not active:
            return None
        score = self.config.composite(active)
        if score < .75:
            return None
        return CameraAlert(score, [s.value for s in active], now, {s.value:round(v,3) for s,v in active.items()})


class PlatformCamera:
    def __init__(self, *, monitor_factory=None):
        self.monitor_factory = monitor_factory
        self.monitor = None
        self.seat_number = None
        self.scorer = None
        self.watchdog = None
        self.lock = asyncio.Lock()

    def status(self, session_id):
        if self.monitor is None or self.monitor.status()['session_id'] != session_id:
            return dict(phase='stopped',running=False,run_id=0,session_id=session_id,seat_number=None,
                        fps=0,ai_seconds=0,objects=[],checking=[],error=None,alert_error=None,head_pose=None,head_error=None)
        return {**self.monitor.status(), 'seat_number':self.seat_number}

    async def start(self, session_id, seat_number, config, *, student_id=None,owner_id=None):
        async with self.lock:
            if self.monitor is not None and self.monitor.status()['running']:
                state = self.monitor.status()
                if state['session_id']==session_id and self.seat_number==seat_number:
                    return self.status(session_id)
                raise HTTPException(409,'This PC’s camera is already monitoring another session or seat. Stop it first.')
            if await self._stop_locked():
                raise HTTPException(409,'Camera is still stopping. Retry shortly.')
            self.seat_number = seat_number
            self.scorer = CameraScorer(config)
            if self.monitor_factory is None:
                import sys
                sys.path.insert(0,str(PROJECT_ROOT))
                from backend.object_monitor import ObjectMonitor
                factory = ObjectMonitor
            else:
                factory = self.monitor_factory
            async def persist_for_seat(payload):
                return await self.persist(payload,seat_number,student_id)
            self.monitor = factory(persist_for_seat,scorer=lambda:self.scorer,evidence=True)
            self.monitor.start(session_id,asyncio.get_running_loop())
            self.watchdog = asyncio.create_task(self._watch(session_id,seat_number,student_id,owner_id),name='platform-camera-policy')
            return self.status(session_id)

    async def stop(self, session_id=None):
        async with self.lock:
            if self.monitor is not None and (session_id is None or self.monitor.status()['session_id']==session_id):
                await self._stop_locked()

    async def _stop_locked(self):
        task = self.watchdog
        self.watchdog = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        if self.monitor is not None:
            state = await asyncio.to_thread(self.monitor.stop)
            return state.get('phase') == 'stopping'
        return False

    async def _watch(self,session_id,seat_number,student_id,owner_id):
        try:
            while self.monitor is not None and self.monitor.status()['running']:
                await asyncio.sleep(2)
                async with acquire_connection() as conn:
                    state = await conn.fetchrow('''SELECT s.status,s.invigilator_id,inv.role AS inv_role,inv.status AS inv_status,
                        sa.student_id,u.status AS student_status,u.deleted_at AS student_deleted
                        FROM exam_sessions s LEFT JOIN users inv ON inv.id=s.invigilator_id
                        LEFT JOIN seat_assignments sa ON sa.session_id=s.id AND sa.seat_number=$2
                        LEFT JOIN users u ON u.id=sa.student_id WHERE s.id=$1::uuid''',session_id,seat_number)
                    if (state is None or state['status']!='in_progress' or str(state['invigilator_id'])!=owner_id
                        or state['inv_role']!='teacher' or state['inv_status']!='active'
                        or str(state['student_id'])!=student_id or state['student_status']!='active' or state['student_deleted'] is not None):
                        await asyncio.to_thread(self.monitor.stop)
                        self.monitor._publish(error='The exam or monitored student assignment changed. Camera stopped.')
                        return
                    self.scorer.config = await get_detection_config(conn)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Stop rather than collect evidence without an active policy/session check.
            if self.monitor is not None:
                await asyncio.to_thread(self.monitor.stop)
                self.monitor._publish(error='Could not verify the exam session or detection policy. Camera stopped; restart after reconnecting.')

    async def persist(self, payload, seat_number, student_id):
        from app.routers.internal import save_detection
        from app.sockets import emit_sync
        session_id = payload['session_id']
        path = f'{settings.supabase_snapshot_bucket}/{session_id}/local-{uuid.uuid4()}.jpg'
        destination = local_snapshot_path(path)
        destination.parent.mkdir(parents=True,exist_ok=True)
        await asyncio.to_thread(destination.write_bytes,payload['snapshot'])
        body = DetectionEventIn(session_id=session_id,seat_number=seat_number,
                                behaviour_types=list(payload['per_signal']),per_signal=payload['per_signal'],
                                composite_score=payload['confidence'],snapshot_path=path,
                                detected_at=datetime.fromtimestamp(payload['timestamp'],timezone.utc))
        try:
            async with acquire_connection() as conn:
                # Validate attribution inside ingestion's transaction; emit only after commit.
                case = await save_detection(body,conn,expected_student_id=student_id)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        try:
            await emit_sync()
        except Exception:
            logging.getLogger('proctorai.camera').exception('Live invalidation failed after local camera case commit')
        return case.model_dump(mode='json')


platform_camera = PlatformCamera()
