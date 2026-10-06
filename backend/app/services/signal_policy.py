"""Shared review strength for verified object detections; overlays stay raw."""
import math


def object_signal_score(signal: str, model_confidence: float) -> float:
    """Map class verification confidence to review strength, not guilt likelihood."""
    if signal not in ('PHONE_DETECTED', 'UNAUTHORISED_OBJECT'):
        raise ValueError('Unsupported object signal')
    if not math.isfinite(model_confidence) or not 0 <= model_confidence <= 1:
        raise ValueError('Invalid model confidence')
    floor = .50 if signal == 'PHONE_DETECTED' else .60
    if model_confidence <= floor:
        return round(.8 * model_confidence / floor, 3)
    return round(min(1., .8 + .2 * (model_confidence-floor)/(1-floor)), 3)
