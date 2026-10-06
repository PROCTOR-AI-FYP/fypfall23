"""Slow object delivery, isolated ownership and post-capture policy guards."""
import asyncio
import threading
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.routers import device_camera as routes
from app.services import device_camera as service
from app.services.device_camera_jobs import ObjectJobs
from tests.helpers import (STUDENT_A_EMAIL, STUDENT_B_EMAIL, TEACHER_EMAIL,
                           auth, login)
from tests.test_detection_pipeline import active_session  # noqa: F401
from tests.test_device_camera import device, jpeg  # noqa: F401


@pytest_asyncio.fixture
async def jobs(device, monkeypatch):
    manager = ObjectJobs()
    monkeypatch.setattr(routes, 'object_jobs', manager)
    yield manager
    await manager.close()
    assert not manager.jobs and not manager.by_run
    assert all(task.done() for task in manager.tasks)


async def enqueue(client, headers, run_id, *, index=0, mode='single'):
    result = await client.post(
        f'/api/device-camera/{run_id}/object-jobs?frame_index={index}&mode={mode}',
        headers={**headers, 'Content-Type': 'image/jpeg'}, content=jpeg())
    assert result.status_code == 202, result.text
    assert result.json()['state'] == 'running'
    return result.json()['job_id']


async def completed(client, headers, run_id, job_id, jobs):
    await asyncio.wait_for(asyncio.shield(jobs.jobs[job_id].task), 5)
    result = await client.get(f'/api/device-camera/{run_id}/object-jobs/{job_id}', headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['state'] == 'complete'
    return result.json()['result']


async def test_device_camera_job_survives_short_http_wait_and_has_no_inference_queue(client, device, jobs, monkeypatch):
    headers = auth(await login(client, STUDENT_A_EMAIL))
    run_id = (await client.post('/api/device-camera/check/start', headers=headers)).json()['run_id']
    original = device._infer
    entered, finish = threading.Event(), threading.Event()

    def delayed(run, data):
        entered.set()
        assert finish.wait(5)
        return original(run, data)

    monkeypatch.setattr(device, '_infer', delayed)
    job_id = await enqueue(client, headers, run_id)
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        job = jobs.jobs[job_id]
        # A short browser/proxy request lifetime never owns the model task.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(job.task), .01)
        response = await client.get(f'/api/device-camera/{run_id}/object-jobs/{job_id}', headers=headers)
        assert response.json() == {'state': 'running'}
        duplicate = await client.post(f'/api/device-camera/{run_id}/object-jobs?frame_index=1',
                                      headers={**headers, 'Content-Type': 'image/jpeg'}, content=jpeg())
        assert duplicate.status_code == 429
        assert len(jobs.jobs) == 1 and not job.task.done()
        other = auth(await login(client, STUDENT_B_EMAIL))
        other_run = (await client.post('/api/device-camera/check/start', headers=other)).json()['run_id']
        busy = await client.post(f'/api/device-camera/{other_run}/object-jobs?frame_index=0',
                                 headers={**other, 'Content-Type': 'image/jpeg'}, content=jpeg())
        assert busy.status_code == 429 and busy.headers['Retry-After'] == '1'
    finally:
        finish.set()
    result = await completed(client, headers, run_id, job_id, jobs)
    assert result['objects'][0]['label'] == 'phone' and result['frame_index'] == 0
    assert result['alert'] is None and result['detections'] == []
    replay = await client.post(f'/api/device-camera/{run_id}/object-jobs?frame_index=0',
                               headers={**headers, 'Content-Type': 'image/jpeg'}, content=jpeg())
    assert replay.status_code == 409
    next_id = await enqueue(client, headers, run_id, index=1)
    assert next_id != job_id and len(jobs.jobs) == 1
    assert (await client.get(f'/api/device-camera/{run_id}/object-jobs/{job_id}', headers=headers)).status_code == 404
    await completed(client, headers, run_id, next_id, jobs)


async def test_device_camera_job_result_is_private_and_preserves_model_failure(client, device, jobs, monkeypatch):
    owner = auth(await login(client, STUDENT_A_EMAIL))
    other = auth(await login(client, STUDENT_B_EMAIL))
    run_id = (await client.post('/api/device-camera/check/start', headers=owner)).json()['run_id']

    def failed(run, data):
        raise HTTPException(503, 'Fixture model unavailable', headers={'Retry-After': '3'})

    monkeypatch.setattr(device, '_infer', failed)
    job_id = await enqueue(client, owner, run_id)
    await asyncio.wait_for(jobs.jobs[job_id].task, 5)
    path = f'/api/device-camera/{run_id}/object-jobs/{job_id}'
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=other)).status_code == 404
    error = await client.get(path, headers=owner)
    assert error.status_code == 503 and error.json()['detail'] == 'Fixture model unavailable'
    assert error.headers['Retry-After'] == '3'


