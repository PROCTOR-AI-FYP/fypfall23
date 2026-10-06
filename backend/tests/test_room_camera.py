"""Room attribution, independent head states, roster changes, and role gates."""
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from app.models import BehaviourType as B
from app.services.device_camera import DeviceRun
from app.services.room_camera import CameraRegion, RoomStart, RoomState, assign_box
from app.vision.head_pose import FaceObservation
from tests.helpers import STUDENT_A_EMAIL, STUDENT_B_EMAIL, TEACHER_EMAIL, HOD_EMAIL, auth, login
from tests.test_device_camera import device, jpeg  # noqa: F401
from tests.test_detection_pipeline import active_session  # noqa: F401

REGIONS=[{'seat_number':14,'box':[0,0,.48,1]}, {'seat_number':25,'box':[.52,0,1,1]}]


@pytest.mark.parametrize('regions',[
    [{'seat_number':14,'box':[0,0,.7,1]},{'seat_number':25,'box':[.5,0,1,1]}],
    [REGIONS[0],REGIONS[0]],
    [{'seat_number':14,'box':[0,0,float('nan'),1]}],
    [{'seat_number':14,'box':[0,0,1.1,1]}],
    [{'seat_number':14,'box':[.5,0,.4,1]}],
    [{'seat_number':14,'box':[0,0,.001,1]}],
])
def test_unsafe_camera_regions_are_rejected(regions):
    with pytest.raises(ValidationError):RoomStart(regions=regions)


def test_objects_on_boundaries_or_outside_seats_are_not_assigned():
    regions=RoomStart(regions=REGIONS).regions
    assert assign_box([.1,.2,.25,.4],regions)==14
    assert assign_box([.7,.2,.85,.4],regions)==25
    assert assign_box([.4,.2,.6,.4],regions) is None
    assert assign_box([.485,.2,.515,.4],regions) is None
    assert assign_box([.1,.2,.1,.4],regions) is None
    assert assign_box([float('nan'),.2,.3,.4],regions) is None


def rotation(yaw):
    y=math.radians(yaw)
    return np.array([[math.cos(y),0,math.sin(y)],[0,1,0],[-math.sin(y),0,math.cos(y)]])


def test_room_head_ordering_is_not_identity_and_seats_have_independent_calibration():
    run=DeviceRun('teacher','exam');room=RoomState.create(run,RoomStart(regions=REGIONS).regions,{14:'A',25:'B'})
    source=SimpleNamespace(estimate_all=lambda frame,now:observations,close=lambda:None)
    room.source=source;frame=np.zeros((360,640,3),np.uint8)
    observations=[FaceObservation(np.eye(3),(60,70,200,250)),FaceObservation(np.eye(3),(420,70,560,250))]
    for i in range(10):
        if i%2:observations.reverse()
        states=room.heads(frame,Path('unused'),calibrate=i==0,now=i*.3)
    assert all(s['calibrated'] and not s['sustained'] for s in states)
    observations=[FaceObservation(np.eye(3),(420,70,560,250)),FaceObservation(rotation(42),(60,70,200,250))]
    for i in range(10,22):states=room.heads(frame,Path('unused'),now=i*.3)
    by_seat={s['seat_number']:s for s in states}
    assert by_seat[14]['sustained'] and not by_seat[25]['sustained']
    assert room.seats[14].head_score==.85 and room.seats[25].head_score==0
    # A second face in one region cannot select either student by list order.
    observations.append(FaceObservation(np.eye(3),(210,90,290,240)))
    states=room.heads(frame,Path('unused'),now=6.7)
    assert states[0]['state']=='multiple_faces' and room.seats[14].head_score==0
    assert states[1]['calibrated']


def test_small_or_boundary_face_cannot_trigger_and_camera_resolution_change_stops():
    run=DeviceRun('teacher','exam');room=RoomState.create(run,RoomStart(regions=REGIONS).regions,{14:'A',25:'B'})
    observations=[FaceObservation(None,(60,70,90,110),'face_too_small')]
    room.source=SimpleNamespace(estimate_all=lambda f,t:observations,close=lambda:None)
    frame=np.zeros((360,640,3),np.uint8)
    states=room.heads(frame,'unused',calibrate=True,now=0)
    assert states[0]['state']=='face_too_small' and room.seats[14].head_score==0
    observations[:]=[FaceObservation(rotation(50),(260,70,400,250))]
    states=room.heads(frame,'unused',now=.3)
    assert not any(s['sustained'] for s in states)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:room.check_shape(np.zeros((720,1280,3),np.uint8))
    assert error.value.status_code==409


