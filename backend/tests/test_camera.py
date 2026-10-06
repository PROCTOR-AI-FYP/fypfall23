"""Camera authorization, real seat attribution, local evidence and case workflow."""
import time
import uuid

import pytest
import pytest_asyncio

from app.models import BehaviourType
from app.services import camera
from app.services.detection import DetectionConfig
from tests.helpers import (ADMIN_EMAIL,CONTROLLER_EMAIL,HOD_EMAIL,TEACHER_EMAIL,
                           STUDENT_A_EMAIL,STUDENT_B_EMAIL,auth,login)
from tests.test_detection_pipeline import active_session  # noqa: F401


class FakeMonitor:
    def __init__(self,sink,**kwargs):
        self.sink=sink
        self.state={'running':False,'session_id':None,'head_pose':None,'head_error':None}
    def start(self,session,loop): self.state.update(running=True,session_id=session,phase='ready',run_id=1)
    def status(self): return dict(self.state)
    def stop(self):
        self.state.update(running=False,head_pose=None,phase='stopped')
        return self.status()
    def calibrate_head(self): self.state['head_pose']={'state':'calibrating'}


@pytest_asyncio.fixture
async def fake_camera(monkeypatch,tmp_path):
    monkeypatch.setattr(camera.platform_camera,'monitor_factory',FakeMonitor)
    monkeypatch.setattr(camera,'EVIDENCE_ROOT',tmp_path)
    yield camera.platform_camera
    await camera.platform_camera.stop()
    camera.platform_camera.monitor=None


async def test_camera_requires_assigned_invigilator_and_registered_seat(client,active_session,fake_camera):
    base=f'/api/sessions/{active_session}/camera'
    assert (await client.post(base+'/start',json={'seat_number':14})).status_code==401
    for email in (ADMIN_EMAIL,HOD_EMAIL,CONTROLLER_EMAIL,STUDENT_A_EMAIL):
        assert (await client.post(base+'/start',headers=auth(await login(client,email)),json={'seat_number':14})).status_code==403
    teacher=auth(await login(client,TEACHER_EMAIL))
    assert (await client.post(base+'/start',headers=teacher,json={'seat_number':13})).status_code==409
    assert (await client.post(base+'/start',headers=teacher,json={'seat_number':14})).status_code==202
    assert (await client.post(base+'/calibrate',headers=teacher)).json()['head_pose']['state']=='calibrating'
    assert (await client.post(base+'/stop',headers=teacher)).json()['running'] is False
    assert (await client.post(base+'/calibrate',headers=teacher)).status_code==409


async def test_camera_cannot_start_completed_exam(client,fake_camera):
    teacher=auth(await login(client,TEACHER_EMAIL))
    response=await client.post('/api/sessions/00000000-0000-0000-0000-000000000001/camera/start',headers=teacher,json={'seat_number':14})
    assert response.status_code==409


def test_configured_camera_scorer_supports_head_alone_and_stable_objects():
    scorer=camera.CameraScorer(DetectionConfig())
    for i in range(40):
        head=scorer.update_scores({'HEAD_POSE_VIOLATION':.65},i*.1)
        assert head.per_signal=={'HEAD_POSE_VIOLATION':.85}
    found=None
    for i in range(40,80):
        found=scorer.update_scores({'HEAD_POSE_VIOLATION':.65,'PHONE_DETECTED':.92},i*.1)
    assert found is not None and found.score==pytest.approx(.968)
    assert set(found.active_signals)=={'PHONE_DETECTED','HEAD_POSE_VIOLATION'}
    assert scorer.update_scores({},8) is None


def test_admin_sensitivity_controls_camera_scoring():
    config=DetectionConfig()
    config.thresholds[BehaviourType.PHONE_DETECTED]=.98
    scorer=camera.CameraScorer(config)
    for i in range(40): assert scorer.update_scores({'PHONE_DETECTED':.92},i*.1) is None


