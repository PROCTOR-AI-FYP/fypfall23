"""Isolated browser QA: real UI/API/models, recorded camera scene, fixture users.

Never imported by the application. Uses a NEW disposable local database, a
distinct session cookie and ports 8003/5181. No Google or real-account bypass.
Run from the repository with venv/Scripts/python.exe after test services start.
"""
from pathlib import Path
import asyncio
import json
import os
import re
import sys
import time
import uuid

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
config = json.loads((ROOT/'ai-engine/.runtime/platform-tests/test-services.json').read_text())
if config['port'] != 55432 or config['redis_port'] != 56379 or config['database'] != 'proctorai_integration_tests':
    raise RuntimeError('Refusing a non-fixture database')
runtime=ROOT/'ai-engine/.runtime/platform-browser'
reuse='--reuse' in sys.argv
DATABASE = json.loads((runtime/'fixture.json').read_text())['database'] if reuse else 'proctorai_browser_' + uuid.uuid4().hex[:12]
if not re.fullmatch(r'proctorai_browser_[0-9a-f]{12}',DATABASE):
    raise RuntimeError('Refusing a non-browser-fixture database')
ADMIN = f"postgresql://postgres:{config['password']}@127.0.0.1:55432/"
os.environ.update(APP_ENV='test',DATABASE_URL=f'postgresql://app_user:app_password@127.0.0.1:55432/{DATABASE}',
    DATABASE_ADMIN_URL=ADMIN+DATABASE,REDIS_URL='redis://127.0.0.1:56379/1',REQUIRE_REDIS_TLS='false',
    MQTT_ENABLED='false',SUPABASE_SERVICE_ROLE_KEY='',ANTHROPIC_API_KEY='',LOCAL_CAMERA_ENABLED='true',
    JWT_SECRET='browser-fixture-only-secret-never-used-by-real-platform',SESSION_COOKIE_NAME='proctorai_browser_fixture',
    CORS_ALLOWED_ORIGINS='http://127.0.0.1:5181')

from app.main import app, asgi_app
from app.db import acquire_connection
from app.models import Role
from app.security import create_access_token,set_session_cookie
from app.services import camera
from app.services import storage
from fastapi import HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from fastapi.responses import FileResponse
import uvicorn

SESSION='00000000-0000-0000-0000-00000000b001'
camera.EVIDENCE_ROOT=ROOT/'ai-engine/.runtime/platform-browser/evidence'
SCENES={'phones_books':'live-test/frame-45.jpg','neutral':'head-pose-live/neutral.jpg',
        'left':'head-pose-live/left.jpg','right':'head-pose-live/right.jpg','down':'head-pose-live/down.jpg',
        'difficult':'realtime-corrected-live-v3-raw-021.jpg','empty':'realtime-corrected-live-v3-raw-000.jpg'}
scene='phones_books'


class FixtureStorage:
    """Local QA adapter only; never use real Supabase keys or write real cases."""
    def __init__(self):self.saved={}
    async def upload(self,path,data,content_type):self.saved[path]=data
    async def delete(self,paths):
        for path in paths:self.saved.pop(path,None)
    async def signed_url(self,path,expires_in=60):
        return '/api/fixture/image/phones_books'


fixture_storage=FixtureStorage()
storage.get_storage=lambda:fixture_storage
from app.routers import media
media.get_storage=lambda:fixture_storage


@app.get('/api/fixture/image/{name}',include_in_schema=False)
async def fixture_image(name:str):
    if name not in SCENES:
        raise HTTPException(404)
    return FileResponse(ROOT/'ai-engine/validation-output'/SCENES[name])


class ReplayCamera:
    def __init__(self):
        import cv2
        self.selected=scene
        self.frame=cv2.imread(str(ROOT/'ai-engine/validation-output'/SCENES[self.selected]))
        if self.frame is None: raise RuntimeError('Recorded camera fixture missing')
    def read(self):
        if scene!=self.selected:
            import cv2
            self.selected=scene
            self.frame=cv2.imread(str(ROOT/'ai-engine/validation-output'/SCENES[self.selected]))
        time.sleep(1/18)
        return True,self.frame.copy()
    def release(self): pass


