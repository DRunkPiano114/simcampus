"""Tests for agent state update functions."""

from random import Random

from sim.agent.state_update import (
    ENERGY_DELTA,
    EXTREME_EMOTIONS,
    clamp,
    decay_concerns,
    maybe_decay_emotion,
    regress_relationships,
    reset_energy_for_sleep,
    update_academic_pressure,
    update_energy,
)
from sim.models.agent import ActiveConcern, AgentState, Emotion, PressureLevel
from sim.models.relationship import Relationship, RelationshipFile


# --- clamp ---

def test_clamp_within_range():
    assert clamp(50, 0, 100) == 50


def test_clamp_below_minimum():
    assert clamp(-10, 0, 100) == 0


def test_clamp_above_maximum():
    assert clamp(150, 0, 100) == 100


def test_clamp_at_boundaries():
    assert clamp(0, 0, 100) == 0
    assert clamp(100, 0, 100) == 100


# --- update_energy ---

def test_update_energy_class():
    state = AgentState(energy=80)
    update_energy(state, "上课")
    assert state.energy == 75  # 80 - 5


def test_update_energy_break():
    state = AgentState(energy=50)
    update_energy(state, "课间")
    assert state.energy == 55  # 50 + 5


def test_update_energy_lunch():
    state = AgentState(energy=40)
    update_energy(state, "午饭")
    assert state.energy == 55  # 40 + 15


def test_update_energy_unknown_scene():
    state = AgentState(energy=50)
    update_energy(state, "unknown_scene")
    assert state.energy == 50  # No change


def test_update_energy_clamps_at_zero():
    state = AgentState(energy=3)
    update_energy(state, "上课")
    assert state.energy == 0  # 3 - 5 → clamped to 0


def test_update_energy_clamps_at_hundred():
    state = AgentState(energy=95)
    update_energy(state, "午饭")
    assert state.energy == 100  # 95 + 15 → clamped to 100


def test_all_energy_deltas_covered():
    """Verify every scene type in ENERGY_DELTA works."""
    for scene_name, delta in ENERGY_DELTA.items():
        state = AgentState(energy=50)
        update_energy(state, scene_name)
        assert state.energy == clamp(50 + delta, 0, 100)


# --- reset_energy_for_sleep ---

def test_reset_energy_for_sleep():
    state = AgentState(energy=20)
    reset_energy_for_sleep(state)
    assert state.energy == 85


def test_reset_energy_already_high():
    state = AgentState(energy=95)
    reset_energy_for_sleep(state)
    assert state.energy == 85


# --- update_academic_pressure ---

def test_pressure_base_by_level():
    for level, expected_base in [
        (PressureLevel.HIGH, 50),
        (PressureLevel.MEDIUM, 30),
        (PressureLevel.LOW, 15),
    ]:
        state = AgentState(academic_pressure=0)
        update_academic_pressure(state, level, next_exam_in_days=30)
        assert state.academic_pressure == expected_base


def test_pressure_exam_countdown_3_days():
    state = AgentState(academic_pressure=0)
    update_academic_pressure(state, PressureLevel.MEDIUM, next_exam_in_days=3)
    assert state.academic_pressure == 30 + 15  # base + countdown


def test_pressure_exam_countdown_7_days():
    state = AgentState(academic_pressure=0)
    update_academic_pressure(state, PressureLevel.MEDIUM, next_exam_in_days=7)
    assert state.academic_pressure == 30 + 8


def test_pressure_exam_countdown_14_days():
    state = AgentState(academic_pressure=0)
    update_academic_pressure(state, PressureLevel.MEDIUM, next_exam_in_days=14)
    assert state.academic_pressure == 30 + 3


def test_pressure_exam_far():
    state = AgentState(academic_pressure=0)
    update_academic_pressure(state, PressureLevel.MEDIUM, next_exam_in_days=20)
    assert state.academic_pressure == 30  # base only


def test_pressure_post_exam_day0_resets():
    """Day 0 after exam: pressure resets to base regardless of current value."""
    state = AgentState(academic_pressure=80)
    update_academic_pressure(state, PressureLevel.MEDIUM, next_exam_in_days=30, days_since_exam=0)
    assert state.academic_pressure == 30  # Reset to MEDIUM base


def test_pressure_post_exam_day0_resets_high():
    state = AgentState(academic_pressure=95)
    update_academic_pressure(state, PressureLevel.HIGH, next_exam_in_days=30, days_since_exam=0)
    assert state.academic_pressure == 50  # Reset to HIGH base


def test_pressure_post_exam_recovery():
    state = AgentState(academic_pressure=50)
    update_academic_pressure(state, PressureLevel.MEDIUM, next_exam_in_days=30, days_since_exam=3)
    # base(30) + countdown(0) + recovery(-6) = 24
    assert state.academic_pressure == 24


