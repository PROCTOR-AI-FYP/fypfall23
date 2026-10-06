"""Known 3D rotations, neutral calibration and timed head-pose regressions."""
import math
from types import SimpleNamespace
import cv2
import numpy as np
import pytest

from head_pose_detector import (HEAD,FaceObservation,HeadPoseDetector,MediaPipePoseSource,PoseResult,
                                pose_from_rotation,rotation_from_matrix)


def rotation(yaw=0,pitch=0,roll=0):
    # Independent axis-angle construction, not the extraction implementation.
    x=cv2.Rodrigues(np.array([-math.radians(pitch),0.,0.]))[0]
    y=cv2.Rodrigues(np.array([0.,math.radians(yaw),0.]))[0]
    z=cv2.Rodrigues(np.array([0.,0.,math.radians(roll)]))[0]
    return z@y@x


@pytest.mark.parametrize('angles',[(0,0,0),(40,0,0),(-40,0,0),(0,-30,0),
    (0,25,0),(0,0,35),(0,0,-35),(35,-25,15),(-35,25,-15),(70,-40,20)])
def test_known_rotations_have_correct_axes_signs_and_degrees(angles):
    found=pose_from_rotation(rotation(*angles))
    assert (found.yaw,found.pitch,found.roll)==pytest.approx(angles,abs=1e-8)


def test_scale_and_translation_cannot_become_angles():
    matrix=np.eye(4)
    matrix[:3,:3]=rotation(35,-20,8)*1.04
    matrix[:3,3]=[120.,-40.,-700.]
    pose=pose_from_rotation(matrix)
    assert (pose.yaw,pose.pitch,pose.roll)==pytest.approx((35,-20,8))


@pytest.mark.parametrize('matrix',[np.zeros((3,3)),np.diag([-1.,1.,1.]),
    np.diag([1.,1.,4.]),np.full((3,3),np.nan),np.eye(2)])
def test_bad_transforms_are_rejected(matrix):
    with pytest.raises(ValueError): rotation_from_matrix(matrix)


def test_gimbal_singularity_is_not_a_plausible_pose():
    with pytest.raises(ValueError): pose_from_rotation(rotation(90))


class Source:
    def __init__(self):
        self.observation=FaceObservation(rotation(),(20,20,100,130))
        self.closed=False

    def estimate(self,frame,timestamp): return self.observation
    def close(self): self.closed=True


@pytest.fixture
def detector():
    source=Source()
    head=HeadPoseDetector(source=source,smoothing_seconds=0)
    frame=np.zeros((200,300,3),np.uint8)
    yield head,source,frame
    head.close()
    assert source.closed


def calibrate(head,frame,start=0):
    head.begin_calibration()
    for t in np.arange(start,start+2.11,.1):
        assert head.process_frame(frame,float(t)) is None
    assert head.status()['calibrated']
    return start+2.2


def test_uncalibrated_pose_cannot_trigger_event(detector):
    head,source,frame=detector
    source.observation=FaceObservation(rotation(45))
    for t in np.arange(0,4,.1): assert head.process_frame(frame,float(t)) is None
    assert head.status()['state']=='calibration_required'
    assert head.status()['yaw'] is None


def test_camera_rotation_is_removed_as_rotation_not_subtracted_euler(detector):
    head,source,frame=detector
    baseline=rotation(12,-25,17)
    source.observation=FaceObservation(baseline)
    now=calibrate(head,frame)
    assert abs(head.status()['pitch'])<1e-6
    source.observation=FaceObservation(baseline@rotation(-40,-15,8))
    head.process_frame(frame,now)
    state=head.status()
    assert (state['yaw'],state['pitch'],state['roll'])==pytest.approx((-40,-15,8))


@pytest.mark.parametrize('angles',[(40,0,0),(-40,0,0),(0,-30,0)])
def test_left_right_and_down_require_two_continuous_seconds(detector,angles):
    head,source,frame=detector
    now=calibrate(head,frame)
    source.observation=FaceObservation(rotation(*angles))
    for t in np.arange(now,now+1.99,.1):
        assert head.process_frame(frame,float(t)) is None
    event=head.process_frame(frame,now+2.01)
    assert event.type==HEAD and event.confidence==.65
    assert head.status()['sustained']
    source.observation=FaceObservation(rotation())
    assert head.process_frame(frame,now+2.1) is None
    assert not head.status()['violating']


def test_roll_is_not_mislabelled_as_sideways_yaw(detector):
    head,source,frame=detector
    now=calibrate(head,frame)
    source.observation=FaceObservation(rotation(0,0,45))
    for t in np.arange(now,now+3,.1): assert head.process_frame(frame,float(t)) is None
    assert abs(head.status()['yaw'])<1e-6
    assert head.status()['roll']==pytest.approx(45)