def monitor_factory(sink,**kwargs):
    sys.path.insert(0,str(ROOT))
    from backend.object_monitor import ObjectMonitor
    return ObjectMonitor(sink,camera=ReplayCamera,**kwargs)


camera.platform_camera.monitor_factory=monitor_factory


@app.get('/api/fixture',include_in_schema=False)
async def fixture_menu():
    return HTMLResponse('<h1>Isolated platform QA</h1><p>Fixture accounts and recorded camera scene. No real cases.</p>'+
        ''.join(f'<p><a href="/api/fixture/login/{role.value}">{role.value}</a></p>' for role in Role)+
        '<h2>Recorded camera scene</h2>'+''.join(f'<p><a href="/api/fixture/scene/{name}">{name}</a></p>' for name in SCENES))


@app.get('/api/fixture/scene/{name}',include_in_schema=False)
async def choose_scene(name:str):
    global scene
    if name not in SCENES: raise HTTPException(404)
    scene=name
    return RedirectResponse(f'/teacher/live-monitor/{SESSION}')


@app.get('/api/fixture/login/{role}',include_in_schema=False)
async def fixture_login(role:Role):
    async with acquire_connection() as conn:
        user=await conn.fetchval('SELECT id FROM users WHERE role=$1 ORDER BY email LIMIT 1',role.value)
    if user is None: raise HTTPException(404)
    route={'admin':'/admin/dashboard','teacher':f'/teacher/live-monitor/{SESSION}','hod':'/hod/dashboard',
           'student':'/student/cases','exam_controller':'/exam-controller/schedule'}[role.value]
    response=RedirectResponse(route)
    set_session_cookie(response,create_access_token(user_id=str(user),role=role))
    return response


async def prepare():
    if reuse:
        return
    conn=await asyncpg.connect(ADMIN+'postgres')
    try: await conn.execute(f'CREATE DATABASE {DATABASE}')
    finally: await conn.close()
    conn=await asyncpg.connect(ADMIN+DATABASE)
    try:
        await conn.execute((ROOT/'backend/db/schema.sql').read_text(encoding='utf-8'))
        await conn.execute((ROOT/'backend/db/seed.sql').read_text(encoding='utf-8'))
        await conn.execute("UPDATE users SET supabase_user_id=gen_random_uuid()")
        await conn.execute('''INSERT INTO exam_sessions(id,course_code,course_name,department,room,classroom_id,status,invigilator_id,scheduled_date,start_time,end_time)
            SELECT $1,'CS-QA','Recorded camera verification','Computer Science','Hall-A',
            '00000000-0000-0000-0000-0000000c0001','in_progress',id,CURRENT_DATE,'09:00','23:59'
            FROM users WHERE role='teacher' ''',SESSION)
        await conn.execute('''INSERT INTO seat_assignments(session_id,seat_number,student_reg_no,student_id)
            SELECT $1,14,'232475',id FROM users WHERE registration_or_employee_no='232475' ''',SESSION)
        if '--two-students' in sys.argv:
            await conn.execute('''INSERT INTO seat_assignments(session_id,seat_number,student_reg_no,student_id)
                SELECT $1,25,'232490',id FROM users WHERE registration_or_employee_no='232490' ''',SESSION)
        await conn.execute("UPDATE detection_thresholds SET sensitivity=40 WHERE behaviour_type='UNAUTHORISED_OBJECT'")
    finally: await conn.close()
    runtime=ROOT/'ai-engine/.runtime/platform-browser'
    runtime.mkdir(parents=True,exist_ok=True)
    (runtime/'fixture.json').write_text(json.dumps({'database':DATABASE,'session_id':SESSION,'mode':'real models / recorded scene / disposable accounts'}))


if __name__=='__main__':
    asyncio.run(prepare())
    uvicorn.run(asgi_app,host='127.0.0.1',port=8003,loop='asyncio',http='h11',access_log=False)