async def add_second_student(conn,session):
    await conn.execute('''INSERT INTO seat_assignments(session_id,seat_number,student_reg_no,student_id)
        SELECT $1::uuid,25,'232490',id FROM users WHERE email=$2''',session,STUDENT_B_EMAIL)


async def test_room_start_requires_the_exact_roster_and_replacement_stops_run(client,admin_conn,active_session,device):
    await add_second_student(admin_conn,active_session)
    headers=auth(await login(client,TEACHER_EMAIL));url=f'/api/sessions/{active_session}/device-camera/room/start'
    assert (await client.post(url,headers=headers,json={'regions':[REGIONS[0]]})).status_code==409
    assert (await client.post(url,headers=headers,json={'regions':REGIONS})).status_code==201
    run=next(iter(device.runs.values()))
    await admin_conn.execute('DELETE FROM seat_assignments WHERE session_id=$1::uuid AND seat_number=25',active_session)
    result=await client.post(f'/api/device-camera/{run.run_id}/room/frame?frame_index=0',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
    assert result.status_code==409 and 'CSV roster changed' in result.text
    assert await admin_conn.fetchval('SELECT count(*) FROM cases WHERE session_id=$1::uuid',active_session)==0


async def test_room_phone_and_book_scores_are_separate_and_privately_saved(client,admin_conn,active_session,device,monkeypatch):
    from app.services import storage
    from app.services.device_camera import time
    saved={}
    class Storage:
        async def upload(self,path,data,kind):saved[path]=data
        async def delete(self,paths):
            for path in paths:saved.pop(path,None)
    monkeypatch.setattr(storage,'get_storage',lambda:Storage())
    await add_second_student(admin_conn,active_session)
    headers=auth(await login(client,TEACHER_EMAIL))
    started=await client.post(f'/api/sessions/{active_session}/device-camera/room/start',headers=headers,json={'regions':REGIONS})
    assert started.status_code==201
    run=device.runs[started.json()['run_id']]
    def infer(target,data):
        frame=__import__('app.services.device_camera',fromlist=['decode_frame']).decode_frame(data)
        seat=14 if target.frame_index==0 else 25
        child=target.room.seats[seat];signal='PHONE_DETECTED' if seat==14 else 'UNAUTHORISED_OBJECT'
        event=SimpleNamespace(type=signal,confidence=.92,track_id=1)
        child.histories[(signal,1)]=[(time.monotonic()-4,.96),(time.monotonic()-2,.96)]
        return frame,child,[event],[],.01,None
    monkeypatch.setattr(device,'_infer',infer)
    # An active head warning from another seat cannot accompany seat 14's phone.
    run.room.seats[25].head_score=.85;run.room.seats[25].head_verified_at=time.monotonic()
    for i,seat in enumerate([14,25]):
        result=await client.post(f'/api/device-camera/{run.run_id}/room/frame?frame_index={i}',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
        assert result.status_code==200 and result.json()['alert'],result.text
        assert result.json()['alert']['seat_number']==seat
    rows=await admin_conn.fetch('SELECT seat_number,behaviour_types,snapshot_path FROM detection_events WHERE session_id=$1::uuid ORDER BY seat_number',active_session)
    assert list(rows[0]['behaviour_types'])==['PHONE_DETECTED']
    assert 'PHONE_DETECTED' not in rows[1]['behaviour_types']
    import cv2
    for row in rows:
        image=cv2.imdecode(np.frombuffer(saved[row['snapshot_path']],np.uint8),cv2.IMREAD_COLOR)
        assert image.shape[1]<320  # the other student's room region is not saved
    hod=auth(await login(client,HOD_EMAIL))
    assert len((await client.get('/api/detections',headers=hod,params={'session_id':active_session})).json())==2


async def test_csv_read_matches_reupload_not_capacity_placeholders(client,admin_conn,active_session):
    headers=auth(await login(client,TEACHER_EMAIL));url=f'/api/sessions/{active_session}/seatmap'
    first=await client.get(url,headers=headers)
    assert first.status_code==200 and first.json()['assignments'][0]['seat_number']==14
    upload=await client.post(url,headers=headers,files={'file':('seats.csv',b'seat_number,student_reg_no\n7,232490\n','text/csv')})
    assert upload.status_code==200
    next_map=(await client.get(url,headers=headers)).json()
    assert [s['seat_number'] for s in next_map['assignments']]==[7]
    assert next_map['assignments'][0]['registration_no']=='232490'
    assert next_map['assignments'][0]['student_name']
    invalid=await client.post(url,headers=headers,files={'file':('bad.csv',b'seat_number,student_reg_no\n1,000000\n','text/csv')})
    assert invalid.status_code==409
    assert (await client.get(url,headers=headers)).json()==next_map


async def test_room_head_endpoint_creates_only_the_violating_students_case(client,admin_conn,active_session,device,monkeypatch):
    from app.services import storage
    saved={}
    class Storage:
        async def upload(self,path,data,kind):saved[path]=data
        async def delete(self,paths):
            for path in paths:saved.pop(path,None)
    monkeypatch.setattr(storage,'get_storage',lambda:Storage())
    await add_second_student(admin_conn,active_session)
    headers=auth(await login(client,TEACHER_EMAIL))
    started=await client.post(f'/api/sessions/{active_session}/device-camera/room/start',headers=headers,json={'regions':REGIONS})
    run=device.runs[started.json()['run_id']]
    observations=[FaceObservation(np.eye(3),(60,70,200,250)),FaceObservation(np.eye(3),(420,70,560,250))]
    run.room.source=SimpleNamespace(estimate_all=lambda f,t:observations,close=lambda:None)
    process=run.room.heads;clock=iter(np.arange(0,20,.3))
    monkeypatch.setattr(run.room,'heads',lambda image,path,calibrate:process(image,path,calibrate,now=next(clock)))
    response=await client.post(f'/api/device-camera/{run.run_id}/head/calibrate',headers=headers)
    assert response.status_code==204
    async def sample(index):
        result=await client.post(f'/api/device-camera/{run.run_id}/room/head/frame?frame_index={index}',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
        assert result.status_code==200,result.text
        return result.json()
    for i in range(10):
        result=await sample(i)
        assert result['alerts']==[]
    assert all(s['calibrated'] for s in result['seats'])
    observations[1]=FaceObservation(rotation(-42),(420,70,560,250))
    results=[await sample(i) for i in range(10,23)]
    alerts=[a for r in results for a in r['alerts']]
    assert len(alerts)==1 and alerts[0]['seat_number']==25
    updates=[d for r in results for d in r['detections']]
    assert len(updates)==1 and updates[0]['case_id']==alerts[0]['id']
    assert updates[0]['seat_number']==25 and updates[0]['behaviour_types']==['HEAD_POSE_VIOLATION']
    row=await admin_conn.fetchrow('SELECT * FROM detection_events WHERE session_id=$1::uuid',active_session)
    assert list(row['behaviour_types'])==['HEAD_POSE_VIOLATION'] and row['snapshot_path'] in saved
    assert results[-1]['seats'][0]['sustained'] is False
    repeated=await client.post(f'/api/device-camera/{run.run_id}/room/head/frame?frame_index=22',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
    assert repeated.status_code==409


def test_whole_frame_objects_are_grouped_for_all_seats_with_independent_track_ids():
    from app.vision.phone import DetectionEvent
    run=DeviceRun('teacher','exam');room=RoomState.create(run,RoomStart(regions=REGIONS).regions,{14:'A',25:'B'})
    events=[DetectionEvent('PHONE_DETECTED',.9,0,(80,140,130,220),'phone',1),
            DetectionEvent('UNAUTHORISED_OBJECT',.9,0,(440,140,540,240),'book',2),
            DetectionEvent('PHONE_DETECTED',.9,0,(300,140,340,220),'phone',3)]
    room.wide_detector=SimpleNamespace(process_frame=lambda f:events,last_inference_seconds=.01)
    target,grouped,objects,seconds,warning=room.objects(np.zeros((360,640,3),np.uint8),None)
    assert target is None
    assert {seat:len(rows) for seat,rows in grouped.items()}=={14:1,25:1}
    assert grouped[14][0].track_id=='wide:1'
    assert len(objects)==2 and all(o['track_id'].startswith('wide:') for o in objects)
    assert all(s.detector is None for s in room.seats.values())


def test_fast_detail_checks_keep_same_seat_until_confirmation_time(monkeypatch):
    from app.vision.phone import DetectionEvent
    from app.services import room_camera
    run=DeviceRun('teacher','exam');room=RoomState.create(run,RoomStart(regions=REGIONS).regions,{14:'A',25:'B'})
    room.wide_detector=SimpleNamespace(process_frame=lambda f:[],last_inference_seconds=.01)
    event=DetectionEvent('PHONE_DETECTED',.9,0,(80,140,130,220),'phone',1)
    room.seats[14].detector=SimpleNamespace(process_frame=lambda f:[event],last_inference_seconds=.01)
    clock=[0.]
    monkeypatch.setattr(room_camera.time,'monotonic',lambda:clock[0])
    frame=np.zeros((360,640,3),np.uint8)
    for now in [0,.5,1,2.9]:
        clock[0]=now
        target,events,*_=room.objects(frame,None)
        assert target.seat_number==14 and events and room.cursor==0
    clock[0]=3.1
    assert room.objects(frame,None)[0].seat_number==14
    assert room.cursor==1 and room.focused_samples==0


def test_visible_wide_object_does_not_starve_other_seats_detail_checks():
    from app.vision.phone import DetectionEvent
    run=DeviceRun('teacher','exam');room=RoomState.create(run,RoomStart(regions=REGIONS).regions,{14:'A',25:'B'})
    phone=DetectionEvent('PHONE_DETECTED',.9,0,(80,140,130,220),'phone',1)
    book=DetectionEvent('UNAUTHORISED_OBJECT',.9,0,(80,140,180,220),'book',1)
    room.wide_detector=SimpleNamespace(process_frame=lambda f:[phone],last_inference_seconds=.01)
    room.seats[14].detector=SimpleNamespace(process_frame=lambda f:[],last_inference_seconds=.01)
    room.seats[25].detector=SimpleNamespace(process_frame=lambda f:[book],last_inference_seconds=.01)
    frame=np.zeros((360,640,3),np.uint8)
    for cycle in range(2):
        for _ in range(3):assert room.objects(frame,None)[0] is None
        target,events,objects,*_=room.objects(frame,None)
        assert target.seat_number==[14,25][cycle]
    assert events[0].label=='book' and objects[0]['seat_number']==25


@pytest.mark.parametrize('socket_available',[True,False])
async def test_one_room_sample_can_save_two_separate_student_cases(client,admin_conn,active_session,device,monkeypatch,socket_available):
    from app.services import storage
    from app.services.device_camera import decode_frame,time
    class Storage:
        async def upload(self,*args):pass
        async def delete(self,*args):pass
    monkeypatch.setattr(storage,'get_storage',lambda:Storage())
    if not socket_available:
        from app.routers import internal
        async def disconnected(*args):raise RuntimeError('test socket outage')
        monkeypatch.setattr(internal,'emit_detection',disconnected)
    await add_second_student(admin_conn,active_session)
    headers=auth(await login(client,TEACHER_EMAIL))
    started=await client.post(f'/api/sessions/{active_session}/device-camera/room/start',headers=headers,json={'regions':REGIONS})
    run=device.runs[started.json()['run_id']]
    def infer(target,data):
        rows={}
        for seat,signal in [(14,'PHONE_DETECTED'),(25,'UNAUTHORISED_OBJECT')]:
            identity=f'wide:{seat}'
            target.room.seats[seat].histories[(signal,identity)]=[(time.monotonic()-4,.96),(time.monotonic()-2,.96)]
            rows[seat]=[SimpleNamespace(type=signal,confidence=.92,track_id=identity)]
        return decode_frame(data),None,rows,[],.01,None
    monkeypatch.setattr(device,'_infer',infer)
    response=await client.post(f'/api/device-camera/{run.run_id}/room/frame?frame_index=0',headers={**headers,'Content-Type':'image/jpeg'},content=jpeg())
    assert response.status_code==200,response.text
    assert {a['seat_number'] for a in response.json()['alerts']}=={14,25}
    updates=response.json()['detections']
    assert {d['seat_number'] for d in updates}=={14,25}
    assert {d['case_id'] for d in updates}=={a['id'] for a in response.json()['alerts']}
    assert all(d['session_id']==active_session and d['student_name'] and d['id']!=d['case_id'] for d in updates)
    assert all('snapshot_path' not in d for d in updates)
    assert response.json()['checked_seat'] is None
    rows=await admin_conn.fetch('SELECT seat_number,behaviour_types FROM detection_events WHERE session_id=$1::uuid ORDER BY seat_number',active_session)
    assert list(rows[0]['behaviour_types'])==['PHONE_DETECTED']
    assert list(rows[1]['behaviour_types'])==['UNAUTHORISED_OBJECT']
    # The committed HTTP feed also rechecks the current account and assignment.
    from app.routers.device_camera import committed_detections
    from starlette.requests import Request
    from fastapi import HTTPException
    alerts=response.json()['alerts']
    other=Request({'type':'http','headers':[(b'cookie',auth(await login(client,HOD_EMAIL))['Cookie'].encode())]})
    with pytest.raises(HTTPException) as denied:await committed_detections(alerts,other)
    assert denied.value.status_code==403
    await admin_conn.execute('UPDATE exam_sessions SET invigilator_id=NULL WHERE id=$1::uuid',active_session)
    owner=Request({'type':'http','headers':[(b'cookie',headers['Cookie'].encode())]})
    assert await committed_detections(alerts,owner)==[]
