"""Browser camera capture with the same cookie, role, seat and case permissions."""
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.db import acquire_connection
from app.deps import CurrentUser, resolve_session_user
from app.models import Role, BehaviourType
from app.routers.sessions import _visible_session
from app.services.device_camera import MAX_IMAGE_BYTES, device_camera
from app.services.detection import get_detection_config
from app.services.room_camera import RoomStart, RoomState

router = APIRouter(tags=['device camera'])
logger = logging.getLogger('proctorai.device-camera')
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


async def room_students(conn, session_id, user):
    session = await _visible_session(conn, UUID(session_id), user)
    if session['status'] != 'in_progress':
        raise HTTPException(409, 'This exam is not in progress. Camera stopped.')
    rows = await conn.fetch('''SELECT sa.seat_number,sa.student_id FROM seat_assignments sa
        JOIN users u ON u.id=sa.student_id WHERE sa.session_id=$1 AND u.role='student'
        AND u.status='active' AND u.deleted_at IS NULL ORDER BY sa.seat_number''', UUID(session_id))
    return {r['seat_number']:str(r['student_id']) for r in rows}


async def verify_room(conn, run, user):
    if user.role != Role.TEACHER:
        raise HTTPException(403, 'Only the assigned invigilator can monitor this room.')
    if run.room is None:
        raise HTTPException(409, 'Start whole-room monitoring before sending room frames.')
    students = await room_students(conn, run.session_id, user)
    if students != run.room.students:
        raise HTTPException(409, 'The CSV roster changed. Remap the classroom and restart monitoring.')


@router.post('/api/sessions/{session_id}/device-camera/room/start', status_code=201)
async def room_start(session_id: UUID, body: RoomStart, user: CurrentUser = Depends(teacher)):
    enabled()
    async with acquire_connection() as conn:
        students = await room_students(conn,str(session_id),user)
    if not students or set(students) != {r.seat_number for r in body.regions}:
        raise HTTPException(409, 'Map every active CSV student seat once before starting room monitoring.')
    run = device_camera.start(user.user_id,session_id=str(session_id))
    run.room = RoomState.create(run,body.regions,students)
    return {'run_id':run.run_id,'mapped_seats':len(students)}


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

async def camera_sample(request: Request):
    if request.headers.get('content-type', '').split(';')[0] != 'image/jpeg':
        raise HTTPException(415, 'Camera samples must be JPEG images.')
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > MAX_IMAGE_BYTES:
            raise HTTPException(413, 'Camera sample exceeds the 1 MB limit.')
    return bytes(chunks)

async def save_alert(run, request, image, scores, *, head_only=False, evidence=None):
    if not run.session_id or not scores:
        return None, None
    async with acquire_connection() as conn:
        current = await resolve_session_user(conn, request.cookies.get(settings.session_cookie_name))
        await verify_exam(conn, run.session_id, current, run.seat_number, run.student_id)
        config = await get_detection_config(conn)
        try:
            case = await device_camera.persist(run,image,scores,config,conn,head_only=head_only,evidence=evidence)
            if case:
                from app.sockets import emit_sync
                try:
                    await emit_sync()
                except Exception:
                    logger.exception('Saved case %s; live refresh notification failed',case.id)
            return case.model_dump(mode='json') if case else None, None
        except HTTPException:
            raise
        except Exception:
            logger.exception('Could not persist device-camera evidence for run %s', run.run_id)
            return None, 'Detection worked, but evidence could not be saved. Monitoring will retry.'

@router.post('/api/device-camera/{run_id}/head/calibrate', status_code=204)
async def calibrate_head(run_id: UUID, user: CurrentUser = Depends(teacher)):
    enabled()
    run = device_camera.get(str(run_id),user.user_id)
    if not run.session_id:
        raise HTTPException(409,'Server head verification requires an active exam.')
    async with acquire_connection() as conn:
        if run.room is not None:
            await verify_room(conn,run,user)
            for target in run.room.seats.values():
                target.head_score = 0.
        else:
            await verify_exam(conn,run.session_id,user,run.seat_number,run.student_id)
    run.head_calibrate = True
    run.head_epoch += 1
    run.head_score = 0.

@router.post('/api/device-camera/{run_id}/head/frame')
async def head_frame(run_id: UUID, request: Request, frame_index: int = Query(ge=0), user: CurrentUser = Depends(teacher)):
    enabled()
    run = device_camera.get(str(run_id),user.user_id)
    if run.room is not None:
        raise HTTPException(409,'Use room verification for this camera.')
    if not run.session_id:
        raise HTTPException(409,'Server head verification requires an active exam.')
    async with acquire_connection() as conn:
        await verify_exam(conn,run.session_id,user,run.seat_number,run.student_id)
    image,state = await device_camera.verify_head(run,await camera_sample(request),frame_index)
    async with acquire_connection() as conn:
        current = await resolve_session_user(conn, request.cookies.get(settings.session_cookie_name))
        await verify_exam(conn,run.session_id,current,run.seat_number,run.student_id)
        config = await get_detection_config(conn)
    signal = 'HEAD_POSE_VIOLATION'
    scores = {signal:run.head_score} if run.head_score >= config.thresholds[BehaviourType(signal)] else {}
    alert,error = await save_alert(run,request,image,scores,head_only=True)
    return {'head':state,'alert':alert,'alert_error':error,
            'review_enabled':bool(scores)}


