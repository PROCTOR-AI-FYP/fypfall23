"""Focused crop verification must not promote an unrelated book."""
from unittest.mock import Mock
import importlib.util
from pathlib import Path

import numpy as np
import pytest
import torch
from types import SimpleNamespace

from grounding_detector import GroundingModel, decode_classes, cpu_thread_budget
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


@pytest.fixture(params=['desktop', 'backend'])
def thread_budget(request):
    if request.param == 'desktop':
        return cpu_thread_budget
    # Loading this standalone adapter does not load backend settings or a DB.
    path = Path(__file__).resolve().parents[1] / 'backend/app/vision/grounding.py'
    spec = importlib.util.spec_from_file_location('backend_grounding_cpu_budget_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cpu_thread_budget


def cgroup_reader(files):
    def read(path):
        if path not in files:
            raise FileNotFoundError(path)
        value = files[path]
        if isinstance(value, Exception):
            raise value
        return value
    return read


def test_unrestricted_cpu_preserves_existing_eight_thread_cap(thread_budget):
    assert thread_budget(32, cpu_count=32, affinity_count=32, reader=cgroup_reader({})) == 8
    assert thread_budget(2, cpu_count=32, affinity_count=32, reader=cgroup_reader({})) == 2


def test_affinity_and_physical_count_limit_the_budget(thread_budget):
    assert thread_budget(32, cpu_count=16, affinity_count=3, reader=cgroup_reader({})) == 3
    assert thread_budget(32, cpu_count=2, affinity_count=8, reader=cgroup_reader({})) == 2
    assert thread_budget(32, cpu_count=4, affinity_count=0, reader=cgroup_reader({})) == 4


@pytest.mark.parametrize('quota,expected', [('25000', 1), ('100000', 1), ('150000', 2), ('800000', 8), ('1200000', 8)])
def test_v2_cpu_quota_fraction_uses_ceiling_and_never_zero(thread_budget, quota, expected):
    files = {'/sys/fs/cgroup/cpu.max': quota + ' 100000'}
    assert thread_budget(32, cpu_count=32, affinity_count=32, reader=cgroup_reader(files)) == expected


@pytest.mark.parametrize('config', ['max 100000', '-1 100000', '0 100000', '100000 0', 'bad 100000', '100000', '100000 100000 extra', ''])
def test_unlimited_or_invalid_v2_quota_is_ignored(thread_budget, config):
    assert thread_budget(8, cpu_count=8, affinity_count=8, reader=cgroup_reader({'/sys/fs/cgroup/cpu.max': config})) == 8


def test_v2_nested_process_uses_smallest_ancestor_quota(thread_budget):
    files = {'/proc/self/cgroup': '0::/service/worker\n',
             '/sys/fs/cgroup/cpu.max': 'max 100000',
             '/sys/fs/cgroup/service/cpu.max': '150000 100000',
             '/sys/fs/cgroup/service/worker/cpu.max': '800000 100000'}
    assert thread_budget(32, cpu_count=32, affinity_count=32, reader=cgroup_reader(files)) == 2


@pytest.mark.parametrize('root', ['/sys/fs/cgroup/cpu', '/sys/fs/cgroup/cpu,cpuacct', '/sys/fs/cgroup/cpuacct,cpu'])
def test_v1_cpu_quota_and_controller_mounts_are_supported(thread_budget, root):
    files = {root + '/cpu.cfs_quota_us': '150000', root + '/cpu.cfs_period_us': '100000'}
    assert thread_budget(8, cpu_count=8, affinity_count=8, reader=cgroup_reader(files)) == 2


def test_v1_process_controller_uses_parent_quota(thread_budget):
    files = {'/proc/self/cgroup': '7:cpu,cpuacct:/department/exam\n',
             '/sys/fs/cgroup/cpu/department/cpu.cfs_quota_us': '25000',
             '/sys/fs/cgroup/cpu/department/cpu.cfs_period_us': '100000'}
    assert thread_budget(8, cpu_count=8, affinity_count=8, reader=cgroup_reader(files)) == 1


@pytest.mark.parametrize('files', [
    {'/sys/fs/cgroup/cpu/cpu.cfs_quota_us': '100000'},
    {'/sys/fs/cgroup/cpu/cpu.cfs_period_us': '100000'},
    {'/sys/fs/cgroup/cpu/cpu.cfs_quota_us': '-1', '/sys/fs/cgroup/cpu/cpu.cfs_period_us': '100000'},
    {'/sys/fs/cgroup/cpu/cpu.cfs_quota_us': '100000', '/sys/fs/cgroup/cpu/cpu.cfs_period_us': '0'},
    {'/proc/self/cgroup': PermissionError(), '/sys/fs/cgroup/cpu.max': PermissionError()},
    {'/proc/self/cgroup': 'invalid membership\n0::/../outside\n'},
])
def test_incomplete_inaccessible_and_unlimited_quota_falls_back_safely(thread_budget, files):
    assert thread_budget(8, cpu_count=8, affinity_count=4, reader=cgroup_reader(files)) == 4


def test_quota_cannot_increase_an_existing_thread_limit(thread_budget):
    files = {'/sys/fs/cgroup/cpu.max': '200000 100000'}
    assert thread_budget(1, cpu_count=8, affinity_count=8, reader=cgroup_reader(files)) == 1
    assert thread_budget(0, cpu_count=0, affinity_count=0, reader=cgroup_reader({})) == 1
