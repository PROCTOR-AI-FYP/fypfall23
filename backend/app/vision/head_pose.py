"""Calibrated head rotation from MediaPipe's canonical-face transformation.

Yaw +: person's left (unmirrored image right). Pitch -: down. Roll +: image
counterclockwise. R = Rz(roll) Ry(yaw) Rx(-pitch). Angles are relative to the
person's normal exam posture. Head orientation is not gaze or proof of cheating.
"""
from __future__ import annotations
import argparse
import math
import time
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np

YAW_THRESHOLD_DEG = 30.
PITCH_THRESHOLD_DEG = -20.
SUSTAINED_SECONDS = 2.
HEAD = 'HEAD_POSE_VIOLATION'
MODEL_PATH = Path(__file__).parent / 'models/face_landmarker.task'


@dataclass(frozen=True)
class PoseResult:
    yaw: float
    pitch: float
    roll: float


@dataclass(frozen=True)
class DetectionEvent:
    type: str
    confidence: float
    timestamp: float


@dataclass(frozen=True)
class FaceObservation:
    rotation: np.ndarray | None
    box: tuple | None = None
    reason: str | None = None


def rotation_from_matrix(matrix):
    """Remove scale/drift, rejecting invalid or reflected transforms."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape not in ((3,3),(4,4)) or not np.isfinite(matrix).all():
        raise ValueError('Invalid face transform')
    block = matrix[:3,:3]
    if np.linalg.det(block) <= 0:
        raise ValueError('Reflected or degenerate face transform')
    u, singular, vt = np.linalg.svd(block)
    if singular.min() < 1e-6 or singular.max()/singular.min() > 1.2:
        raise ValueError('Distorted face transform')
    return u @ vt


def pose_from_rotation(rotation):
    r = rotation_from_matrix(rotation)
    sy = math.hypot(r[0,0],r[1,0])
    if sy < 1e-5:
        raise ValueError('Head rotation outside supported frontal range')
    return PoseResult(math.degrees(math.atan2(-r[2,0],sy)),
                      -math.degrees(math.atan2(r[2,1],r[2,2])),
                      math.degrees(math.atan2(r[1,0],r[0,0])))


def rotation_distance(a,b):
    return math.degrees(math.acos(float(np.clip((np.trace(a.T @ b)-1)/2,-1,1))))


def mean_rotation(rotations):
    u, _, vt = np.linalg.svd(np.mean(rotations,axis=0))
    return u @ np.diag([1.,1.,np.linalg.det(u @ vt)]) @ vt


class MediaPipePoseSource:
    def __init__(self, model_path=MODEL_PATH, *, num_faces=2, max_dimension=640, image_mode=False):
        import mediapipe as mp
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError('Face model missing. Run python ai-engine/prepare_models.py --face')
        self.mp = mp
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE if image_mode else mp.tasks.vision.RunningMode.VIDEO, num_faces=num_faces,
            min_face_detection_confidence=.6, min_face_presence_confidence=.6,
            min_tracking_confidence=.6, output_facial_transformation_matrixes=True)
        self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        self._last_ms = -1
        self._mirrored = False
        self.max_dimension = max_dimension
        self.image_mode = image_mode

    def estimate_regions(self, frame, regions, timestamp):
        """Native seat crops let the short-range face model see room faces.

        IMAGE mode prevents VIDEO tracking from following a face from one seat
        crop into the next. Rotation/timing/calibration remain independent in
        the caller. Crop size gates use captured pixels, never upscaled pixels.
        """
        if not self.image_mode:
            raise ValueError('Region estimation requires independent IMAGE inference')
        h,w = frame.shape[:2]
        observations = []
        for bounds in regions:
            x1,y1,x2,y2 = [round(v*(h if i%2 else w)) for i,v in enumerate(bounds)]
            crop = frame[y1:y2,x1:x2]
            if min(crop.shape[:2])<64:
                observations.append(FaceObservation(None,(x1,y1,x2,y2),'face_too_small'))
                continue
            for observation in self.estimate_all(crop,timestamp):
                if observation.box is None:
                    continue
                a,b,c,d = observation.box
                box = (a+x1,b+y1,c+x1,d+y1)
                if a<=2 or b<=2 or c>=crop.shape[1]-2 or d>=crop.shape[0]-2:
                    observations.append(FaceObservation(None,box,'unreliable_face'))
                else:
                    observations.append(FaceObservation(observation.rotation,box,observation.reason))
        return observations

    def estimate_all(self, frame, timestamp):
        """Room observations carry spatial boxes; list position is never identity.

        Keep native image detail up to 1600 pixels. Do not upscale a tiny face
        and then call it reliable; size gates use actual captured pixels.
        """
        h, w = frame.shape[:2]
        ratio = min(1., self.max_dimension / max(h, w))
        small = cv2.resize(frame, (round(w*ratio), round(h*ratio))) if ratio < 1 else frame
        result = self._detect(small, timestamp, False)
        observations = []
        for index, landmarks in enumerate(result.face_landmarks):
            points = np.array([(p.x, p.y) for p in landmarks[:468]])
            if not np.isfinite(points).all():
                continue
            x1,y1 = points.min(axis=0)
            x2,y2 = points.max(axis=0)
            box = (x1*w,y1*h,x2*w,y2*h)
            if (x2-x1)*small.shape[1] < 60 or (y2-y1)*small.shape[0] < 70:
                observations.append(FaceObservation(None, box, 'face_too_small'))
                continue
            try:
                if x1<0 or y1<0 or x2>1 or y2>1:
                    raise ValueError('Face outside image')
                rotation = rotation_from_matrix(result.facial_transformation_matrixes[index])
                observations.append(FaceObservation(rotation, box))
            except (ValueError, IndexError):
                observations.append(FaceObservation(None, box, 'unreliable_face'))
        return observations

    def _detect(self, small, timestamp, mirrored):
        # A failed view may be easier for the model after horizontal reflection.
        # Reuse VIDEO tracking in the successful view instead of doubling every
        # frame's inference. The camera feed itself always stays unmirrored.
        view = cv2.flip(small, 1) if mirrored else small
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                              data=cv2.cvtColor(view,cv2.COLOR_BGR2RGB))
        if getattr(self,'image_mode',False):
            return self.landmarker.detect(image)
        ms = max(self._last_ms+1,round(timestamp*1000))
        self._last_ms = ms
        return self.landmarker.detect_for_video(image,ms)

    def estimate(self, frame, timestamp):
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
            raise ValueError('Expected a non-empty BGR camera frame')
        h,w = frame.shape[:2]
        ratio = min(1.,640/max(h,w))
        small = cv2.resize(frame,(round(w*ratio),round(h*ratio))) if ratio < 1 else frame
        result = self._detect(small,timestamp,self._mirrored)
        if not result.face_landmarks:
            recovered = self._detect(small,timestamp,not self._mirrored)
            if recovered.face_landmarks:
                self._mirrored = not self._mirrored
                result = recovered
        if len(result.face_landmarks) != 1:
            return FaceObservation(None,reason='no_face' if not result.face_landmarks else 'multiple_faces')
        points = np.array([(p.x,p.y) for p in result.face_landmarks[0][:468]])
        if self._mirrored:
            points[:,0] = 1.-points[:,0]
        if not np.isfinite(points).all():
            return FaceObservation(None,reason='unreliable_face')
        x1,y1 = points.min(axis=0)
        x2,y2 = points.max(axis=0)
        if (x2-x1)*small.shape[1] < 60 or (y2-y1)*small.shape[0] < 70:
            return FaceObservation(None,reason='face_too_small')
        if x1<0 or y1<0 or x2>1 or y2>1 or not result.facial_transformation_matrixes:
            return FaceObservation(None,reason='unreliable_face')
        try:
            rotation = rotation_from_matrix(result.facial_transformation_matrixes[0])
            if self._mirrored:
                # Reflect both camera and canonical model axes to retain a
                # proper rotation. Yaw/roll signs and original-image boxes must
                # not inherit the mirrored inference view.
                reflection = np.diag([-1.,1.,1.])
                rotation = reflection @ rotation @ reflection
        except ValueError:
            return FaceObservation(None,reason='unreliable_face')
        return FaceObservation(rotation,(x1*w,y1*h,x2*w,y2*h))

    def close(self):
        self.landmarker.close()


class HeadPoseDetector:
    def __init__(self, yaw_threshold=YAW_THRESHOLD_DEG, pitch_threshold=PITCH_THRESHOLD_DEG,
                 sustained_seconds=SUSTAINED_SECONDS, debug=False, *, source=None,
                 calibration_seconds=2., smoothing_seconds=.12, max_gap=.5,
                 reference_loss_seconds=2.):
        if (not all(math.isfinite(v) for v in (yaw_threshold,pitch_threshold,sustained_seconds))
                or not 0<yaw_threshold<85 or not -85<pitch_threshold<0 or sustained_seconds<=0):
            raise ValueError('Invalid head-pose thresholds')
        if (not all(math.isfinite(value) for value in
                    (calibration_seconds,smoothing_seconds,max_gap,reference_loss_seconds))
                or calibration_seconds<=0 or smoothing_seconds<0 or max_gap<=0
                or reference_loss_seconds<max_gap):
            raise ValueError('Invalid head-pose timing')
        self.yaw_threshold, self.pitch_threshold = yaw_threshold,pitch_threshold
        self.sustained_seconds, self.debug = sustained_seconds,debug
        self.calibration_seconds, self.smoothing_seconds, self.max_gap = calibration_seconds,smoothing_seconds,max_gap
        self.reference_loss_seconds = reference_loss_seconds
        self.source = source if source is not None else MediaPipePoseSource()
        self._neutral = self._filtered = None
        self._last_pose = self._raw_pose = None
        self._last_time = self._violation_start_time = None
        self._last_valid_time = None
        self._calibration = None
        self._calibration_start = None
        self._shape = self._box = None
        self._reason = 'calibration_required'
        self._violating = self._sustained = False
        self._calibration_progress = 0.
        self.last_processing_seconds = 0.

    def begin_calibration(self):
        self._neutral = self._filtered = self._last_pose = None
        self._calibration = []
        self._calibration_start = None
        self._calibration_progress = 0.
        self._clear_violation()
        self._reason = 'calibrating'

    def _invalidate_reference(self):
        self._neutral = self._filtered = self._last_pose = None
        self._clear_violation()
        self._interrupt_calibration()

    def _clear_violation(self):
        self._violation_start_time = None
        self._violating = self._sustained = False

    def _interrupt_calibration(self):
        if self._calibration is not None:
            self._calibration = []
            self._calibration_start = None
            self._calibration_progress = 0.

    def process_frame(self, frame, timestamp=None):
        now = time.monotonic() if timestamp is None else float(timestamp)
        if not math.isfinite(now):
            raise ValueError('Expected a finite timestamp')
        started = time.perf_counter()
        try:
            return self._process(frame,now)
        finally:
            self.last_processing_seconds = time.perf_counter()-started

    def _process(self, frame, now):
        dt = None if self._last_time is None else now-self._last_time
        if dt is not None and (dt<=0 or dt>self.max_gap):
            self._clear_violation()
            self._interrupt_calibration()
            self._filtered = None
        if dt is not None and (dt<=0 or dt>=self.reference_loss_seconds):
            self._invalidate_reference()
        self._last_time = now
        if self._shape is not None and frame.shape!=self._shape:
            self._neutral = self._filtered = None
            self._clear_violation()
            self._interrupt_calibration()
        self._shape = frame.shape
        if (self._last_valid_time is not None
                and now-self._last_valid_time>=self.reference_loss_seconds):
            self._invalidate_reference()
        observation = self.source.estimate(frame,now)
        self._box = observation.box
        try:
            if observation.rotation is None:
                raise ValueError(observation.reason or 'unreliable_face')
            rotation = rotation_from_matrix(observation.rotation)
            self._raw_pose = pose_from_rotation(rotation)
        except ValueError as exc:
            self._reason = str(exc)
            self._last_pose = self._raw_pose = self._filtered = None
            self._clear_violation()
            self._interrupt_calibration()
            if observation.reason == 'multiple_faces':
                # A face-list position is not a student identity. Do not apply
                # one person's neutral posture after an ambiguous handover.
                self._invalidate_reference()
            return None
        self._last_valid_time = now
        if self._calibration is not None:
            raw = self._raw_pose
            if abs(raw.yaw)>35 or abs(raw.pitch)>55 or abs(raw.roll)>35:
                self._interrupt_calibration()
                self._reason = 'face_forward_to_calibrate'
                return None
            if self._calibration and rotation_distance(self._calibration[0],rotation)>5:
                self._interrupt_calibration()
            if not self._calibration:
                self._calibration_start = now
            self._calibration.append(rotation)
            elapsed = now-self._calibration_start
            self._calibration_progress = min(1.,elapsed/self.calibration_seconds,len(self._calibration)/8)
            self._reason = 'calibrating'
            if elapsed<self.calibration_seconds or len(self._calibration)<8:
                return None
            self._neutral = mean_rotation(self._calibration)
            self._calibration = None
            self._filtered = None
        if self._neutral is None:
            self._reason = 'calibration_required'
            self._last_pose = None
            self._clear_violation()
            return None
        relative = self._neutral.T @ rotation
        alpha = 1. if dt is None or self.smoothing_seconds==0 else 1.-math.exp(-max(dt,0)/self.smoothing_seconds)
        self._filtered = relative if self._filtered is None else mean_rotation([
            (1-alpha)*self._filtered+alpha*relative])
        try:
            pose = pose_from_rotation(self._filtered)
        except ValueError:
            self._reason = 'unreliable_face'
            self._last_pose = self._filtered = None
            self._clear_violation()
            return None
        if abs(pose.yaw)>80 or abs(pose.pitch)>75 or abs(pose.roll)>75:
            self._reason = 'unreliable_face'
            self._last_pose = self._filtered = None
            self._clear_violation()
            return None
        self._last_pose = pose
        enter = abs(pose.yaw)>self.yaw_threshold or pose.pitch<self.pitch_threshold
        remain = abs(pose.yaw)>self.yaw_threshold-3 or pose.pitch<self.pitch_threshold+3
        if not (enter or self._violating and remain):
            self._clear_violation()
            self._reason = 'neutral'
            return None
        self._violating = True
        if self._violation_start_time is None:
            self._violation_start_time = now
        self._sustained = now-self._violation_start_time>=self.sustained_seconds
        self._reason = 'sustained' if self._sustained else 'turning'
        # Policy signal strength, not a fabricated probability of guilt.
        return DetectionEvent(HEAD,.65,time.time()) if self._sustained else None

    def status(self):
        pose = self._last_pose
        return dict(state=self._reason, calibrated=self._neutral is not None,
                    calibrating=self._calibration is not None, calibration_progress=self._calibration_progress,
                    yaw=None if pose is None else pose.yaw, pitch=None if pose is None else pose.pitch,
                    roll=None if pose is None else pose.roll, violating=self._violating, sustained=self._sustained,
                    duration=0. if self._violation_start_time is None else self._last_time-self._violation_start_time,
                    face_box=self._box, processing_ms=self.last_processing_seconds*1000,
                    thresholds=dict(yaw=self.yaw_threshold,pitch=self.pitch_threshold,seconds=self.sustained_seconds))

    def annotate_frame(self, frame):
        annotated = frame.copy()
        if self._box is not None:
            x1,y1,x2,y2 = map(round,self._box)
            color = (0,0,255) if self._sustained else (0,180,255) if self._violating else (80,210,100)
            cv2.rectangle(annotated,(x1,y1),(x2,y2),color,2)
        pose = self._last_pose
        text = (f'Head yaw {pose.yaw:+.1f}  pitch {pose.pitch:+.1f}  roll {pose.roll:+.1f}'
                if pose else 'Head: '+self._reason.replace('_',' '))
        cv2.putText(annotated,text,(10,frame.shape[0]-18),cv2.FONT_HERSHEY_SIMPLEX,.55,(240,240,240),2)
        return annotated

    def close(self):
        self.source.close()


def main():
    from camera import open_camera
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',default='0')
    args = parser.parse_args()
    detector = HeadPoseDetector(debug=True)
    cap = open_camera(int(args.source) if args.source.isdigit() else args.source)
    print('Press c in your normal exam posture; hold still for 2 seconds. q quits.',flush=True)
    try:
        while True:
            ok,frame = cap.read()
            if not ok:
                break
            event = detector.process_frame(frame)
            if event:
                print(f'{event.type}: {detector.status()}',flush=True)
            cv2.imshow('ProctorAI calibrated head pose',detector.annotate_frame(frame))
            key = cv2.waitKey(1)&0xff
            if key==ord('q'):
                break
            if key==ord('c'):
                detector.begin_calibration()
    finally:
        cap.release()
        detector.close()
        cv2.destroyAllWindows()


if __name__=='__main__':
    main()
