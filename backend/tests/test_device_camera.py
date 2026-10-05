"""Browser capture permissions, bounded uploads, attribution and server-only scoring."""
import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.services import device_camera as service
from app.services.detection import DetectionConfig
from tests.helpers import (ADMIN_EMAIL, CONTROLLER_EMAIL, HOD_EMAIL, TEACHER_EMAIL,
                           STUDENT_A_EMAIL, STUDENT_B_EMAIL, auth, login)
from tests.test_detection_pipeline import active_session, live_server, session_cookie  # noqa: F401


def jpeg():
    import cv2
    import numpy as np
    return cv2.imencode('.jpg', np.full((360, 640, 3), 100, np.uint8))[1].tobytes()


@pytest.fixture
def device(monkeypatch):
    manager = service.DeviceCameraService()
    monkeypatch.setattr(service, 'device_camera', manager)
    from app.routers import device_camera
    monkeypatch.setattr(device_camera, 'device_camera', manager)
    def infer(run, data):
        frame = service.decode_frame(data)
        event = SimpleNamespace(type='PHONE_DETECTED', confidence=.92, track_id=1)
        run.detector = SimpleNamespace(annotate_frame=lambda image: image)
        return frame, [event], [dict(label='phone', type=event.type, confidence=.92, track_id=1, confirmed=True, box=[.2,.2,.4,.5])], .01
    monkeypatch.setattr(manager, '_infer', infer)
    return manager


async def test_exam_capture_only_assigned_teacher_and_registered_seat(client, active_session, device):
    path=f'/api/sessions/{active_session}/device-camera/start'
    assert (await client.post(path, json={'seat_number':14})).status_code==401
    for email in [ADMIN_EMAIL, CONTROLLER_EMAIL, HOD_EMAIL, STUDENT_A_EMAIL]:
        assert (await client.post(path,headers=auth(await login(client,email)),json={'seat_number':14})).status_code==403
    teacher=auth(await login(client,TEACHER_EMAIL))
    assert (await client.post(path,headers=teacher,json={'seat_number':999})).status_code==409
    response=await client.post(path,headers=teacher,json={'seat_number':14})
    assert response.status_code==201
    run=device.runs[response.json()['run_id']]
    assert run.session_id==active_session and run.student_id is not None
    assert (await client.post(path,headers=teacher,json={'seat_number':14})).status_code==409


