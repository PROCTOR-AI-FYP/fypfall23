"""Rolling per-seat signal buffers, alert triggering, and cooldowns.

Key scheme: buffer:{session_id}:{seat}:{signal} is a Redis list holding the
most recent BUFFER_WINDOW_FRAMES scores (LPUSH + LTRIM). A whole frame's
buffer writes and read-backs go out as one pipelined round trip, and the
cooldown claims for any triggered seats as a second one. Atomic per-buffer
updates reset interrupted streams and reject duplicate indices. Pipelining cuts
round trips, not billed commands; see app/redis_client.py for the Upstash
cost analysis.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field

import asyncpg

from app.models import BehaviourType
from app.redis_client import get_redis

BUFFER_WINDOW_FRAMES = 18  # 3 seconds at the worker's 6 FPS
BUFFER_TTL_SECONDS = 300
# LPUSH keeps an existing TTL, so refreshing it every ~10 s is enough and
# saves one command per seat-signal on the other frames.
BUFFER_TTL_REFRESH_EVERY_N_FRAMES = 60
TRIGGER_FRACTION = 0.6
TRIGGER_MIN_FRAMES = math.ceil(TRIGGER_FRACTION * BUFFER_WINDOW_FRAMES)
DETECTION_COOLDOWN_SECONDS = 30
CONFIG_TTL_SECONDS = 30.0

# Fallback when detection_thresholds is empty; schema.sql seeds the same values.
SIGNAL_THRESHOLDS: dict[BehaviourType, float] = {
    BehaviourType.GAZE_DEVIATION: 0.70,
    BehaviourType.HEAD_POSE_VIOLATION: 0.70,
    BehaviourType.LIP_MOVEMENT: 0.75,
    BehaviourType.PHONE_DETECTED: 0.80,
    BehaviourType.UNAUTHORISED_OBJECT: 0.80,
}


def threshold_for_sensitivity(sensitivity: int) -> float:
    """Admin sensitivity 0-100 -> per-frame score threshold (higher = more alerts)."""
    return round(1 - sensitivity / 100, 3)


@dataclass(frozen=True)
class DetectionConfig:
    thresholds: dict[BehaviourType, float] = field(default_factory=lambda: dict(SIGNAL_THRESHOLDS))
    # Composite weights; an empty map means "composite = strongest signal".
    weights: dict[BehaviourType, float] = field(default_factory=dict)

    def composite(self, signals: dict[BehaviourType, float]) -> float:
        if not signals:
            return 0.0
        if any(not math.isfinite(score) or not 0 <= score <= 1 for score in signals.values()):
            raise ValueError('Signal scores must be finite values between zero and one.')
        if any(not math.isfinite(weight) or weight < 0 for weight in self.weights.values()):
            raise ValueError('Signal weights must be finite and non-negative.')
        total_weight = sum(self.weights.get(signal, 0.0) for signal in signals)
        if total_weight <= 0:
            return 0.0 if self.weights else max(signals.values())
        return round(sum(score * self.weights.get(signal, 0.0) for signal, score in signals.items()) / total_weight, 3)


_config_cache: tuple[float, DetectionConfig] | None = None


async def get_detection_config(conn: asyncpg.Connection) -> DetectionConfig:
    """Admin thresholds, cached briefly (frames arrive ~6/s per room)."""
    global _config_cache
    now = time.monotonic()
    if _config_cache is not None and _config_cache[0] > now:
        return _config_cache[1]
    rows = await conn.fetch("SELECT behaviour_type, sensitivity, weight FROM detection_thresholds")
    config = DetectionConfig(
        thresholds={**SIGNAL_THRESHOLDS, **{BehaviourType(r["behaviour_type"]): threshold_for_sensitivity(r["sensitivity"]) for r in rows}},
        weights={BehaviourType(r["behaviour_type"]): float(r["weight"]) for r in rows},
    )
    _config_cache = (now + CONFIG_TTL_SECONDS, config)
    return config


def forget_detection_config() -> None:
    global _config_cache
    _config_cache = None


@dataclass(frozen=True)
class SeatSignals:
    seat_number: int
    signals: dict[BehaviourType, float]


@dataclass(frozen=True)
class TriggeredSeat:
    seat_number: int
    behaviour_types: list[BehaviourType]
    per_signal: dict[BehaviourType, float]
    composite_score: float


def buffer_key(session_id: str, seat_number: int, signal: BehaviourType) -> str:
    return f"buffer:{session_id}:{seat_number}:{signal.value}"


def cooldown_key(session_id: str, seat_number: int) -> str:
    return f"cooldown:{session_id}:{seat_number}"


async def record_frame(
    session_id: str, frame_index: int, seats: list[SeatSignals]
) -> dict[tuple[int, BehaviourType], list[float]]:
    """Append one frame's scores to every buffer and return the updated windows."""
    # A missing signal is an observed absence, not permission to retain an old
    # positive window across frames. Each observed seat advances every signal.
    entries = [(seat.seat_number, signal, seat.signals.get(signal, 0.0))
               for seat in seats for signal in BehaviourType]
    if any(not math.isfinite(score) or not 0 <= score <= 1 for _, _, score in entries):
        raise ValueError('Signal scores must be finite values between zero and one.')
    if not entries:
        return {}

    pipe = get_redis().pipeline(transaction=False)
    now = time.monotonic()
    script = '''
        local last=redis.call('GET',KEYS[2])
        if last then
            local index,stamp=string.match(last,'([^:]+):(.+)')
            local gap=tonumber(ARGV[3])-tonumber(stamp)
            if gap>=0 and gap<=2 and tonumber(ARGV[2])<=tonumber(index) then return {} end
            if gap<0 or gap>2 or tonumber(ARGV[2])~=tonumber(index)+1 then redis.call('DEL',KEYS[1]) end
        else
            redis.call('DEL',KEYS[1])
        end
        redis.call('SET',KEYS[2],ARGV[2]..':'..ARGV[3],'EX',ARGV[5])
        redis.call('LPUSH',KEYS[1],ARGV[1])
        redis.call('LTRIM',KEYS[1],0,tonumber(ARGV[4])-1)
        redis.call('EXPIRE',KEYS[1],ARGV[5])
        return redis.call('LRANGE',KEYS[1],0,tonumber(ARGV[4])-1)
    '''
    for seat_number, signal, score in entries:
        key = buffer_key(session_id, seat_number, signal)
        pipe.eval(script,2,key,key+':frame',f'{score:.3f}',frame_index,now,BUFFER_WINDOW_FRAMES,BUFFER_TTL_SECONDS)
    results = await pipe.execute()

    windows: dict[tuple[int, BehaviourType], list[float]] = {}
    for index, (seat_number, signal, _) in enumerate(entries):
        window = results[index]
        windows[(seat_number, signal)] = [float(value) for value in window]
    return windows


