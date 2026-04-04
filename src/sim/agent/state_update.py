import random

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

# Extreme emotions that should decay
EXTREME_EMOTIONS = {
    Emotion.ANGRY, Emotion.EXCITED, Emotion.SAD,
    Emotion.EMBARRASSED, Emotion.JEALOUS, Emotion.GUILTY,
    Emotion.FRUSTRATED, Emotion.TOUCHED,
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
    exam_shock: int = 0,
    days_since_exam: int | None = None,
) -> AgentState:
    base = PRESSURE_BASE[pressure_level]

    # Exam countdown pressure
    if next_exam_in_days <= 3:
        countdown_delta = 15
    elif next_exam_in_days <= 7:
        countdown_delta = 8
    elif next_exam_in_days <= 14:
        countdown_delta = 3
    else:
        countdown_delta = 0

    # Post-exam recovery
    recovery = 0
    if days_since_exam is not None and days_since_exam >= 0:
        if days_since_exam == 0:
            recovery = -(state.academic_pressure - base)  # Reset to base
        else:
            recovery = -2 * days_since_exam

    pressure = base + countdown_delta + exam_shock + recovery
    state.academic_pressure = clamp(pressure, 0, 100)
    return state


def decay_concerns(state: AgentState) -> AgentState:
    """Decay all concern intensities by 1 per day. Remove when <= 0."""
    surviving = []
    for c in state.active_concerns:
        c.intensity -= 1
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
    if state.emotion in EXTREME_EMOTIONS and scenes_since_extreme >= 2:
        if rng.random() < 0.5:
            state.emotion = Emotion.NEUTRAL
    return state


def regress_relationships(rels: RelationshipFile) -> RelationshipFile:
    """Nudge favorability and trust 1 point toward zero daily."""
    for rel in rels.relationships.values():
        if rel.favorability > 0:
            rel.favorability -= 1
        elif rel.favorability < 0:
            rel.favorability += 1
        if rel.trust > 0:
            rel.trust -= 1
        elif rel.trust < 0:
            rel.trust += 1
    return rels