@pytest.mark.parametrize('reason',['no_face','multiple_faces','face_too_small','unreliable_face'])
def test_missing_or_ambiguous_face_clears_angles_and_duration(detector,reason):
    head,source,frame=detector
    now=calibrate(head,frame)
    source.observation=FaceObservation(rotation(40))
    head.process_frame(frame,now)
    head.process_frame(frame,now+.4)
    source.observation=FaceObservation(None,reason=reason)
    assert head.process_frame(frame,now+.5) is None
    assert head.status()['yaw'] is None and head.status()['duration']==0
    source.observation=FaceObservation(rotation(40))
    assert head.process_frame(frame,now+.6) is None
    assert not head.status()['sustained']


def test_stale_frames_or_clock_reset_cannot_fill_sustain_timer(detector):
    head,source,frame=detector
    now=calibrate(head,frame)
    source.observation=FaceObservation(rotation(40))
    head.process_frame(frame,now)
    assert head.process_frame(frame,now+10) is None
    assert head.status()['duration']==0
    assert head.process_frame(frame,now-1) is None
    assert head.status()['duration']==0


def test_calibration_restarts_after_movement_or_face_loss(detector):
    head,source,frame=detector
    head.begin_calibration()
    for t in np.arange(0,1.1,.1): head.process_frame(frame,float(t))
    source.observation=FaceObservation(rotation(10))
    head.process_frame(frame,1.2)
    assert head.status()['calibration_progress']==0
    source.observation=FaceObservation(None,reason='no_face')
    head.process_frame(frame,1.3)
    assert not head.status()['calibrated']
    source.observation=FaceObservation(rotation())
    for t in np.arange(1.4,3.51,.1): head.process_frame(frame,float(t))
    assert head.status()['calibrated']


def test_calibration_cannot_zero_an_already_turned_head(detector):
    head,source,frame=detector
    source.observation=FaceObservation(rotation(50))
    head.begin_calibration()
    for t in np.arange(0,3,.1): head.process_frame(frame,float(t))
    assert not head.status()['calibrated']


def test_near_threshold_jitter_does_not_chatter(detector):
    head,source,frame=detector
    now=calibrate(head,frame)
    for i,t in enumerate(np.arange(now,now+2.11,.1)):
        source.observation=FaceObservation(rotation(31 if i%2==0 else 29))
        event=head.process_frame(frame,float(t))
    assert event is not None
    source.observation=FaceObservation(rotation(26))
    assert head.process_frame(frame,now+2.2) is None


def test_resolution_change_requires_new_calibration(detector):
    head,_,frame=detector
    now=calibrate(head,frame)
    head.process_frame(np.zeros((400,600,3),np.uint8),now)
    assert not head.status()['calibrated']


def test_recalibration_clears_previous_violation(detector):
    head,source,frame=detector
    now=calibrate(head,frame)
    source.observation=FaceObservation(rotation(40))
    for t in np.arange(now,now+2.11,.1): head.process_frame(frame,float(t))
    assert head.status()['sustained']
    head.begin_calibration()
    assert not head.status()['calibrated'] and not head.status()['violating']


def test_extreme_relative_rotation_does_not_disable_detector(detector):
    head,source,frame=detector
    baseline=rotation(-25)
    source.observation=FaceObservation(baseline)
    now=calibrate(head,frame)
    source.observation=FaceObservation(rotation(65))  # 90 relative to neutral
    assert head.process_frame(frame,now) is None
    assert head.status()['state']=='unreliable_face'
    source.observation=FaceObservation(baseline)
    assert head.process_frame(frame,now+.1) is None
    assert head.status()['state']=='neutral'


def test_brief_tracking_loss_keeps_reference_but_restarts_warning(detector):
    head,source,frame=detector
    now=calibrate(head,frame)
    source.observation=FaceObservation(rotation(40))
    head.process_frame(frame,now)
    source.observation=FaceObservation(None,reason='no_face')
    head.process_frame(frame,now+.1)
    assert head.status()['calibrated'] and head.status()['yaw'] is None
    source.observation=FaceObservation(rotation(40))
    head.process_frame(frame,now+.2)
    assert head.status()['duration']==0 and head.status()['yaw']==pytest.approx(40)


@pytest.mark.parametrize('reason',['no_face','multiple_faces'])
def test_lost_or_ambiguous_student_requires_fresh_neutral(detector,reason):
    head,source,frame=detector
    now=calibrate(head,frame)
    source.observation=FaceObservation(None,reason=reason)
    for t in np.arange(now,now+2.11,.1): head.process_frame(frame,float(t))
    assert not head.status()['calibrated'] and not head.status()['sustained']
    source.observation=FaceObservation(rotation(40))
    assert head.process_frame(frame,now+2.2) is None
    assert head.status()['state']=='calibration_required'
    source.observation=FaceObservation(rotation())
    calibrate(head,frame,now+2.3)
    assert head.status()['state']=='neutral'


