"""Motion, removal, delayed inference and bounded worker queue regressions."""
import threading
import time

import cv2
import numpy as np
import pytest

from phone_detector import BOOK, DetectionEvent, overlap
from realtime import InferenceSnapshot, RealtimeEngine, VisualTrack, gray_frame


@pytest.fixture
def frame():
    rng = np.random.default_rng(41)
    image = np.zeros((360, 640, 3), np.uint8)
    image[100:220, 100:180] = rng.integers(30, 240, (120, 80, 3), np.uint8)
    return image


def event():
    return DetectionEvent(BOOK, .8, 0, (100, 100, 180, 220), 'book', 1)


def shifted(frame, distance):
    return cv2.warpAffine(frame, np.float32([[1, 0, distance], [0, 1, 0]]), (640, 360))


def test_visual_track_follows_object_on_current_frame(frame):
    cv2.setNumThreads(1)
    track = VisualTrack.create(event(), gray_frame(frame), frame.shape, 0)
    assert track.advance(gray_frame(frame), gray_frame(shifted(frame, 30)))
    assert overlap(track.box, (130, 100, 210, 220)) > .95


def test_object_removal_drops_track_instead_of_drawing_stale_box(frame):
    track = VisualTrack.create(event(), gray_frame(frame), frame.shape, 0)
    assert not track.advance(gray_frame(frame), gray_frame(np.zeros_like(frame)))


def test_abrupt_movement_reacquires_using_current_appearance(frame):
    track = VisualTrack.create(event(), gray_frame(frame), frame.shape, 0)
    assert track.advance(gray_frame(frame), gray_frame(shifted(frame, 180)))
    assert overlap(track.box, (280, 100, 360, 220)) > .95


def test_different_textured_object_cannot_reacquire_old_track(frame):
    track = VisualTrack.create(event(), gray_frame(frame), frame.shape, 0)
    other = np.zeros_like(frame)
    other[100:220, 280:360] = np.random.default_rng(99).integers(30,240,(120,80,3),np.uint8)
    assert not track.advance(gray_frame(frame), gray_frame(other))


def test_rotated_scaled_object_is_reacquired_with_geometric_evidence(frame):
    transform = np.float32([[1.15,-.18,150],[.18,1.15,-30]])
    moved = cv2.warpAffine(frame,transform,(640,360))
    track = VisualTrack.create(event(),gray_frame(frame),frame.shape,0)
    assert track.advance(gray_frame(frame),gray_frame(moved))
    bounds = cv2.transform(np.float32([[[100,100],[180,100],[180,220],[100,220]]]),transform)[0]
    expected = (*bounds.min(axis=0),*bounds.max(axis=0))
    assert overlap(track.box,expected) > .85


def test_blurred_history_does_not_veto_object_visible_now(frame,blocked_engine):
    engine,started,_,_ = blocked_engine
    engine.update(frame,0)
    assert started.wait(2)
    engine.update(np.zeros_like(frame),.2)
    with engine._condition:
        engine._result = InferenceSnapshot(0,gray_frame(frame),frame.shape,(event(),),.01)
    events = engine.update(shifted(frame,180),.3)
    assert len(events)==1 and overlap(events[0].box,(280,100,360,220)) > .95


def test_two_semantic_checks_survive_visual_track_reinitialization(frame,blocked_engine):
    engine,started,_,_ = blocked_engine
    engine._min_semantic_hits = 2
    engine.update(frame,0)
    assert started.wait(2)
    verified = DetectionEvent(BOOK,.8,0,event().box,'book',1,semantic_hits=2)
    with engine._condition:
        engine._result = InferenceSnapshot(0,gray_frame(frame),frame.shape,(verified,),.01)
    events = engine.update(frame,.1)
    assert len(events)==1


def test_one_semantic_hit_cannot_be_counted_twice(frame,blocked_engine):
    engine,started,_,_ = blocked_engine
    engine._min_semantic_hits = 2
    engine.update(frame,0)
    assert started.wait(2)
    single = DetectionEvent(BOOK,.8,0,event().box,'book',1,semantic_hits=1)
    with engine._condition:
        engine._result = InferenceSnapshot(0,gray_frame(frame),frame.shape,(single,),.01)
    assert not engine.update(frame,.1)


@pytest.fixture
def blocked_engine():
    release, started = threading.Event(), threading.Event()
    processed = []
    class Detector:
        last_inference_seconds = .01
        def process_frame(self, frame, timestamp):
            processed.append(timestamp)
            started.set()
            release.wait(5)
            return []
    engine = RealtimeEngine(Detector, min_semantic_hits=1)
    assert engine.wait_ready(2)
    yield engine, started, release, processed
    release.set()
    engine.close()


def test_old_detection_is_aligned_to_live_motion(frame, blocked_engine):
    engine, started, _, _ = blocked_engine
    engine.update(frame, 0)
    assert started.wait(2)
    for i in range(1, 4):
        engine.update(shifted(frame, i * 10), i * .2)
    with engine._condition:
        engine._result = InferenceSnapshot(0, gray_frame(frame), frame.shape, (event(),), .01)
    events = engine.update(shifted(frame, 30), .7)
    assert len(events) == 1
    assert overlap(events[0].box, (130, 100, 210, 220)) > .95
    assert not engine.update(np.zeros_like(frame), .8)


