"""Spatial attribution for one fixed room camera, independent state per CSV seat.

The roster establishes identity; the teacher's camera regions establish location.
Never infer a student from face-list ordering or copy a room warning to all seats.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.schemas import StrictModel
from app.services.device_camera import DeviceRun, decode_frame


class CameraRegion(StrictModel):
    seat_number: int = Field(ge=1, le=1000)
    box: list[float] = Field(min_length=4, max_length=4)

    @model_validator(mode='after')
    def bounds(self):
        x1,y1,x2,y2 = self.box
        if (not all(math.isfinite(v) and 0<=v<=1 for v in self.box)
                or x2-x1<.025 or y2-y1<.025):
            raise ValueError('Draw a non-empty camera region inside the image.')
        return self


class RoomStart(StrictModel):
    regions: list[CameraRegion] = Field(min_length=1, max_length=64)

    @model_validator(mode='after')
    def distinct(self):
        if len({r.seat_number for r in self.regions}) != len(self.regions):
            raise ValueError('Map each seat only once.')
        for i, a in enumerate(self.regions):
            for b in self.regions[i+1:]:
                if intersection(a.box, b.box) > 1e-8:
                    raise ValueError('Camera seat regions must not overlap.')
        return self


def intersection(a, b):
    return max(0., min(a[2],b[2])-max(a[0],b[0])) * max(0.,min(a[3],b[3])-max(a[1],b[1]))


def assign_box(box, regions, coverage=.85):
    """Require an unambiguous, mostly contained observation. Boundary = unknown."""
    if not all(math.isfinite(v) for v in box):
        return None
    area = (box[2]-box[0])*(box[3]-box[1])
    if area <= 0:
        return None
    cx,cy = (box[0]+box[2])/2,(box[1]+box[3])/2
    matches = [r.seat_number for r in regions
               if r.box[0]<cx<r.box[2] and r.box[1]<cy<r.box[3]
               and intersection(box, r.box)/area >= coverage]
    return matches[0] if len(matches)==1 else None


class ObservationSource:
    observation = None
    def estimate(self, frame, timestamp):
        return self.observation
    def close(self):
        pass


@dataclass
class RoomState:
    regions: list[CameraRegion]
    students: dict[int, str]
    seats: dict[int, DeviceRun]
    source: object | None = None
    cursor: int = 0
    focused_samples: int = 0
    focused_started: float | None = None
    shape: tuple | None = None
    last_objects: list = field(default_factory=list)
    previous_faces: dict = field(default_factory=dict)
    wide_detector: object | None = None
    wide_samples: int = 0

    @classmethod
    def create(cls, run, regions, students):
        return cls(regions, students,
                   {seat:DeviceRun(run.owner_id, run.session_id, seat, student)
                    for seat, student in students.items()})

    def close(self):
        if self.source:
            self.source.close()
            self.source = None

    def check_shape(self, frame):
        if self.shape is not None and frame.shape != self.shape:
            raise HTTPException(409, 'Camera dimensions changed. Remap the room before restarting.')
        self.shape = frame.shape

    def heads(self, frame, model_path, calibrate=False, now=None):
        from app.vision.head_pose import MediaPipePoseSource, HeadPoseDetector, FaceObservation
        self.check_shape(frame)
        if self.source is None:
            self.source = MediaPipePoseSource(model_path, num_faces=2, max_dimension=1600, image_mode=True)
        now = time.monotonic() if now is None else now
        height,width = frame.shape[:2]
        grouped = {seat:[] for seat in self.seats}
        observations = (self.source.estimate_regions(frame,[r.box for r in self.regions],now)
                        if hasattr(self.source,'estimate_regions') else self.source.estimate_all(frame,now))
        for observation in observations:
            if observation.box is None:
                continue
            normalized = [v/(height if i%2 else width) for i,v in enumerate(observation.box)]
            seat = assign_box(normalized,self.regions)
            if seat is not None:
                grouped[seat].append(observation)
            else:
                # A face straddling regions makes those regions ambiguous.
                for region in self.regions:
                    if intersection(normalized,region.box)>0:
                        grouped[region.seat_number].append(FaceObservation(None,reason='unreliable_face'))
        states = []
        for seat, target in self.seats.items():
            if target.head is None:
                target.head = HeadPoseDetector(source=ObservationSource(),max_gap=2.,reference_loss_seconds=4.)
            if calibrate:
                target.head.begin_calibration()
            observations = grouped[seat]
            if len(observations)==1 and observations[0].rotation is not None:
                box = observations[0].box
                previous = self.previous_faces.get(seat)
                if previous is not None:
                    area = (box[2]-box[0])*(box[3]-box[1])
                    prior_area = (previous[2]-previous[0])*(previous[3]-previous[1])
                    overlap = intersection(box,previous)
                    if overlap/max(area+prior_area-overlap,1)<.15:
                        target.head._invalidate_reference()
                self.previous_faces[seat] = box
            elif not observations or len(observations)>1:
                self.previous_faces.pop(seat,None)
            target.head.source.observation = (observations[0] if len(observations)==1 else
                FaceObservation(None,reason='multiple_faces' if observations else 'no_face'))
            target.head.process_frame(frame,timestamp=now)
            state = target.head.status()
            target.head_score = .85 if state['sustained'] else 0.
            target.head_verified_at = now
            states.append({'seat_number':seat,**state})
        return states

    def objects(self, frame, model):
        """Check the whole room first. If no attributable object is verified,
        scan one native seat crop and retain a positive crop for confirmation.
        Full-frame observations score all implicated seats in the same sample.
        """
        from app.vision.phone import PhoneDetector
        from dataclasses import replace
        self.check_shape(frame)
        elapsed = 0.
        # Periodic native checks also cover small objects in other seats while
        # a readily visible object remains in the wide image.
        if not self.focused_samples and self.wide_samples<3:
            if self.wide_detector is None:
                self.wide_detector = PhoneDetector(model=model,use_tiling=False,full_imgsz=640,min_hits=1,track_ttl=90)
            scene_events = self.wide_detector.process_frame(frame)
            elapsed = self.wide_detector.last_inference_seconds
            h,w = frame.shape[:2]
            grouped = {seat:[] for seat in self.seats}
            objects = []
            for event in scene_events:
                if event.confidence < (.50 if event.type=='PHONE_DETECTED' else .60):
                    continue
                box = [v/(h if i%2 else w) for i,v in enumerate(event.box)]
                seat = assign_box(box,self.regions)
                if seat is None:
                    continue
                # Global and crop tracker IDs have independent confirmation
                # histories, even when both trackers issue numeric ID 1.
                identity = f'wide:{event.track_id}'
                grouped[seat].append(replace(event,track_id=identity))
                objects.append(dict(label=event.label,type=event.type,confidence=event.confidence,
                    track_id=identity,confirmed=True,box=box,seat_number=seat))
            if objects:
                self.wide_samples += 1
                return None, grouped, objects, elapsed, None
            # No global recognition: old global positives must not bridge this
            # negative scene, while the independently sampled crop can continue.
            for target in self.seats.values():
                for key in list(target.histories):
                    if isinstance(key[1],str) and key[1].startswith('wide:'):
                        target.histories.pop(key)
        self.wide_samples = 0
        region = self.regions[self.cursor]
        target = self.seats[region.seat_number]
        h,w = frame.shape[:2]
        x1,y1,x2,y2 = [round(v*(h if i%2 else w)) for i,v in enumerate(region.box)]
        crop = frame[y1:y2,x1:x2].copy()
        if min(crop.shape[:2]) < 64:
            target.histories.clear()
            self.cursor = (self.cursor+1)%len(self.regions)
            self.focused_samples = 0
            self.focused_started = None
            return target, [], [], elapsed, 'Region is too small in the camera image; improve camera coverage.'
        if target.detector is None:
            target.detector = PhoneDetector(model=model,use_tiling=False,full_imgsz=640,min_hits=1,track_ttl=90)
        events = target.detector.process_frame(crop)
        events = [e for e in events if e.confidence >= (.50 if e.type=='PHONE_DETECTED' else .60)]
        objects = []
        for event in events:
            local = event.box
            # Edge-clipped detections cannot confidently establish ownership.
            if local[0]<=2 or local[1]<=2 or local[2]>=crop.shape[1]-2 or local[3]>=crop.shape[0]-2:
                continue
            box = [(local[0]+x1)/w,(local[1]+y1)/h,(local[2]+x1)/w,(local[3]+y1)/h]
            if assign_box(box,self.regions) != target.seat_number:
                continue
            objects.append(dict(label=event.label,type=event.type,confidence=event.confidence,
                                track_id=event.track_id,confirmed=True,box=box,seat_number=target.seat_number))
        valid_ids = {o['track_id'] for o in objects}
        events = [event for event in events if event.track_id in valid_ids]
        now = time.monotonic()
        if events:
            if not self.focused_samples:
                self.focused_started = now
            self.focused_samples += 1
        if not events or (self.focused_samples>=3 and now-self.focused_started>=3):
            self.cursor = (self.cursor+1)%len(self.regions)
            self.focused_samples = 0
            self.focused_started = None
        return target, events, objects, elapsed+target.detector.last_inference_seconds, None

    def evidence(self, frame, seat, *, objects=None):
        """Limit the saved snapshot to this student's camera region."""
        import cv2
        region = next(r for r in self.regions if r.seat_number==seat)
        h,w = frame.shape[:2]
        x1,y1,x2,y2 = [round(v*(h if i%2 else w)) for i,v in enumerate(region.box)]
        crop = frame[y1:y2,x1:x2].copy()
        for obj in objects or []:
            if obj['seat_number']!=seat:
                continue
            a,b,c,d = [round(v*(h if i%2 else w)) for i,v in enumerate(obj['box'])]
            cv2.rectangle(crop,(a-x1,b-y1),(c-x1,d-y1),(0,180,255),2)
            cv2.putText(crop,f"{obj['label']} {obj['confidence']:.0%}",(a-x1,max(40,b-y1-6)),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,180,255),2)
        cv2.putText(crop, f'Seat {seat}', (8,22), cv2.FONT_HERSHEY_SIMPLEX,.6,(80,210,100),2)
        return crop
