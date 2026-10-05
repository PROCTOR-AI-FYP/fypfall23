"""Focused crop verification must not promote an unrelated book."""
from unittest.mock import Mock

import numpy as np
import torch
from types import SimpleNamespace

from grounding_detector import GroundingModel, decode_classes
from phone_detector import PhoneDetector


def candidate(box, confidence):
    return torch.tensor(box, dtype=torch.float32), 1, confidence


def adapter(outputs):
    model = GroundingModel.__new__(GroundingModel)
    model.book_threshold = 0.6
    model._infer = Mock(side_effect=outputs)
    return model


def test_small_book_is_verified_at_its_original_frame_location():
    model = adapter([[candidate([620, 410, 700, 520], .4)],
                     [candidate([236, 202, 316, 312], .8)]])
    detector = PhoneDetector(model=model)
    found = detector.detect(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert len(found) == 1
    assert found[0].confidence > .79
    assert found[0].box == (620, 410, 700, 520)


def test_unrelated_book_in_refinement_crop_cannot_upgrade_weak_candidate():
    model = adapter([[candidate([620, 410, 700, 520], .4)],
                     [candidate([0, 0, 30, 30], .9)]])
    found = PhoneDetector(model=model).detect(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert len(found) == 1 and found[0].confidence < .6


def test_already_confident_book_needs_no_refinement():
    model = adapter([[candidate([620, 410, 700, 520], .8)]])
    PhoneDetector(model=model).detect(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert model._infer.call_count == 1


def test_small_phone_requires_verified_same_location_crop():
    weak=(torch.tensor([620.,410.,700.,520.]),0,.35)
    same=(torch.tensor([120.,105.,200.,215.]),0,.65)
    context=(torch.tensor([236.,202.,316.,312.]),0,.4)
    model=adapter([[weak],[context],[same]])
    found=PhoneDetector(model=model).detect(np.zeros((720,1280,3),dtype=np.uint8))
    assert len(found)==1 and found[0].confidence>.64
    assert found[0].box==(620,410,700,520)


def test_unrelated_phone_in_crop_does_not_upgrade_weak_scene_recognition():
    model=adapter([[(torch.tensor([620.,410.,700.,520.]),0,.35)],[],
                   [(torch.tensor([0.,0.,30.,30.]),0,.9)]])
    found=PhoneDetector(model=model).detect(np.zeros((720,1280,3),dtype=np.uint8))
    assert len(found)==1 and found[0].confidence<.5


def test_verified_context_book_cannot_be_promoted_to_phone():
    box=torch.tensor([620.,410.,700.,520.])
    local=torch.tensor([236.,202.,316.,312.])
    model=adapter([[(box,0,.4),(box,1,.3)],[(local,1,.8),(local,0,.9)]])
    found=PhoneDetector(model=model).detect(np.zeros((720,1280,3),dtype=np.uint8))
    assert model._infer.call_count==2
    assert not any(d.label=='phone' and d.confidence>=.5 for d in found)


def decode(probabilities):
    # Article, cell, phone, article, book, fabric: class confidence must
    # come from its nouns, even when another article crosses the threshold.
    outputs = SimpleNamespace(logits=torch.logit(torch.tensor([[probabilities]])),
                              pred_boxes=torch.tensor([[[.5, .5, .2, .4]]]))
    return decode_classes(outputs, [[1,2],[4],[5]], (100,200,3), .15)


def test_extra_article_does_not_discard_recognised_phone():
    found = decode([.49,.51,.508,.166,.142,.018])
    assert len(found) == 1 and found[0][1] == 0 and found[0][2] > .5
    assert torch.allclose(found[0][0],torch.tensor([80.,30.,120.,70.]))


def test_article_confidence_cannot_promote_weak_book():
    assert decode([.05,.02,.02,.8,.1,.02]) == []


def test_competing_fabric_does_not_become_book():
    assert decode([.01,.02,.02,.8,.4,.75]) == []


def test_close_class_scores_are_ambiguous():
    assert decode([.7,.75,.75,.7,.73,.05]) == []


def test_distinct_book_class_is_retained():
    found = decode([.05,.12,.13,.81,.8,.2])
    assert len(found)==1 and found[0][1]==1 and found[0][2] > .79