def test_local_camera_cannot_promote_unverified_objects_or_disabled_head():
    config=DetectionConfig()
    config.thresholds[BehaviourType.PHONE_DETECTED]=0
    config.thresholds[BehaviourType.UNAUTHORISED_OBJECT]=0
    config.thresholds[BehaviourType.HEAD_POSE_VIOLATION]=.9
    scorer=camera.CameraScorer(config)
    for i in range(40):
        assert scorer.update_scores({'PHONE_DETECTED':.49,'UNAUTHORISED_OBJECT':.59,
                                     'HEAD_POSE_VIOLATION':.65},i*.1) is None


def test_local_camera_confirmation_is_not_diluted_and_resets_on_interruption():
    scorer=camera.CameraScorer(DetectionConfig())
    found=None
    for i in range(32):
        # 75% present: absence governs persistence, not verified strength.
        found=scorer.update_scores({'PHONE_DETECTED':.51} if i%4 else {},i*.1)
    assert found.per_signal=={'PHONE_DETECTED':.804}
    assert scorer.update_scores({'PHONE_DETECTED':.51},4) is None
    assert scorer.update_scores({'PHONE_DETECTED':.51},4) is None
    assert scorer.update_scores({'PHONE_DETECTED':.51},3.9) is None


def test_local_camera_weights_apply_to_head_and_object_together():
    config=DetectionConfig(weights={BehaviourType.HEAD_POSE_VIOLATION:1,
                                    BehaviourType.PHONE_DETECTED:3})
    scorer=camera.CameraScorer(config)
    for i in range(32):
        found=scorer.update_scores({'PHONE_DETECTED':.5,'HEAD_POSE_VIOLATION':.65},i*.1)
    assert found.score==.813
    scorer.config=DetectionConfig(weights={BehaviourType.HEAD_POSE_VIOLATION:0,
                                         BehaviourType.PHONE_DETECTED:0})
    assert scorer.update_scores({'PHONE_DETECTED':.5,'HEAD_POSE_VIOLATION':.65},3.2) is None


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-.1,1.1])
def test_local_camera_rejects_invalid_model_scores(value):
    with pytest.raises(ValueError):
        camera.CameraScorer(DetectionConfig()).update_scores({'PHONE_DETECTED':value},0)


@pytest.mark.parametrize('value',[float('nan'),float('inf')])
def test_local_camera_rejects_invalid_timestamps(value):
    with pytest.raises(ValueError):
        camera.CameraScorer(DetectionConfig()).update_scores({},value)


async def test_camera_evidence_enters_real_case_hierarchy(client,admin_conn,active_session,fake_camera):
    teacher=auth(await login(client,TEACHER_EMAIL))
    hod=auth(await login(client,HOD_EMAIL))
    student=auth(await login(client,STUDENT_A_EMAIL))
    other_student=auth(await login(client,STUDENT_B_EMAIL))
    student_id=str(await admin_conn.fetchval('SELECT id FROM users WHERE email=$1',STUDENT_A_EMAIL))
    case=await fake_camera.persist({'session_id':active_session,'timestamp':time.time(),'confidence':.92,
                                   'per_signal':{'PHONE_DETECTED':.92,'HEAD_POSE_VIOLATION':.65},'snapshot':b'local test evidence'},14,student_id)
    case_id=case['id']
    detail=(await client.get(f'/api/cases/{case_id}',headers=student)).json()
    assert detail['student_id']==student_id and detail['seat_number']==14
    assert detail['per_signal']=={'PHONE_DETECTED':.92,'HEAD_POSE_VIOLATION':.65}
    assert (await client.get(f'/api/cases/{case_id}',headers=other_student)).status_code==404
    detection_id=str(await admin_conn.fetchval('SELECT detection_event_id FROM cases WHERE id=$1::uuid',case_id))
    image=f'/api/detections/{detection_id}/snapshot'
    assert (await client.get(image,headers=student)).status_code==403
    assert (await client.get(image,headers=teacher)).content==b'local test evidence'
    assert (await client.get(image,headers=hod)).status_code==200
    media=(await client.get(f'/api/detections/{detection_id}/media',headers=teacher)).json()
    assert media['clip_status']=='snapshot_only'
    assert media['snapshot_url']==image
    assert (await client.post(f'/api/detections/{detection_id}/confirm',headers=teacher,json={'teacher_note':'Reviewed exam evidence'})).status_code==200
    assert (await client.post(f'/api/cases/{case_id}/transitions',headers=hod,json={'to_status':'confirmed'})).status_code==200
    assert (await client.post(f'/api/cases/{case_id}/penalty',headers=hod,json={'penalty_type':'formal_warning','description':'Fixture review outcome'})).status_code==201
    notice=await client.get(f'/api/cases/{case_id}/notice',headers=student)
    assert notice.status_code==200 and 'Fixture review outcome' in notice.text
    assert notice.headers['content-disposition'].endswith('.txt"')
    assert (await client.get(f'/api/cases/{case_id}/notice',headers=other_student)).status_code==404
    assert (await client.get(f'/api/cases/{case_id}/notice')).status_code==401
    appeal=await client.post(f'/api/cases/{case_id}/appeals',headers=student,json={'statement':'Fixture appeal for independent review'})
    assert appeal.status_code==201,appeal.text
    resolution=await client.post(f"/api/appeals/{appeal.json()['id']}/resolve",headers=hod,json={'status':'accepted','review_note':'Fixture appeal accepted after review'})
    assert resolution.status_code==200
    assert (await client.get(f'/api/cases/{case_id}',headers=student)).json()['status']=='dismissed'
    assert (await client.get(f'/api/cases/{case_id}',headers=student)).json()['penalty']['revoked_at'] is not None
    assert (await client.get(f'/api/cases/{case_id}/notice',headers=student)).status_code==409


