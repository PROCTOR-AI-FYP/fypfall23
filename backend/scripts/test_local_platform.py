"""Run platform tests only against this task's isolated local services.

Never uses backend/.env database/Redis endpoints. The test suite truncates its
database, so this launcher refuses any name, host or port outside this fixture.
"""
import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'ai-engine/.runtime/platform-tests/test-services.json'


async def run():
    config = json.loads(FIXTURE.read_text())
    if config['database']!='proctorai_integration_tests' or config['port']!=55432 or config['redis_port']!=56379:
        raise RuntimeError('Unexpected destructive-test fixture configuration')
    admin = f"postgresql://postgres:{config['password']}@127.0.0.1:55432/"
    conn = await asyncpg.connect(admin+'postgres')
    try:
        exists = await conn.fetchval('SELECT 1 FROM pg_database WHERE datname=$1',config['database'])
        if not exists:
            await conn.execute('CREATE DATABASE proctorai_integration_tests')
    finally:
        await conn.close()
    env = {**os.environ,'APP_ENV':'test','DATABASE_ADMIN_URL':admin+config['database'],
           'DATABASE_URL':'postgresql://app_user:app_password@127.0.0.1:55432/proctorai_integration_tests',
           'REDIS_URL':'redis://127.0.0.1:56379/0','REQUIRE_REDIS_TLS':'false','MQTT_ENABLED':'false',
           'SUPABASE_SERVICE_ROLE_KEY':'','ANTHROPIC_API_KEY':'','LOCAL_CAMERA_ENABLED':'true',
           'JWT_SECRET':'isolated-platform-test-secret-for-fixtures-only',
           'SESSION_COOKIE_NAME':'proctorai_test_session'}
    env['PATH']=str(ROOT/'ai-engine/.runtime/tools')+os.pathsep+env['PATH']
    temp = ROOT / 'ai-engine/.runtime/platform-tests' / ('pytest-' + uuid.uuid4().hex)
    result = subprocess.run([sys.executable,'-m','pytest','tests','--basetemp',str(temp),*sys.argv[1:]],cwd=ROOT/'backend',env=env)
    raise SystemExit(result.returncode)


if __name__=='__main__':
    asyncio.run(run())