@pytest.mark.parametrize('change,expected', [('seat', 409), ('role', 403),
                                           ('disabled', 401), ('exam', 409), ('invigilator', 404)])
async def test_device_camera_job_poll_rechecks_current_exam_access(client, admin_conn, active_session,
                                                                 device, jobs, change, expected):
    headers = auth(await login(client, TEACHER_EMAIL))
    run_id = (await client.post(f'/api/sessions/{active_session}/device-camera/start', headers=headers,
                                json={'seat_number': 14})).json()['run_id']
    job_id = await enqueue(client, headers, run_id)
    await completed(client, headers, run_id, job_id, jobs)
    if change == 'seat':
        await admin_conn.execute('UPDATE seat_assignments SET student_id=(SELECT id FROM users WHERE email=$1) WHERE session_id=$2::uuid',
                                 STUDENT_B_EMAIL, active_session)
    elif change == 'role':
        await admin_conn.execute("UPDATE users SET role='hod' WHERE email=$1", TEACHER_EMAIL)
    elif change == 'disabled':
        await admin_conn.execute("UPDATE users SET status='disabled' WHERE email=$1", TEACHER_EMAIL)
    elif change == 'exam':
        await admin_conn.execute("UPDATE exam_sessions SET status='completed' WHERE id=$1::uuid", active_session)
    else:
        await admin_conn.execute('UPDATE exam_sessions SET invigilator_id=NULL WHERE id=$1::uuid', active_session)
    response = await client.get(f'/api/device-camera/{run_id}/object-jobs/{job_id}', headers=headers)
    assert response.status_code == expected and 'objects' not in response.text
    if change != 'disabled':
        assert job_id not in jobs.jobs and device.runs.get(run_id) is None


@pytest.mark.parametrize('initial,changed_epoch', [(0., False), (.85, True)])
async def test_device_camera_job_uses_capture_head_context_and_returns_committed_alert(client, admin_conn,
                                                                                    active_session, device, jobs,
                                                                                    monkeypatch, initial, changed_epoch):
    from app.services import storage
    class PrivateStorage:
        async def upload(self, *args): pass
        async def delete(self, *args): pass
    monkeypatch.setattr(storage, 'get_storage', lambda: PrivateStorage())
    headers = auth(await login(client, TEACHER_EMAIL))
    run_id = (await client.post(f'/api/sessions/{active_session}/device-camera/start', headers=headers,
                                json={'seat_number': 14})).json()['run_id']
    run = device.runs[run_id]
    now = service.time.monotonic()
    run.histories[('PHONE_DETECTED', 1)] = [(now-4, .968), (now-2, .968)]
    run.head_score = initial
    run.head_verified_at = now
    gate = asyncio.Event()
    authenticate = routes.authenticated

    async def delayed_cookie_check(request):
        await gate.wait()
        return await authenticate(request)

    # Depends captured the original authenticator; only deferred work waits.
    monkeypatch.setattr(routes, 'authenticated', delayed_cookie_check)
    job_id = await enqueue(client, headers, run_id)
    run.head_score = .85
    run.head_verified_at = service.time.monotonic()
    if changed_epoch:
        run.head_epoch += 1
    gate.set()
    result = await completed(client, headers, run_id, job_id, jobs)
    assert result['alert'] is not None
    assert result['detections'][0]['case_id'] == result['alert']['id']
    assert result['detections'][0]['behaviour_types'] == ['PHONE_DETECTED']
    assert result['detections'][0]['seat_number'] == 14
    assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid', active_session) == 1


