"""Geometry, model output, tracking and alert regressions; no network/camera."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from phone_detector import BOOK, PHONE, ObjectDetection, PhoneDetector, merge_detections, tile_regions
from composite_scorer import CompositeScorer


class Tensor:
    def __init__(self, values):
        self.values = np.asarray(values)
    def cpu(self):
        return self
    def numpy(self):
        return self.values


def result(rows=()):
    return SimpleNamespace(boxes=SimpleNamespace(xyxy=Tensor([r[:4] for r in rows]),
                                                cls=Tensor([r[4] for r in rows]),
                                                conf=Tensor([r[5] for r in rows])))


def model(names=None):
    return SimpleNamespace(names=names or {0: 'book', 1: 'cell phone', 2: 'person'},
                           predict=Mock(side_effect=lambda images, **kwargs: [result() for _ in images]))


def detection(signal=PHONE, score=0.7, box=(10, 10, 40, 60)):
    return ObjectDetection(signal, score, box, 'phone' if signal == PHONE else 'book')


@pytest.fixture
def detector():
    return PhoneDetector(model=model())


@pytest.fixture
def frame():
    return np.zeros((100, 100, 3), dtype=np.uint8)


def test_model_class_ids_are_resolved_by_name():
    assert PhoneDetector(model=model({67: 'cell phone', 73: 'book'})).class_signals == {67: PHONE, 73: BOOK}


def test_descriptive_book_classes_are_resolved_by_exact_name():
    assert PhoneDetector(model=model({0: 'smartphone', 1: 'hardcover book', 2: 'person'})).class_signals == {0: PHONE, 1: BOOK}


def test_unsupported_checkpoint_fails_instead_of_silently_disabling_books():
    with pytest.raises(ValueError, match='phones AND books'):
        PhoneDetector(model=model({0: 'person', 1: 'laptop'}))


@pytest.mark.parametrize('kwargs', [{'conf_threshold': 1.1}, {'candidate_threshold': 0.7},
                                    {'tile_size': 0}, {'overlap_ratio': 1}, {'min_hits': 0}])
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        PhoneDetector(model=model(), **kwargs)


def test_slices_cover_every_pixel_and_include_edges():
    regions = tile_regions(1920, 1080)
    coverage = np.zeros((1080, 1920), dtype=bool)
    for x1, y1, x2, y2 in regions:
        assert 0 <= x1 < x2 <= 1920 and 0 <= y1 < y2 <= 1080
        assert x2 - x1 <= 640 and y2 - y1 <= 640
        coverage[y1:y2, x1:x2] = True
    assert coverage.all()
    assert len(regions) == len(set(regions))


def test_overlapping_predictions_merge_without_merging_phone_with_book():
    candidates = [detection(), detection(score=0.5, box=(12, 12, 39, 59)), detection(BOOK)]
    assert len(merge_detections(candidates)) == 2


def test_full_frame_plus_crop_offsets_are_preserved():
    fake = model()
    detector = PhoneDetector(model=fake, tile_size=640, min_hits=1, full_imgsz=960)
    fake.predict.side_effect = [[result()], [result(), result([(5, 10, 25, 50, 0, 0.8)])]]
    found = detector.detect(np.zeros((480, 960, 3), dtype=np.uint8))
    assert found[0].type == BOOK
    assert found[0].box == (325, 10, 345, 50)
    assert fake.predict.call_args_list[0].kwargs['imgsz'] == 960
    assert fake.predict.call_args_list[1].kwargs['imgsz'] == 640


def test_phone_and_book_reach_composite_alert(detector, frame):
    detector.detect = Mock(return_value=[detection(), detection(BOOK, box=(60, 60, 90, 90))])
    scorer = CompositeScorer()
    alert = None
    for i in range(20):
        events = detector.process_frame(frame, timestamp=i / 6)
        alert = scorer.update({event.type for event in events}, timestamp=i / 6)
    assert alert and {PHONE, BOOK} <= set(alert.active_signals)
    book_only = CompositeScorer()
    for i in range(18):
        alert = book_only.update({BOOK}, i / 6)
    assert alert.score == 0.75


def test_single_frame_and_repeated_low_confidence_do_not_confirm(detector, frame):
    detector.detect = Mock(side_effect=[[detection()]] + [[detection(score=0.2)]] * 6)
    assert all(not detector.process_frame(frame, timestamp=i / 6) for i in range(7))


def test_confidence_dip_keeps_track_but_absent_object_never_emits(detector, frame):
    detector.detect = Mock(side_effect=[[detection()], [detection()], [detection(score=0.2)], [],
                                       [detection(score=0.25)]])
    assert not detector.process_frame(frame, 0)
    first = detector.process_frame(frame, 0.2)[0]
    assert detector.process_frame(frame, 0.4)[0].track_id == first.track_id
    assert not detector.process_frame(frame, 0.6)
    assert detector.process_frame(frame, 0.8)[0].track_id == first.track_id


def test_expired_track_requires_confirmation_again(detector, frame):
    detector.detect = Mock(return_value=[detection()])
    detector.process_frame(frame, 0)
    assert detector.process_frame(frame, 0.2)
    assert not detector.process_frame(frame, detector.track_ttl + 1)


def test_three_missing_frames_force_new_confirmation(detector, frame):
    detector.detect = Mock(side_effect=[[detection()], [detection()], [], [], [], [detection()], [detection()]])
    events = [detector.process_frame(frame, i / 6) for i in range(7)]
    assert not any(events[2:6])
    assert events[1][0].track_id != events[6][0].track_id


def test_two_phones_have_independent_tracks(detector, frame):
    detector.detect = Mock(return_value=[detection(), detection(box=(60, 60, 90, 95))])
    detector.process_frame(frame, 0)
    assert len({event.track_id for event in detector.process_frame(frame, 0.2)}) == 2


def test_annotation_never_calls_model_again(detector, frame):
    detector.process_frame(frame, 0)
    count = detector.model.predict.call_count
    detector.annotate_frame(frame)
    detector.annotate_frame(frame)
    assert detector.model.predict.call_count == count


def test_model_output_is_normalized_and_irrelevant_objects_are_ignored(frame):
    fake = model()
    fake.predict.side_effect = None
    fake.predict.return_value = [result([(5, 5, 20, 30, 1, 0.8), (40, 40, 90, 90, 0, 0.9),
                                        (0, 0, 100, 100, 2, 0.99)])]
    detector = PhoneDetector(model=fake, min_hits=1)
    assert {e.type for e in detector.process_frame(frame)} == {PHONE, BOOK}