async def test_reassigned_seat_cannot_receive_previous_students_alert(client,admin_conn,active_session,fake_camera):
    old_student=str(await admin_conn.fetchval('SELECT id FROM users WHERE email=$1',STUDENT_A_EMAIL))
    await admin_conn.execute('UPDATE seat_assignments SET student_id=(SELECT id FROM users WHERE email=$1) WHERE session_id=$2::uuid AND seat_number=14',STUDENT_B_EMAIL,active_session)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as failure:
        await fake_camera.persist({'session_id':active_session,'timestamp':time.time(),'confidence':.92,
            'per_signal':{'PHONE_DETECTED':.92},'snapshot':b'previous student'},14,old_student)
    assert failure.value.status_code==409
    assert await admin_conn.fetchval('SELECT count(*) FROM detection_events WHERE session_id=$1::uuid',active_session)==0
    assert not list(camera.EVIDENCE_ROOT.rglob('*.jpg'))


async def test_camera_emits_alert_only_after_case_commit(client,admin_conn,active_session,fake_camera,monkeypatch):
    from app.routers import internal
    seen=[]
    async def observer(session_id,invigilator_id,payload):
        seen.append(await admin_conn.fetchval('SELECT count(*) FROM cases WHERE id=$1::uuid',payload['case_id']))
    monkeypatch.setattr(internal,'emit_detection',observer)
    student_id=str(await admin_conn.fetchval('SELECT id FROM users WHERE email=$1',STUDENT_A_EMAIL))
    await fake_camera.persist({'session_id':active_session,'timestamp':time.time(),'confidence':.92,
        'per_signal':{'PHONE_DETECTED':.92},'snapshot':b'committed evidence'},14,student_id)
    assert seen==[1]


async def test_local_camera_preserves_case_when_live_invalidation_fails(client,admin_conn,active_session,fake_camera,monkeypatch):
    from app import sockets
    async def fail(): raise RuntimeError('test socket outage')
    monkeypatch.setattr(sockets,'emit_sync',fail)
    student_id=str(await admin_conn.fetchval('SELECT id FROM users WHERE email=$1',STUDENT_A_EMAIL))
    case=await fake_camera.persist({'session_id':active_session,'timestamp':time.time(),'confidence':.85,
        'per_signal':{'HEAD_POSE_VIOLATION':.85},'snapshot':b'committed head evidence'},14,student_id)
    assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE id=$1::uuid',case['id'])==1
    assert len(list(camera.EVIDENCE_ROOT.rglob('*.jpg')))==1


@pytest.mark.parametrize('path',['snapshots/../local-test.jpg',f'snapshots/{uuid.uuid4()}/../escape.jpg','snapshots/not-a-uuid/local-x.jpg'])
def test_local_evidence_rejects_path_traversal(path):
    assert camera.local_snapshot_path(path) is None