async def test_device_camera_stopped_job_cannot_save_late_evidence(client, admin_conn, active_session,
                                                                 device, jobs, monkeypatch):
    from app.services import storage
    uploaded = []
    class PrivateStorage:
        async def upload(self, *args): uploaded.append(args)
        async def delete(self, *args): pass
    monkeypatch.setattr(storage, 'get_storage', lambda: PrivateStorage())
    headers = auth(await login(client, TEACHER_EMAIL))
    run_id = (await client.post(f'/api/sessions/{active_session}/device-camera/start', headers=headers,
                                json={'seat_number': 14})).json()['run_id']
    now = service.time.monotonic()
    device.runs[run_id].histories[('PHONE_DETECTED', 1)] = [(now-4, .968), (now-2, .968)]
    original = device._infer
    entered, finish = threading.Event(), threading.Event()

    def delayed(run, data):
        entered.set()
        assert finish.wait(5)
        return original(run, data)

    monkeypatch.setattr(device, '_infer', delayed)
    job_id = await enqueue(client, headers, run_id)
    job = jobs.jobs[job_id]
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert (await client.post(f'/api/device-camera/{run_id}/stop', headers=headers)).status_code == 204
        assert job_id not in jobs.jobs and run_id not in jobs.by_run
        assert (await client.get(f'/api/device-camera/{run_id}/object-jobs/{job_id}', headers=headers)).status_code == 404
        other = auth(await login(client, STUDENT_B_EMAIL))
        other_run = (await client.post('/api/device-camera/check/start', headers=other)).json()['run_id']
        blocked = await client.post(f'/api/device-camera/{other_run}/object-jobs?frame_index=0',
                                    headers={**other, 'Content-Type': 'image/jpeg'}, content=jpeg())
        assert blocked.status_code == 429 and device.inference_lock.locked()
    finally:
        finish.set()
        await asyncio.gather(job.task, return_exceptions=True)
    assert not device.inference_lock.locked()
    assert not uploaded
    assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid', active_session) == 0


async def test_device_camera_room_job_checks_entire_roster_before_releasing_result(client, admin_conn,
                                                                                active_session, device, jobs, monkeypatch):
    headers = auth(await login(client, TEACHER_EMAIL))
    run_id = (await client.post(f'/api/sessions/{active_session}/device-camera/room/start', headers=headers,
                                json={'regions': [{'seat_number': 14, 'box': [.05, .05, .95, .95]}]})).json()['run_id']
    def infer(run, data):
        return service.decode_frame(data), None, {14: []}, [], .01, None
    monkeypatch.setattr(device, '_infer', infer)
    job_id = await enqueue(client, headers, run_id, mode='room')
    result = await completed(client, headers, run_id, job_id, jobs)
    assert result['mapped_seats'] == 1 and result['reviews'][0]['seat_number'] == 14
    await admin_conn.execute('INSERT INTO seat_assignments(session_id,seat_number,student_id,student_reg_no) SELECT $1::uuid,25,id,registration_or_employee_no FROM users WHERE email=$2',
                             active_session, STUDENT_B_EMAIL)
    response = await client.get(f'/api/device-camera/{run_id}/object-jobs/{job_id}', headers=headers)
    assert response.status_code == 409 and job_id not in jobs.jobs


async def test_device_camera_stop_during_upload_finishes_snapshot_and_cooldown_cleanup(client, admin_conn,
                                                                                    active_session, device, jobs,
                                                                                    monkeypatch):
    from app.services import storage
    from app.services.detection import cooldown_key
    from app.redis_client import get_redis
    saved = {}
    entered, release = asyncio.Event(), asyncio.Event()

    class PendingStorage:
        async def upload(self, path, data, content_type):
            # The remote write succeeded; the caller is still awaiting its
            # response. Cancelling here would strand the snapshot and claim.
            saved[path] = data
            entered.set()
            await release.wait()

        async def delete(self, paths):
            for path in paths:
                saved.pop(path, None)

    monkeypatch.setattr(storage, 'get_storage', lambda: PendingStorage())
    headers = auth(await login(client, TEACHER_EMAIL))
    run_id = (await client.post(f'/api/sessions/{active_session}/device-camera/start', headers=headers,
                                json={'seat_number': 14})).json()['run_id']
    now = service.time.monotonic()
    device.runs[run_id].histories[('PHONE_DETECTED', 1)] = [(now-4, .968), (now-2, .968)]
    job_id = await enqueue(client, headers, run_id)
    job = jobs.jobs[job_id]
    key = cooldown_key(active_session, 14)+':device:PHONE_DETECTED'
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert saved and await get_redis().get(key) is not None
        assert (await client.post(f'/api/device-camera/{run_id}/stop', headers=headers)).status_code == 204
        await asyncio.sleep(0)
        assert job_id not in jobs.jobs and not job.task.done()
        assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid', active_session) == 0
    finally:
        release.set()
        await asyncio.gather(job.task, return_exceptions=True)
    assert not saved
    assert await get_redis().get(key) is None
    assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid', active_session) == 0
    assert all(task.done() for task in jobs.tasks)