def test_delayed_detection_does_not_resurrect_removed_object(frame, blocked_engine):
    engine, started, _, _ = blocked_engine
    engine.update(frame, 0)
    assert started.wait(2)
    empty = np.zeros_like(frame)
    engine.update(empty, .2)
    with engine._condition:
        engine._result = InferenceSnapshot(0, gray_frame(frame), frame.shape, (event(),), .01)
    assert not engine.update(empty, .3)


def test_queue_replaces_old_pending_frames_while_inference_is_busy(frame, blocked_engine):
    engine, started, release, processed = blocked_engine
    engine.update(frame, 0)
    assert started.wait(2)
    for i in range(1, 11):
        engine.update(frame, float(i))
    with engine._condition:
        assert engine._pending[1] == 10
    assert processed == [0]
    release.set()
    deadline = time.monotonic() + 2
    while len(processed) < 2 and time.monotonic() < deadline:
        time.sleep(.01)
    assert processed[:2] == [0, 10]


def test_tracks_expire_without_semantic_refresh(frame, blocked_engine):
    engine, started, _, _ = blocked_engine
    engine.update(frame, 0)
    assert started.wait(2)
    with engine._condition:
        engine._result = InferenceSnapshot(0, gray_frame(frame), frame.shape, (event(),), .01)
    assert engine.update(frame, .1)
    assert not engine.update(frame, 9)


def test_slow_inference_is_reconciled_against_current_image(frame, blocked_engine):
    engine, started, _, _ = blocked_engine
    engine.update(frame,0)
    assert started.wait(2)
    engine.update(frame,10)
    with engine._condition:
        engine._result = InferenceSnapshot(0,gray_frame(frame),frame.shape,(event(),),10.)
    assert engine.update(frame,10.1)
    assert engine.update(frame,11)
    assert engine.rejected_age == 0


def test_slow_inference_cannot_resurrect_removed_object(frame, blocked_engine):
    engine, started, _, _ = blocked_engine
    engine.update(frame,0)
    assert started.wait(2)
    empty = np.zeros_like(frame)
    engine.update(empty,10)
    with engine._condition:
        engine._result = InferenceSnapshot(0,gray_frame(frame),frame.shape,(event(),),10.)
    assert not engine.update(empty,10.1)
    assert engine.rejected_alignment == 1


def test_unbounded_old_inference_is_rejected(frame, blocked_engine):
    engine, started, _, _ = blocked_engine
    engine.update(frame,0)
    assert started.wait(2)
    with engine._condition:
        engine._result = InferenceSnapshot(0,gray_frame(frame),frame.shape,(event(),),31.)
    assert not engine.update(frame,31)
    assert engine.rejected_age == 1


def test_tighter_ai_box_replaces_containing_track_instead_of_duplicate(frame, blocked_engine):
    engine, started, _, _ = blocked_engine
    engine.update(frame,0)
    assert started.wait(2)
    with engine._condition:
        engine._result = InferenceSnapshot(0,gray_frame(frame),frame.shape,(event(),),.01)
    original = engine.update(frame,.1)
    tighter = DetectionEvent(BOOK,.8,0,(110,110,150,170),'book',99,semantic_hits=2)
    with engine._condition:
        engine._result = InferenceSnapshot(.1,gray_frame(frame),frame.shape,(tighter,),.01)
    updated = engine.update(frame,.2)
    assert len(updated)==1 and updated[0].track_id==original[0].track_id


def test_loading_failure_is_reported_without_blocking_camera(frame):
    def fail():
        raise ValueError('missing test model')
    engine = RealtimeEngine(fail)
    try:
        assert not engine.wait_ready(2)
        assert 'missing test model' in engine.error
        assert engine.update(frame, 0) == []
    finally:
        engine.close()


def test_confirmation_follows_moving_object_even_when_ai_changes_id(frame, blocked_engine):
    engine, started, _, _ = blocked_engine
    engine._min_semantic_hits = 2
    engine.update(frame, 0)
    assert started.wait(2)
    with engine._condition:
        engine._result = InferenceSnapshot(0, gray_frame(frame), frame.shape, (event(),), .01)
    assert not engine.update(frame, .1)
    for i in range(1, 5):
        moved = shifted(frame, i*20)
        engine.update(moved, .1+i*.1)
    second = DetectionEvent(BOOK, .8, 0, (180,100,260,220), 'book', 99)
    with engine._condition:
        engine._result = InferenceSnapshot(.5, gray_frame(moved), moved.shape, (second,), .01)
    events = engine.update(moved, .6)
    assert len(events) == 1 and events[0].track_id == 1
    assert overlap(events[0].box, second.box) > .95


def test_weak_second_ai_observation_cannot_confirm_provisional_track(frame, blocked_engine):
    engine, started, _, _ = blocked_engine
    engine._min_semantic_hits = 2
    engine.update(frame, 0)
    assert started.wait(2)
    with engine._condition:
        engine._result = InferenceSnapshot(0, gray_frame(frame), frame.shape, (event(),), .01)
    assert not engine.update(frame, .1)
    weak = DetectionEvent(BOOK,.2,0,event().box,'book',1)
    with engine._condition:
        engine._result = InferenceSnapshot(.1,gray_frame(frame),frame.shape,(weak,),.01)
    assert not engine.update(frame, .2)