@router.post('/api/device-camera/{run_id}/frame')
async def frame(run_id: UUID, request: Request,
                frame_index: int = Query(ge=0), head_sustained: bool = Query(False),
                user: CurrentUser = Depends(authenticated)):
    enabled()
    run = device_camera.get(str(run_id), user.user_id)
    if run.room is not None:
        raise HTTPException(409,'Use room monitoring for this camera.')
    if run.session_id:
        async with acquire_connection() as conn:
            await verify_exam(conn, run.session_id, user, run.seat_number, run.student_id)
    data = await camera_sample(request)
    # Match head context to capture, not to a later pose after slow inference.
    sampled_head_score = run.head_score if time.monotonic()-run.head_verified_at < 1 else 0.
    head_epoch = run.head_epoch
    scene, events, objects, seconds = await device_camera.infer(run, data, frame_index)
    alert = None
    alert_error = None
    observations = 0
    if run.session_id:
        # Re-check after inference: an exam/assignment/account can change while
        # the model works. Never keep a DB connection during expensive inference.
        async with acquire_connection() as conn:
            current = await resolve_session_user(conn, request.cookies.get(settings.session_cookie_name))
            await verify_exam(conn, run.session_id, current, run.seat_number, run.student_id)
            config = await get_detection_config(conn)
            scores = run.observe(events, time.monotonic(), config)
            observations = min(3,max((len(history) for history in run.histories.values()),default=0))
            if scores:
                # Only recently image-verified head pose can accompany objects.
                if head_epoch == run.head_epoch and sampled_head_score >= config.thresholds[BehaviourType.HEAD_POSE_VIOLATION]:
                    scores['HEAD_POSE_VIOLATION'] = sampled_head_score
        alert,alert_error = await save_alert(run,request,scene,scores)
    return {'objects': objects, 'ai_seconds': seconds, 'frame_index': frame_index,
            'alert': alert, 'alert_error': alert_error,
            'review_observations': observations}


@router.post('/api/device-camera/{run_id}/room/head/frame')
async def room_head_frame(run_id: UUID, request: Request, frame_index: int = Query(ge=0),
                          user: CurrentUser = Depends(teacher)):
    enabled()
    run = device_camera.get(str(run_id),user.user_id)
    async with acquire_connection() as conn:
        await verify_room(conn,run,user)
    image,states = await device_camera.verify_head(run,await camera_sample(request),frame_index)
    async with acquire_connection() as conn:
        current = await resolve_session_user(conn,request.cookies.get(settings.session_cookie_name))
        await verify_room(conn,run,current)
        config = await get_detection_config(conn)
    alerts,errors = [],[]
    for state in states:
        # Use the returned sample's state, not a later mutable detector value.
        score = .85 if state['sustained'] else 0.
        state['review_enabled'] = (score >= config.thresholds[BehaviourType.HEAD_POSE_VIOLATION]
            and config.composite({BehaviourType.HEAD_POSE_VIOLATION:score})>=.75)
        if score and score >= config.thresholds[BehaviourType.HEAD_POSE_VIOLATION]:
            target = run.room.seats[state['seat_number']]
            alert,error = await save_alert(target,request,image,{'HEAD_POSE_VIOLATION':score},
                evidence=run.room.evidence(image,target.seat_number))
            if alert: alerts.append(alert)
            if error: errors.append(error)
    return {'seats':states,'alerts':alerts,'alert_error':next(iter(errors),None),
            'image_size':[image.shape[1],image.shape[0]]}


@router.post('/api/device-camera/{run_id}/room/frame')
async def room_frame(run_id: UUID, request: Request, frame_index: int = Query(ge=0),
                     user: CurrentUser = Depends(teacher)):
    enabled()
    run = device_camera.get(str(run_id),user.user_id)
    async with acquire_connection() as conn:
        await verify_room(conn,run,user)
    now = time.monotonic()
    head_epoch = run.head_epoch
    sampled_heads = {seat:target.head_score for seat,target in run.room.seats.items()
                     if now-target.head_verified_at<1}
    scene,target,events,objects,seconds,warning = await device_camera.infer(run,await camera_sample(request),frame_index)
    async with acquire_connection() as conn:
        current = await resolve_session_user(conn,request.cookies.get(settings.session_cookie_name))
        await verify_room(conn,run,current)
        config = await get_detection_config(conn)
    scores = target.observe(events,time.monotonic(),config)
    if scores and head_epoch == run.head_epoch and sampled_heads.get(target.seat_number,0.) >= config.thresholds[BehaviourType.HEAD_POSE_VIOLATION]:
        scores['HEAD_POSE_VIOLATION'] = sampled_heads[target.seat_number]
    alert,error = await save_alert(target,request,scene,scores,
        evidence=run.room.evidence(scene,target.seat_number,objects=True))
    observations = min(3,max((len(h) for h in target.histories.values()),default=0))
    if error:
        review_status = 'failed'
    elif alert:
        review_status = 'saved'
    elif scores:
        review_status = 'cooldown' if config.composite({BehaviourType(k):v for k,v in scores.items()})>=.75 else 'below_review_cutoff'
    else:
        review_status = 'confirming' if observations else 'below_signal_threshold' if objects else 'no_verified_object'
    return {'objects':objects,'ai_seconds':seconds,'frame_index':frame_index,
            'alert':alert,'alert_error':error,'warning':warning,'checked_seat':target.seat_number,
            'mapped_seats':len(run.room.seats),
            'review_observations':observations,'review_status':review_status}