async def test_device_camera_stop_after_commit_keeps_committed_snapshot_and_cooldown(client, admin_conn,
                                                                                   active_session, device, jobs,
                                                                                   monkeypatch):
    from app.services import storage
    from app.routers import internal
    from app.services.detection import cooldown_key
    from app.redis_client import get_redis
    saved = {}
    committed, release = asyncio.Event(), asyncio.Event()

    class PrivateStorage:
        async def upload(self, path, data, content_type): saved[path] = data
        async def delete(self, paths):
            for path in paths:
                saved.pop(path, None)

    async def delayed_postcommit_delivery(*args, **kwargs):
        committed.set()
        await release.wait()

    monkeypatch.setattr(storage, 'get_storage', lambda: PrivateStorage())
    monkeypatch.setattr(internal, 'emit_detection', delayed_postcommit_delivery)
    headers = auth(await login(client, TEACHER_EMAIL))
    run_id = (await client.post(f'/api/sessions/{active_session}/device-camera/start', headers=headers,
                                json={'seat_number': 14})).json()['run_id']
    now = service.time.monotonic()
    device.runs[run_id].histories[('PHONE_DETECTED', 1)] = [(now-4, .968), (now-2, .968)]
    job_id = await enqueue(client, headers, run_id)
    job = jobs.jobs[job_id]
    key = cooldown_key(active_session, 14)+':device:PHONE_DETECTED'
    try:
        await asyncio.wait_for(committed.wait(), 5)
        path = await admin_conn.fetchval('SELECT snapshot_path FROM detection_events WHERE session_id=$1::uuid', active_session)
        claim = await get_redis().get(key)
        assert path in saved and claim is not None
        assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid', active_session) == 1
        assert (await client.post(f'/api/device-camera/{run_id}/stop', headers=headers)).status_code == 204
        await asyncio.sleep(0)
        assert job_id not in jobs.jobs and not job.task.done()
    finally:
        release.set()
        await asyncio.gather(job.task, return_exceptions=True)
    assert path in saved and await get_redis().get(key) == claim
    assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid', active_session) == 1
    assert all(task.done() for task in jobs.tasks)


@pytest.mark.parametrize('data,status', [(b'', 413), (b'invalid', 422),
                                        (b'x'*(service.MAX_IMAGE_BYTES+1), 413)],
                         ids=['empty', 'invalid', 'oversized'])
async def test_device_camera_jobs_reject_bad_uploads_before_enqueue(client, jobs, data, status):
    headers = auth(await login(client, STUDENT_A_EMAIL))
    run_id = (await client.post('/api/device-camera/check/start', headers=headers)).json()['run_id']
    response = await client.post(f'/api/device-camera/{run_id}/object-jobs?frame_index=0',
                                 headers={**headers, 'Content-Type': 'image/jpeg'}, content=data)
    assert response.status_code == status and not jobs.jobs
    for query in ['frame_index=-1', 'frame_index=2147483648', 'frame_index=0&mode=invalid']:
        invalid = await client.post(f'/api/device-camera/{run_id}/object-jobs?{query}',
                                    headers={**headers, 'Content-Type': 'image/jpeg'}, content=jpeg())
        assert invalid.status_code == 422 and not jobs.jobs


async def test_object_jobs_expiry_stops_camera_and_forgets_pending_private_work():
    jobs = ObjectJobs(idle_seconds=.02)
    run = SimpleNamespace(run_id='isolated-run', owner_id='owner', frame_index=-1, stopped=False)
    gate = asyncio.Event()
    async def work():
        await gate.wait()
        return {'objects': ['private result']}
    task = jobs.submit(run, 0, work, lambda: setattr(run, 'stopped', True)).task
    await asyncio.sleep(.05)
    assert run.stopped and not jobs.jobs and not jobs.by_run
    # Expiry revokes delivery immediately, but cleanup still owns its slot.
    assert not task.done()
    other = SimpleNamespace(run_id='next', owner_id='owner', frame_index=-1, stopped=False)
    with pytest.raises(HTTPException) as error:
        jobs.ensure_available(other, 0)
    assert error.value.status_code == 429
    gate.set()
    await asyncio.gather(task, return_exceptions=True)
    assert task.done()
    await jobs.close()


async def test_object_jobs_completed_retention_is_bounded():
    jobs = ObjectJobs(max_jobs=1)
    run = SimpleNamespace(run_id='one', owner_id='owner', frame_index=-1, stopped=False)
    other = SimpleNamespace(run_id='two', owner_id='other', frame_index=-1, stopped=False)
    async def work(): return {'objects': []}
    job = jobs.submit(run, 0, work, lambda: setattr(run, 'stopped', True))
    await job.task
    with pytest.raises(HTTPException) as error:
        jobs.submit(other, 0, work, lambda: setattr(other, 'stopped', True))
    assert error.value.status_code == 429 and len(jobs.jobs) == 1
    await jobs.close()