def test_pressure_clamped_to_100():
    state = AgentState(academic_pressure=0)
    update_academic_pressure(state, PressureLevel.HIGH, next_exam_in_days=1)
    # 50 + 15 = 65
    assert state.academic_pressure == 65


# --- decay_concerns ---

def test_decay_concerns_reduces_intensity():
    state = AgentState(active_concerns=[
        ActiveConcern(text="test", intensity=5),
        ActiveConcern(text="test2", intensity=3),
    ])
    decay_concerns(state)
    assert state.active_concerns[0].intensity == 4
    assert state.active_concerns[1].intensity == 2


def test_decay_concerns_removes_at_zero():
    state = AgentState(active_concerns=[
        ActiveConcern(text="will_survive", intensity=2),
        ActiveConcern(text="will_die", intensity=1),
    ])
    decay_concerns(state)
    assert len(state.active_concerns) == 1
    assert state.active_concerns[0].text == "will_survive"


def test_decay_concerns_empty():
    state = AgentState(active_concerns=[])
    decay_concerns(state)
    assert state.active_concerns == []


# --- maybe_decay_emotion ---

def test_emotion_decay_extreme_resets():
    """With rng < 0.5, extreme emotion resets to NEUTRAL."""
    rng = Random(0)
    # Find a seed where random() < 0.5
    for seed in range(100):
        rng = Random(seed)
        if rng.random() < 0.5:
            rng = Random(seed)
            break
    state = AgentState(emotion=Emotion.ANGRY)
    maybe_decay_emotion(state, scenes_since_extreme=2, rng=rng)
    assert state.emotion == Emotion.NEUTRAL


def test_emotion_decay_not_enough_scenes():
    """Extreme emotion doesn't decay if < 2 scenes."""
    state = AgentState(emotion=Emotion.ANGRY)
    rng = Random(42)
    maybe_decay_emotion(state, scenes_since_extreme=1, rng=rng)
    assert state.emotion == Emotion.ANGRY


def test_emotion_decay_non_extreme_stays():
    """Non-extreme emotions never decay."""
    state = AgentState(emotion=Emotion.HAPPY)
    rng = Random(42)
    maybe_decay_emotion(state, scenes_since_extreme=5, rng=rng)
    assert state.emotion == Emotion.HAPPY


def test_all_extreme_emotions_classified():
    """Verify the set of extreme emotions is what we expect."""
    assert Emotion.ANGRY in EXTREME_EMOTIONS
    assert Emotion.EXCITED in EXTREME_EMOTIONS
    assert Emotion.SAD in EXTREME_EMOTIONS
    assert Emotion.EMBARRASSED in EXTREME_EMOTIONS
    assert Emotion.JEALOUS in EXTREME_EMOTIONS
    assert Emotion.GUILTY in EXTREME_EMOTIONS
    assert Emotion.FRUSTRATED in EXTREME_EMOTIONS
    assert Emotion.TOUCHED in EXTREME_EMOTIONS
    # Non-extreme
    assert Emotion.NEUTRAL not in EXTREME_EMOTIONS
    assert Emotion.HAPPY not in EXTREME_EMOTIONS
    assert Emotion.CALM not in EXTREME_EMOTIONS


# --- regress_relationships ---

def test_regress_positive_relationships():
    rels = RelationshipFile(relationships={
        "b": Relationship(target_name="B", target_id="b", favorability=10, trust=5),
    })
    regress_relationships(rels)
    assert rels.relationships["b"].favorability == 9
    assert rels.relationships["b"].trust == 4


def test_regress_negative_relationships():
    rels = RelationshipFile(relationships={
        "b": Relationship(target_name="B", target_id="b", favorability=-10, trust=-5),
    })
    regress_relationships(rels)
    assert rels.relationships["b"].favorability == -9
    assert rels.relationships["b"].trust == -4


def test_regress_zero_stays_zero():
    rels = RelationshipFile(relationships={
        "b": Relationship(target_name="B", target_id="b", favorability=0, trust=0),
    })
    regress_relationships(rels)
    assert rels.relationships["b"].favorability == 0
    assert rels.relationships["b"].trust == 0


def test_regress_understanding_unchanged():
    """Understanding does NOT regress."""
    rels = RelationshipFile(relationships={
        "b": Relationship(target_name="B", target_id="b", understanding=50),
    })
    regress_relationships(rels)
    assert rels.relationships["b"].understanding == 50


def test_regress_multiple_relationships():
    rels = RelationshipFile(relationships={
        "b": Relationship(target_name="B", target_id="b", favorability=5, trust=-3),
        "c": Relationship(target_name="C", target_id="c", favorability=-1, trust=1),
    })
    regress_relationships(rels)
    assert rels.relationships["b"].favorability == 4
    assert rels.relationships["b"].trust == -2
    assert rels.relationships["c"].favorability == 0
    assert rels.relationships["c"].trust == 0
