"""Review score boundaries and temporal guards, without model-probability claims."""
from types import SimpleNamespace
import math

import pytest

from app.models import BehaviourType as B
from app.services import detection as scoring
from app.services.device_camera import DeviceRun, object_signal_score
from tests.test_detection_pipeline import active_session  # noqa: F401


def test_empty_zero_weight_and_disabled_weight_scores():
    assert scoring.DetectionConfig().composite({}) == 0
    assert scoring.DetectionConfig(weights={B.PHONE_DETECTED:0}).composite({B.PHONE_DETECTED:.99}) == 0
    config=scoring.DetectionConfig(weights={B.PHONE_DETECTED:1,B.HEAD_POSE_VIOLATION:0})
    assert config.composite({B.PHONE_DETECTED:.8,B.HEAD_POSE_VIOLATION:1}) == .8


@pytest.mark.parametrize('value',[math.nan,math.inf,-math.inf,-.001,1.001])
def test_nonfinite_or_out_of_range_scores_cannot_reach_cases(value):
    with pytest.raises(ValueError):scoring.DetectionConfig().composite({B.PHONE_DETECTED:value})
    with pytest.raises(ValueError):object_signal_score('PHONE_DETECTED',value)
    assert not scoring.evaluate_windows({(1,B.PHONE_DETECTED):[value]*18})


def test_qualifying_persistence_does_not_dilute_strength():
    window=[.81]*scoring.TRIGGER_MIN_FRAMES+[0.]*(18-scoring.TRIGGER_MIN_FRAMES)
    result=scoring.evaluate_windows({(1,B.PHONE_DETECTED):window})
    assert result[0].composite_score == .81
    assert not scoring.evaluate_windows({(1,B.PHONE_DETECTED):[.81]*10+[0.]*8})


def test_strongest_verified_track_wins_and_missing_tracks_reset():
    run=DeviceRun('teacher');config=scoring.DetectionConfig()
    events=[SimpleNamespace(type='PHONE_DETECTED',confidence=c,track_id=i) for i,c in [(1,.99),(2,.51)]]
    for now in [0,1.5,3]:result=run.observe(events,now,config)
    assert result['PHONE_DETECTED']==pytest.approx(object_signal_score('PHONE_DETECTED',.99))
    assert run.observe([],4,config) is None and not run.histories


def test_admin_sensitivity_cannot_promote_weak_neural_candidates():
    config=scoring.DetectionConfig(thresholds={**scoring.SIGNAL_THRESHOLDS,B.PHONE_DETECTED:.1})
    run=DeviceRun('teacher');event=SimpleNamespace(type='PHONE_DETECTED',confidence=.3,track_id=1)
    for now in [0,2,4]:assert run.observe([event],now,config) is None


async def test_absent_signals_advance_zero_and_replays_do_not_advance(client,active_session):
    seat=scoring.SeatSignals(14,{B.PHONE_DETECTED:.9})
    first=await scoring.record_frame(active_session,0,[seat])
    assert first[(14,B.PHONE_DETECTED)]==[.9]
    replay=await scoring.record_frame(active_session,0,[seat])
    assert replay[(14,B.PHONE_DETECTED)]==[]
    window=await scoring.record_frame(active_session,1,[scoring.SeatSignals(14,{})])
    assert window[(14,B.PHONE_DETECTED)]==[0.,.9]
    gap=await scoring.record_frame(active_session,4,[seat])
    assert gap[(14,B.PHONE_DETECTED)]==[.9]