def test_multiple_faces_invalidate_reference_immediately(detector):
    head,source,frame=detector
    now=calibrate(head,frame)
    source.observation=FaceObservation(None,reason='multiple_faces')
    head.process_frame(frame,now)
    assert not head.status()['calibrated']
    source.observation=FaceObservation(rotation(-40))
    head.process_frame(frame,now+.1)
    assert head.status()['state']=='calibration_required' and head.status()['yaw'] is None


@pytest.mark.parametrize('offset',[-.1,2.])
def test_clock_reset_or_long_capture_gap_invalidates_reference(detector,offset):
    head,source,frame=detector
    now=calibrate(head,frame)
    source.observation=FaceObservation(rotation(40))
    head.process_frame(frame,now)
    assert head.process_frame(frame,now+offset) is None
    assert not head.status()['calibrated'] and head.status()['yaw'] is None


def face_result(angles=(0,0,0),count=1):
    points=[SimpleNamespace(x=x,y=y) for x,y in [(0.2,0.2),(0.4,0.5)]*234]
    return SimpleNamespace(face_landmarks=[points]*count,
                           facial_transformation_matrixes=[rotation(*angles)]*count)


def queued_pose_source(results):
    class Landmarker:
        def __init__(self): self.calls=[]
        def detect_for_video(self,image,timestamp):
            self.calls.append((image.data.copy(),timestamp))
            return results.pop(0)
    source=MediaPipePoseSource.__new__(MediaPipePoseSource)
    source.mp=SimpleNamespace(Image=lambda **kwargs: SimpleNamespace(**kwargs),
                              ImageFormat=SimpleNamespace(SRGB=1))
    source.landmarker=Landmarker()
    source._last_ms=-1
    source._mirrored=False
    return source


@pytest.mark.parametrize('angles',[(40,-25,15),(-40,20,-15),(0,-30,0)])
def test_mirror_recovery_preserves_physical_axes_box_and_frame(angles):
    # Mirrored landmark coordinates and rotation describe the reflected image.
    # Their public result must describe the original, unmodified camera image.
    mirrored=(-angles[0],angles[1],-angles[2])
    source=queued_pose_source([face_result(count=0),face_result(mirrored),face_result(mirrored)])
    frame=np.zeros((480,640,3),np.uint8)
    frame[:,:100,0]=120
    original=frame.copy()
    found=source.estimate(frame,1.)
    assert np.array_equal(frame,original)
    pose=pose_from_rotation(found.rotation)
    assert (pose.yaw,pose.pitch,pose.roll)==pytest.approx(angles)
    assert found.box==pytest.approx((384,96,512,240))
    calls=source.landmarker.calls
    assert np.array_equal(calls[0][0],cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
    assert np.array_equal(calls[1][0],cv2.cvtColor(cv2.flip(frame,1),cv2.COLOR_BGR2RGB))
    source.estimate(frame,1.)
    assert len(calls)==3  # Successful reflected view becomes the tracked primary.
    assert [entry[1] for entry in calls]==[1000,1001,1002]


@pytest.mark.parametrize('counts',[(2,),(0,2),(0,0)])
def test_recovery_cannot_select_a_student_from_ambiguous_faces(counts):
    source=queued_pose_source([face_result(count=count) for count in counts])
    result=source.estimate(np.zeros((480,640,3),np.uint8),1.)
    assert result.rotation is None and result.box is None
    assert result.reason==('no_face' if counts==(0,0) else 'multiple_faces')
    assert len(source.landmarker.calls)==len(counts)


def test_recovery_rejects_invalid_face_transform():
    bad=face_result()
    bad.facial_transformation_matrixes=[np.diag([-1.,1.,1.])]
    source=queued_pose_source([face_result(count=0),bad])
    result=source.estimate(np.zeros((480,640,3),np.uint8),1.)
    assert result.reason=='unreliable_face' and result.rotation is None


def test_room_estimates_all_faces_without_using_order_as_identity():
    result=face_result(count=2)
    source=queued_pose_source([result]);source.max_dimension=1600
    observations=source.estimate_all(np.zeros((900,1600,3),np.uint8),1.)
    assert len(observations)==2 and all(o.rotation is not None for o in observations)
    assert all(o.box is not None for o in observations)
    assert len(source.landmarker.calls)==1


@pytest.mark.parametrize('value',[float('nan'),float('inf')])
def test_nonfinite_sustained_timing_rejected(value):
    with pytest.raises(ValueError):HeadPoseDetector(sustained_seconds=value,source=Source())
