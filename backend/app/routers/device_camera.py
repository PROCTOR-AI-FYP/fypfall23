"""Browser camera capture with the same cookie, role, seat and case permissions."""
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.db import acquire_connection
from app.deps import CurrentUser, resolve_session_user
from app.models import Role
from app.routers.sessions import _visible_session
from app.services.device_camera import MAX_IMAGE_BYTES, device_camera
from app.services.detection import get_detection_config

router = APIRouter(tags=['device camera'])
async def authenticated(request: Request):
    async with acquire_connection() as conn:
        return await resolve_session_user(conn, request.cookies.get(settings.session_cookie_name))


async def teacher(user: CurrentUser = Depends(authenticated)):
    if user.role != Role.TEACHER:
        raise HTTPException(403, 'Only the assigned invigilator can capture exam evidence.')
    return user


class DeviceStart(BaseModel):
    seat_number: int = Field(ge=1, le=1000)


def enabled():
    if not settings.device_camera_enabled:
        raise HTTPException(503, 'Device camera monitoring is disabled.')


async def verify_exam(conn, session_id, user, seat, expected_student_id=None):
    if user.role != Role.TEACHER:
        raise HTTPException(403, 'Only the assigned invigilator can capture exam evidence.')
    session = await _visible_session(conn, UUID(session_id), user)
    if session['status'] != 'in_progress':
        raise HTTPException(409, 'This exam session is not in progress. Camera stopped.')
    student = await conn.fetchval('''SELECT sa.student_id FROM seat_assignments sa JOIN users u ON u.id=sa.student_id
        WHERE sa.session_id=$1 AND sa.seat_number=$2 AND u.status='active' AND u.deleted_at IS NULL''', UUID(session_id), seat)
    if student is None or (expected_student_id is not None and str(student) != expected_student_id):
        raise HTTPException(409, 'The registered student seat assignment changed. Camera stopped.')
    return str(student)


@router.get('/api/sessions/{session_id}/device-camera/seats')
async def seats(session_id: UUID, user: CurrentUser = Depends(teacher)):
    enabled()
    async with acquire_connection() as conn:
        await _visible_session(conn, session_id, user)
        rows = await conn.fetch('''SELECT sa.seat_number,u.full_name AS student_name,u.registration_or_employee_no AS registration_no
            FROM seat_assignments sa JOIN users u ON u.id=sa.student_id WHERE sa.session_id=$1
            AND u.status='active' AND u.deleted_at IS NULL ORDER BY sa.seat_number''', session_id)
    return [dict(row) for row in rows]


@router.post('/api/sessions/{session_id}/device-camera/start', status_code=201)
async def start(session_id: UUID, body: DeviceStart, user: CurrentUser = Depends(teacher)):
    enabled()
    async with acquire_connection() as conn:
        student = await verify_exam(conn, str(session_id), user, body.seat_number)
    run = device_camera.start(user.user_id, session_id=str(session_id), seat_number=body.seat_number, student_id=student)
    return {'run_id': run.run_id}


@router.post('/api/device-camera/check/start', status_code=201)
async def check_start(user: CurrentUser = Depends(authenticated)):
    enabled()
    # A personal equipment check cannot create evidence, cases or notifications.
    return {'run_id': device_camera.start(user.user_id).run_id}


@router.post('/api/device-camera/{run_id}/stop', status_code=204)
async def stop(run_id: UUID, user: CurrentUser = Depends(authenticated)):
    run = device_camera.get(str(run_id), user.user_id)
    device_camera.stop(run)


@router.post('/api/device-camera/{run_id}/frame')
async def frame(run_id: UUID, request: Request,
                frame_index: int = Query(ge=0), head_sustained: bool = Query(False),
                user: CurrentUser = Depends(authenticated)):
    enabled()
    run = device_camera.get(str(run_id), user.user_id)
    if run.session_id:
        async with acquire_connection() as conn:
            await verify_exam(conn, run.session_id, user, run.seat_number, run.student_id)
    if request.headers.get('content-type', '').split(';')[0] != 'image/jpeg':
        raise HTTPException(415, 'Camera samples must be JPEG images.')
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > MAX_IMAGE_BYTES:
            raise HTTPException(413, 'Camera sample exceeds the 1 MB limit.')
    data = bytes(chunks)
    scene, events, objects, seconds = await device_camera.infer(run, data, frame_index)
    alert = None
    alert_error = None
    if run.session_id:
        # Re-check after inference: an exam/assignment/account can change while
        # the model works. Never keep a DB connection during expensive inference.
        async with acquire_connection() as conn:
            current = await resolve_session_user(conn, request.cookies.get(settings.session_cookie_name))
            await verify_exam(conn, run.session_id, current, run.seat_number, run.student_id)
            config = await get_detection_config(conn)
            scores = run.observe(events, time.monotonic(), config)
            if scores:
                # Head pose is browser-measured context, never standalone evidence.
                if head_sustained:
                    scores['HEAD_POSE_VIOLATION'] = .65
                try:
                    case = await device_camera.persist(run, scene, scores, config, conn)
                    alert = case.model_dump(mode='json') if case else None
                    if case:
                        from app.sockets import emit_sync
                        await emit_sync()
                except HTTPException:
                    raise
                except Exception:
                    alert_error = 'Detection worked, but evidence could not be saved. Monitoring will retry.'
    return {'objects': objects, 'ai_seconds': seconds, 'frame_index': frame_index,
            'alert': alert, 'alert_error': alert_error}