def evaluate_windows(
    windows: dict[tuple[int, BehaviourType], list[float]], config: DetectionConfig | None = None
) -> list[TriggeredSeat]:
    """A signal triggers when a full window has enough frames over its threshold."""
    config = config or DetectionConfig()
    per_seat: dict[int, dict[BehaviourType, float]] = defaultdict(dict)
    for (seat_number, signal), window in windows.items():
        if len(window) < BUFFER_WINDOW_FRAMES:
            continue
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in window):
            continue
        qualifying = [value for value in window if value >= config.thresholds[signal]]
        if len(qualifying) >= TRIGGER_MIN_FRAMES:
            # Persistence and signal strength are separate: absent frames must
            # not dilute an already qualified .80 recognition below .75.
            per_seat[seat_number][signal] = round(sum(qualifying) / len(qualifying), 3)

    return [
        TriggeredSeat(
            seat_number=seat_number,
            behaviour_types=sorted(signals, key=lambda s: s.value),
            per_signal=signals,
            composite_score=config.composite(signals),
        )
        for seat_number, signals in sorted(per_seat.items())
    ]


async def claim_cooldowns(session_id: str, triggered: list[TriggeredSeat]) -> list[TriggeredSeat]:
    """Keep only seats not already alerted within the cooldown window."""
    if not triggered:
        return []
    pipe = get_redis().pipeline(transaction=False)
    for seat in triggered:
        pipe.set(cooldown_key(session_id, seat.seat_number), "1", nx=True, ex=DETECTION_COOLDOWN_SECONDS)
    claimed = await pipe.execute()
    return [seat for seat, won in zip(triggered, claimed, strict=True) if won]


async def process_frame(
    session_id: str, frame_index: int, seats: list[SeatSignals], config: DetectionConfig | None = None
) -> list[TriggeredSeat]:
    windows = await record_frame(session_id, frame_index, seats)
    return await claim_cooldowns(session_id, evaluate_windows(windows, config))