async def test_personal_check_available_to_signed_in_roles_and_never_creates_cases(client,admin_conn,device):
    before=await admin_conn.fetchval('SELECT count(*) FROM cases')
    for email in [ADMIN_EMAIL,CONTROLLER_EMAIL,HOD_EMAIL,TEACHER_EMAIL,STUDENT_A_EMAIL]:
        headers=auth(await login(client,email))
        started=await client.post('/api/device-camera/check/start',headers=headers)
        assert started.status_code==201
        run=started.json()['run_id']
        result=await client.post(f'/api/device-camera/{run}/frame?frame_index=0&head_sustained=true',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
        assert result.status_code==200 and result.json()['objects'][0]['label']=='phone'
        assert result.json()['alert'] is None
        assert (await client.post(f'/api/device-camera/{run}/stop',headers=headers)).status_code==204
    assert await admin_conn.fetchval('SELECT count(*) FROM cases')==before


async def test_run_cannot_be_read_or_stopped_by_another_account(client,device):
    owner=auth(await login(client,STUDENT_A_EMAIL));other=auth(await login(client,STUDENT_B_EMAIL))
    run=(await client.post('/api/device-camera/check/start',headers=owner)).json()['run_id']
    for action in ['frame?frame_index=0','stop']:
        assert (await client.post(f'/api/device-camera/{run}/{action}',headers=other,content=jpeg())).status_code==404


async def test_bounded_uploads_no_client_scores_and_no_replayed_frames(client,device):
    headers=auth(await login(client,TEACHER_EMAIL))
    run=(await client.post('/api/device-camera/check/start',headers=headers)).json()['run_id']
    path=f'/api/device-camera/{run}/frame?frame_index=0'
    assert (await client.post(path,headers=headers,json={'scores':{'PHONE_DETECTED':1}})).status_code==415
    headers={**headers,'Content-Type':'image/jpeg'}
    assert (await client.post(path,headers=headers,content=b'x'*(service.MAX_IMAGE_BYTES+1))).status_code==413
    assert (await client.post(path,headers=headers,content=jpeg())).status_code==200
    assert (await client.post(path,headers=headers,content=jpeg())).status_code==409


async def test_changed_student_or_ended_exam_stops_evidence_capture(client,admin_conn,active_session,device):
    headers=auth(await login(client,TEACHER_EMAIL))
    run=(await client.post(f'/api/sessions/{active_session}/device-camera/start',headers=headers,json={'seat_number':14})).json()['run_id']
    await admin_conn.execute('UPDATE seat_assignments SET student_id=(SELECT id FROM users WHERE email=$1) WHERE session_id=$2::uuid AND seat_number=14',STUDENT_B_EMAIL,active_session)
    response=await client.post(f'/api/device-camera/{run}/frame?frame_index=0',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
    assert response.status_code==409
    assert await admin_conn.fetchval('SELECT count(*) FROM detection_events')==0


async def test_checked_objects_enter_existing_case_workflow_with_private_snapshot(client,admin_conn,active_session,device,monkeypatch):
    from app.services import storage
    saved={}
    class PrivateStorage:
        async def upload(self,path,data,content_type): saved[path]=data
        async def delete(self,paths):
            for path in paths:saved.pop(path,None)
    monkeypatch.setattr(storage,'get_storage',lambda:PrivateStorage())
    headers={**auth(await login(client,TEACHER_EMAIL)),'Content-Type':'image/jpeg'}
    run=(await client.post(f'/api/sessions/{active_session}/device-camera/start',headers=auth(await login(client,TEACHER_EMAIL)),json={'seat_number':14})).json()['run_id']
    last=None
    for i in range(3):
        last=await client.post(f'/api/device-camera/{run}/frame?frame_index={i}&head_sustained=true',headers=headers,content=jpeg())
        assert last.status_code==200,last.text
        if i<2:await asyncio.sleep(1.6)
    assert last.json()['alert'] is not None,last.text
    row=await admin_conn.fetchrow('SELECT * FROM detection_events WHERE session_id=$1::uuid',active_session)
    assert row['seat_number']==14 and row['snapshot_path'] in saved
    # A browser boolean cannot fabricate a head-pose alert.
    assert set(row['behaviour_types'])=={'PHONE_DETECTED'}
    assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid',active_session)==1


def test_temporal_policy_does_not_bridge_missing_objects_or_sparse_samples():
    run=service.DeviceRun(str(uuid.uuid4()));config=DetectionConfig()
    event=SimpleNamespace(type='PHONE_DETECTED',confidence=.92,track_id=1)
    assert run.observe([event],0,config) is None
    assert run.observe([event],1.5,config) is None
    assert run.observe([event],3,config)=={'PHONE_DETECTED':service.object_signal_score(event.type,event.confidence)}
    assert run.observe([],3.1,config) is None
    assert run.observe([event],5,config) is None
    assert run.observe([event],36,config) is None


@pytest.mark.parametrize('signal,confidence', [('PHONE_DETECTED',.51),('UNAUTHORISED_OBJECT',.61)])
def test_visible_recognition_triggers_with_slow_hosted_samples(signal,confidence):
    run=service.DeviceRun('teacher');config=DetectionConfig()
    event=SimpleNamespace(type=signal,confidence=confidence,track_id=1)
    assert run.observe([event],0,config) is None
    assert run.observe([event],15,config) is None
    assert run.observe([event],30,config)[signal]>=.8
    assert event.confidence==confidence  # overlay probability stays unmodified
    from app.models import BehaviourType
    strict=DetectionConfig(thresholds={**config.thresholds,BehaviourType(signal):.95})
    assert run.observe([event],31,strict) is None


def test_stricter_live_policy_cannot_reuse_older_low_scores():
    from app.models import BehaviourType
    run=service.DeviceRun('teacher');config=DetectionConfig()
    event=SimpleNamespace(type='PHONE_DETECTED',confidence=.51,track_id=1)
    run.observe([event],0,config);run.observe([event],15,config)
    strict=DetectionConfig(thresholds={**config.thresholds,BehaviourType.PHONE_DETECTED:.95})
    event.confidence=.99
    assert run.observe([event],30,strict) is None
    assert len(run.histories[('PHONE_DETECTED',1)])==1


@pytest.mark.parametrize('yaw,pitch', [(40,0),(-40,0),(0,-28)])
async def test_image_verified_head_alone_creates_private_review_alert(client,admin_conn,active_session,device,monkeypatch,yaw,pitch):
    import math
    import numpy as np
    from app.vision.head_pose import HeadPoseDetector, FaceObservation
    from app.services import storage
    from app.models import BehaviourType
    saved={}
    class PrivateStorage:
        async def upload(self,path,data,content_type):saved[path]=data
        async def delete(self,paths):
            for path in paths:saved.pop(path,None)
    monkeypatch.setattr(storage,'get_storage',lambda:PrivateStorage())
    headers=auth(await login(client,TEACHER_EMAIL))
    run_id=(await client.post(f'/api/sessions/{active_session}/device-camera/start',headers=headers,json={'seat_number':14})).json()['run_id']
    run=device.runs[run_id]
    class Source:
        rotation=np.eye(3)
        def estimate(self,frame,timestamp):return FaceObservation(self.rotation,(150,80,350,280))
        def close(self):pass
    source=Source()
    run.head=HeadPoseDetector(source=source,max_gap=2.,reference_loss_seconds=4.)
    process=run.head.process_frame
    # Known rotations exercise real calibration/filtering/persistence, without
    # pretending synthetic matrices establish camera model accuracy.
    tick=iter(np.arange(0,20,.35))
    monkeypatch.setattr(run.head,'process_frame',lambda image:process(image,timestamp=next(tick)))
    assert (await client.post(f'/api/device-camera/{run_id}/head/calibrate',headers=headers)).status_code==204
    async def sample(index):
        response=await client.post(f'/api/device-camera/{run_id}/head/frame?frame_index={index}',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
        assert response.status_code==200,response.text
        return response.json()
    for index in range(8):
        result=await sample(index)
        assert result['alert'] is None
    assert result['head']['calibrated']
    y,p=math.radians(yaw),math.radians(-pitch)
    source.rotation=np.array([[math.cos(y),0,math.sin(y)],[0,1,0],[-math.sin(y),0,math.cos(y)]]) @ np.array([[1,0,0],[0,math.cos(p),-math.sin(p)],[0,math.sin(p),math.cos(p)]])
    alerts=[]
    for index in range(8,19):
        result=await sample(index)
        if result['alert']:alerts.append(result['alert'])
    assert result['head']['sustained'] and len(alerts)==1
    case=alerts[0]
    row=await admin_conn.fetchrow('SELECT * FROM detection_events WHERE session_id=$1::uuid',active_session)
    assert row['snapshot_path'] in saved and list(row['behaviour_types'])==['HEAD_POSE_VIOLATION']
    assert case['status']=='pending_review'
    assert (await client.get(f"/api/cases/{case['id']}",headers=auth(await login(client,STUDENT_B_EMAIL)))).status_code==404
    # A head warning does not consume the phone warning's cooldown.
    events=[SimpleNamespace(type='PHONE_DETECTED',confidence=.51,track_id=1)]
    for now in [0,15,30]:scores=run.observe(events,now,DetectionConfig())
    run.detector=SimpleNamespace(annotate_frame=lambda image:image)
    from app.db import acquire_connection
    async with acquire_connection() as conn:
        second=await device.persist(run,service.decode_frame(jpeg()),scores,DetectionConfig(),conn)
    assert second is not None and second.id!=case['id']
    assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid',active_session)==2


async def test_phone_alert_delivered_over_hosted_polling_to_authorized_roles(client,admin_conn,active_session,device,live_server,monkeypatch):
    import socketio
    from app import sockets
    from app.services import storage
    class PrivateStorage:
        async def upload(self,*args):pass
        async def delete(self,*args):pass
    monkeypatch.setattr(storage,'get_storage',lambda:PrivateStorage())
    connections=[]; received={}
    try:
        for email in [TEACHER_EMAIL,HOD_EMAIL,ADMIN_EMAIL,CONTROLLER_EMAIL,STUDENT_A_EMAIL]:
            socket=socketio.AsyncClient();connections.append(socket)
            received[email]=asyncio.Queue()
            socket.on('alert:new',received[email].put)
            await socket.connect(live_server,headers=session_cookie(await login(client,email)),transports=['polling'])
            reply=await socket.call('join_session',{'session_id':active_session})
            assert reply['ok']==(email in [TEACHER_EMAIL,HOD_EMAIL])
        headers=auth(await login(client,TEACHER_EMAIL))
        run=(await client.post(f'/api/sessions/{active_session}/device-camera/start',headers=headers,json={'seat_number':14})).json()['run_id']
        # Time the real temporal guard without sleeping or mocking persistence.
        target=device.runs[run]
        target.histories[('PHONE_DETECTED',1)]=[(service.time.monotonic()-3.2,.968),(service.time.monotonic()-1.6,.968)]
        result=await client.post(f'/api/device-camera/{run}/frame?frame_index=0',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
        assert result.status_code==200 and result.json()['alert'],result.text
        for email in [TEACHER_EMAIL,HOD_EMAIL]:
            event=await asyncio.wait_for(received[email].get(),5)
            assert event['case_id']==result.json()['alert']['id']
        for email in [ADMIN_EMAIL,CONTROLLER_EMAIL,STUDENT_A_EMAIL]:assert received[email].empty()
    finally:
        for socket in connections:
            if socket.connected:await socket.disconnect()


async def test_unavailable_storage_reports_failure_and_releases_retry_cooldown(client,admin_conn,active_session,device,monkeypatch):
    from app.services import storage
    from app.services.detection import cooldown_key
    from app.redis_client import get_redis
    headers=auth(await login(client,TEACHER_EMAIL))
    run_id=(await client.post(f'/api/sessions/{active_session}/device-camera/start',headers=headers,json={'seat_number':14})).json()['run_id']
    run=device.runs[run_id]
    run.histories[('PHONE_DETECTED',1)]=[(service.time.monotonic()-4,.968),(service.time.monotonic()-2,.968)]
    def unavailable():raise storage.StorageNotConfiguredError('Fixture storage unavailable')
    monkeypatch.setattr(storage,'get_storage',unavailable)
    result=await client.post(f'/api/device-camera/{run_id}/frame?frame_index=0',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
    assert result.status_code==200
    assert result.json()['alert'] is None and 'could not be saved' in result.json()['alert_error']
    assert await get_redis().get(cooldown_key(active_session,14)+':device:PHONE_DETECTED') is None
    assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid',active_session)==0


@pytest.mark.parametrize('data',[b'',b'not an image',b'x'*(service.MAX_IMAGE_BYTES+1)],ids=['empty','invalid','oversized'])
def test_image_decoder_rejects_invalid_or_oversized_samples(data):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):service.decode_frame(data)
