"""Local website integration tests, using a disposable SQLite DB and fake camera.

No Supabase/Postgres/Redis tests or tables are touched. Real detector behaviour
is covered separately; these tests verify routing, policy, storage and delivery.
"""
import importlib.util
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.object_monitor import ObjectMonitor
from phone_detector import BOOK, PHONE, DetectionEvent
from head_pose_detector import HEAD


class HeadRuntime:
    signal = None
    calibrated = False
    closed = False

    def begin_calibration(self):
        self.calibrated=True

    def process_frame(self,frame,timestamp):
        return self.signal

    def status(self):
        return dict(state='neutral',calibrated=self.calibrated,calibrating=False)

    def annotate_frame(self,frame):
        return frame

    def close(self):
        self.closed=True


class Camera:
    def __init__(self):
        self.released = False

    def read(self):
        time.sleep(.02)
        return True, np.full((72,128,3), 90, np.uint8)

    def release(self):
        self.released = True


class Runtime:
    error = None
    ready = True
    last_inference_seconds = .02
    _tracks = []
    _min_semantic_hits = 2
    checking_labels = []

    def __init__(self, signals):
        self.signals = signals
        self.closed = False

    def update(self, frame, timestamp):
        return [DetectionEvent(s,.85,time.time(),(20,10,60,60),
                               'phone' if s==PHONE else 'book',i+1)
                for i,s in enumerate(self.signals)]

    def annotate_frame(self, frame):
        annotated = frame.copy()
        cv2.rectangle(annotated,(20,10),(60,60),(0,0,255),2)
        return annotated

    def close(self):
        self.closed = True


@pytest.fixture
def demo(tmp_path,monkeypatch):
    monkeypatch.setenv('PROCTORAI_DEMO_DATABASE_URL', 'sqlite:///'+(tmp_path/'web.db').as_posix())
    name = 'backend.web_test_'+uuid4().hex
    spec = importlib.util.spec_from_file_location(name,ROOT/'backend/main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.sio.emit = AsyncMock()
    camera, runtime = Camera(), Runtime([PHONE,BOOK])
    head=HeadRuntime()
    module.test_head=head
    module.monitor = ObjectMonitor(module.camera_alert_sink, camera=lambda:camera, runtime=lambda:runtime,head=lambda:head)
    with TestClient(module.app) as client:
        yield module,client,camera,runtime
    module.engine.dispose()


def wait_for(predicate,timeout=5):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():
            return
        time.sleep(.04)
    pytest.fail('Timed out waiting for the bridge.')


@pytest.mark.parametrize('signals,kind,score',[
    ([PHONE],PHONE,.9),([BOOK],BOOK,.75),([PHONE,BOOK],PHONE+'+'+BOOK,.9),
])
def test_confirmed_objects_create_saved_cases_and_socket_updates(demo,signals,kind,score):
    module,client,camera,runtime = demo
    runtime.signals = signals
    response = client.post('/object-monitor/start')
    assert response.status_code==202
    session_id = response.json()['session_id']
    # Smoothing must cover real time: opening the camera cannot instantly alert.
    time.sleep(.25)
    assert client.get('/cases').json()==[]
    wait_for(lambda:len(client.get('/cases').json())==1)
    cases = client.get('/cases').json()
    assert cases[0]['type']==kind and cases[0]['confidence']==score
    assert cases[0]['status']=='pending'
    with module.SessionLocal() as db:
        assert db.query(module.DetectionModel).one().session_id==session_id
    module.sio.emit.assert_any_await('case_created',{
        **cases[0], 'status':'pending',
    })
    time.sleep(.25)
    assert len(client.get('/cases').json())==1  # sustained presence is throttled
    stopped=client.post('/object-monitor/stop')
    assert stopped.status_code==200 and not stopped.json()['running']
    assert camera.released and runtime.closed
    assert module.test_head.closed
    assert module.monitor.latest_frame()[1] is None


def test_start_is_idempotent_and_stopped_feed_is_rejected(demo):
    module,client,_,_ = demo
    a=client.post('/object-monitor/start').json()
    b=client.post('/object-monitor/start').json()
    assert a['session_id']==b['session_id'] and a['run_id']==b['run_id']
    with module.SessionLocal() as db:
        assert db.query(module.SessionModel).count()==1
    assert client.get('/object-monitor/feed',params={'run_id':a['run_id']+1}).status_code==409
    client.post('/object-monitor/stop')
    assert client.get('/object-monitor/feed',params={'run_id':a['run_id']}).status_code==409


def test_empty_frames_do_not_open_cases(demo):
    _,client,_,runtime=demo
    runtime.signals=[]
    client.post('/object-monitor/start')
    time.sleep(.3)
    assert client.get('/cases').json()==[]
    status=client.get('/object-monitor/status').json()
    assert status['objects']==[] and status['phase']=='ready'


def test_model_failure_releases_camera_and_is_visible_to_website(demo):
    _,client,camera,runtime=demo
    runtime.error='Model is missing; prepare the local model.'
    client.post('/object-monitor/start')
    wait_for(lambda:client.get('/object-monitor/status').json()['phase']=='error')
    status=client.get('/object-monitor/status').json()
    assert 'Model is missing' in status['error'] and not status['running']
    assert camera.released and runtime.closed


def test_case_review_returns_saved_status_and_missing_case_error(demo):
    _,client,_,_=demo
    response=client.post('/detection-event',json={'type':PHONE,'confidence':.9})
    assert response.status_code==200
    case=client.get('/cases').json()[0]
    assert client.post(f'/cases/{case["id"]}/confirm').status_code==200
    assert client.get('/cases').json()[0]['status']=='confirmed'
    assert client.post('/cases/999999/dismiss').status_code==404


def test_head_calibration_requires_running_camera_and_updates_status(demo):
    module,client,_,_=demo
    assert client.post('/object-monitor/head-pose/calibrate').status_code==409
    client.post('/object-monitor/start')
    wait_for(lambda:client.get('/object-monitor/status').json()['head_pose'] is not None)
    assert client.post('/object-monitor/head-pose/calibrate').status_code==202
    wait_for(lambda:client.get('/object-monitor/status').json()['head_pose']['calibrated'])
    assert module.test_head.calibrated
    client.post('/object-monitor/stop')
    assert client.get('/object-monitor/status').json()['head_pose'] is None


def test_head_signal_keeps_existing_weight_and_combines_with_phone(demo):
    module,client,_,runtime=demo
    runtime.signals=[]
    module.test_head.signal=DetectionEvent(HEAD,.65,time.time(),(0,0,1,1),'head',1)
    client.post('/object-monitor/start')
    time.sleep(3.2)
    assert client.get('/cases').json()==[]  # head alone remains below .75 policy
    runtime.signals=[PHONE]
    wait_for(lambda:len(client.get('/cases').json())==1)
    case=client.get('/cases').json()[0]
    assert case['type']==HEAD+'+'+PHONE and case['confidence']==.9
