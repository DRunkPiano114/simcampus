import random

from ..config import settings
from ..models.agent import AgentState, Emotion, PressureLevel
from ..models.relationship import RelationshipFile


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


# Energy changes by scene type
ENERGY_DELTA = {
    "上课": -5,
    "早读": -3,
    "晚自习": -5,
    "课间": 5,
    "午饭": 15,
    "宿舍夜聊": -5,
}

# Triggers orchestrator re-plan (orchestrator.py:558).
# Keep narrow to avoid re-plan storms.
EXTREME_EMOTIONS = {
    Emotion.ANGRY, Emotion.EXCITED, Emotion.SAD,
    Emotion.EMBARRASSED, Emotion.JEALOUS, Emotion.GUILTY,
    Emotion.FRUSTRATED, Emotion.TOUCHED,
}

# Used only by maybe_decay_emotion (end-of-day reset).
# Wider set: includes low-arousal stuck states that should also decay overnight.
DECAYABLE_EMOTIONS = EXTREME_EMOTIONS | {
    Emotion.ANXIOUS,
    Emotion.BORED,
}

# Base pressure by family background
PRESSURE_BASE = {
    PressureLevel.HIGH: 50,
    PressureLevel.MEDIUM: 30,
    PressureLevel.LOW: 15,
}


def update_energy(state: AgentState, scene_name: str) -> AgentState:
    delta = ENERGY_DELTA.get(scene_name, 0)
    state.energy = clamp(state.energy + delta, 0, 100)
    return state


def reset_energy_for_sleep(state: AgentState) -> AgentState:
    state.energy = 85
    return state


def update_academic_pressure(
    state: AgentState,
    pressure_level: PressureLevel,
    next_exam_in_days: int,
    days_since_exam: int | None = None,
) -> AgentState:
    base = PRESSURE_BASE[pressure_level]

    # Post-exam day 0: reset to base immediately
    if days_since_exam is not None and days_since_exam == 0:
        state.academic_pressure = clamp(base, 0, 100)
        return state

    # Exam countdown pressure
    if next_exam_in_days <= 3:
        countdown_delta = 15
    elif next_exam_in_days <= 7:
        countdown_delta = 8
    elif next_exam_in_days <= 14:
        countdown_delta = 3
    else:
        countdown_delta = 0

    # Post-exam recovery (days 1+)
    recovery = 0
    if days_since_exam is not None and days_since_exam > 0:
        recovery = -2 * days_since_exam

    pressure = base + countdown_delta + recovery
    state.academic_pressure = clamp(pressure, 0, 100)
    return state


def decay_concerns(state: AgentState, today: int) -> AgentState:
    """Decay concerns at end-of-day, dropping stale and zero-intensity ones.

    A concern is stale when no scene has reinforced it within
    `settings.concern_stale_days`. Remaining concerns lose
    `settings.concern_decay_per_day` intensity per day; any reaching 0
    are removed.
    """
    surviving = []
    for c in state.active_concerns:
        if (today - c.last_reinforced_day) >= settings.concern_stale_days:
            continue
        c.intensity = max(0, c.intensity - settings.concern_decay_per_day)
        if c.intensity > 0:
            surviving.append(c)
    state.active_concerns = surviving
    return state


def maybe_decay_emotion(
    state: AgentState,
    scenes_since_extreme: int,
    rng: random.Random | None = None,
) -> AgentState:
    rng = rng or random.Random()
    if state.emotion in DECAYABLE_EMOTIONS and scenes_since_extreme >= 2:
        if rng.random() < 0.5:
            state.emotion = Emotion.NEUTRAL
    return state


def regress_relationships(rels: RelationshipFile) -> RelationshipFile:
    """Asymmetric daily regression.

    Negative relationships heal every day (nudge toward 0).
    Positive relationships only decay after N days without interaction.
    Understanding never regresses.
    """
    for rel in rels.relationships.values():
        # Negative → heal every day
        if rel.favorability < 0:
            rel.favorability = min(0, rel.favorability + 1)
        if rel.trust < 0:
            rel.trust = min(0, rel.trust + 1)

        # Positive → decay only when stale
        if rel.days_since_interaction >= settings.relationship_positive_stale_days:
            if rel.favorability > 0:
                rel.favorability -= 1
            if rel.trust > 0:
                rel.trust -= 1

        rel.days_since_interaction += 1
    return rels
