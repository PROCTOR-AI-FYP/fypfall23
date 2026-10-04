"""Authenticated controls and feed for the assigned invigilator's camera."""
import asyncio
from uuid import UUID

import asyncpg
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field

from app.deps import CurrentUser,get_db,require_role,resolve_session_user
from app.db import acquire_connection
from app.services.authorization import can_access_session
from app.config import settings
from app.models import Role
from app.routers.sessions import _visible_session
from app.services.camera import platform_camera
from app.services.detection import get_detection_config

router = APIRouter(prefix='/api/sessions/{session_id}/camera',tags=['camera'])
reader = require_role(Role.TEACHER,Role.HOD)
controller = require_role(Role.TEACHER)


class CameraStart(BaseModel):
    seat_number: int = Field(ge=1,le=1000)


async def visible(conn,session_id,user,*,active=False):
    if not settings.local_camera_enabled:
        raise HTTPException(503,'Local camera monitoring is not enabled on this server.')
    session = await _visible_session(conn,session_id,user)
    if active and session['status']!='in_progress':
        raise HTTPException(409,'Start this exam session before monitoring.')
    return session


@router.get('/seats')
async def seats(session_id:UUID,user:CurrentUser=Depends(reader),conn:asyncpg.Connection=Depends(get_db)):
    await visible(conn,session_id,user)
    rows = await conn.fetch('''SELECT sa.seat_number,u.full_name AS student_name,u.registration_or_employee_no AS registration_no
        FROM seat_assignments sa JOIN users u ON u.id=sa.student_id WHERE sa.session_id=$1
        AND u.status='active' AND u.deleted_at IS NULL ORDER BY sa.seat_number''',session_id)
    return [dict(row) for row in rows]


@router.get('/status')
async def camera_status(session_id:UUID,user:CurrentUser=Depends(reader),conn:asyncpg.Connection=Depends(get_db)):
    await visible(conn,session_id,user)
    return platform_camera.status(str(session_id))


@router.post('/start',status_code=202)
async def start(session_id:UUID,body:CameraStart,user:CurrentUser=Depends(controller),conn:asyncpg.Connection=Depends(get_db)):
    await visible(conn,session_id,user,active=True)
    mapped = await conn.fetchval('''SELECT sa.student_id FROM seat_assignments sa JOIN users u ON u.id=sa.student_id
        WHERE sa.session_id=$1 AND sa.seat_number=$2 AND u.status='active' AND u.deleted_at IS NULL''',session_id,body.seat_number)
    if mapped is None:
        raise HTTPException(409,'Assign a registered student to this seat before monitoring.')
    return await platform_camera.start(str(session_id),body.seat_number,await get_detection_config(conn),student_id=str(mapped),owner_id=user.user_id)


@router.post('/stop')
async def stop(session_id:UUID,user:CurrentUser=Depends(controller),conn:asyncpg.Connection=Depends(get_db)):
    await visible(conn,session_id,user)
    await platform_camera.stop(str(session_id))
    return platform_camera.status(str(session_id))


@router.post('/calibrate',status_code=202)
async def calibrate(session_id:UUID,user:CurrentUser=Depends(controller),conn:asyncpg.Connection=Depends(get_db)):
    await visible(conn,session_id,user,active=True)
    state = platform_camera.status(str(session_id))
    if not state['running']:
        raise HTTPException(409,'Start the camera before calibrating.')
    try:
        platform_camera.monitor.calibrate_head()
    except RuntimeError as exc:
        raise HTTPException(409,str(exc)) from exc
    return platform_camera.status(str(session_id))


@router.get('/feed')
async def feed(session_id:UUID,request:Request):
    # Release authorization's pooled connection before the long-lived stream.
    async with acquire_connection() as conn:
        user=await resolve_session_user(conn,request.cookies.get(settings.session_cookie_name))
        if user.role not in {Role.TEACHER,Role.HOD}:
            raise HTTPException(403,'Insufficient role')
        await visible(conn,session_id,user,active=True)
    state = platform_camera.status(str(session_id))
    if not state['running']:
        raise HTTPException(409,'Camera is stopped.')
    monitor = platform_camera.monitor
    async def frames():
        sequence = -1
        checked = 0.
        while monitor.status()['running'] and monitor.status()['session_id']==str(session_id):
            now=asyncio.get_running_loop().time()
            if now-checked>2:
                checked=now
                try:
                    async with acquire_connection() as current_conn:
                        current=await resolve_session_user(current_conn,request.cookies.get(settings.session_cookie_name))
                        assignment=await current_conn.fetchval('SELECT invigilator_id FROM exam_sessions WHERE id=$1',session_id)
                        if current.role not in {Role.TEACHER,Role.HOD} or not can_access_session(role=current.role,user_id=current.user_id,invigilator_id=str(assignment) if assignment else None):
                            return
                except Exception:
                    return
            current,jpeg = monitor.latest_frame()
            if jpeg is not None and current!=sequence:
                sequence=current
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+jpeg+b'\r\n'
            await asyncio.sleep(1/20)
    return StreamingResponse(frames(),media_type='multipart/x-mixed-replace; boundary=frame',headers={'Cache-Control':'no-store'})
