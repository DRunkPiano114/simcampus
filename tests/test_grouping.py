"""Tests for agent grouping: affinity scoring, solo detection, clustering."""

from random import Random

from sim.models.agent import (
    Academics, AgentProfile, AgentState, DailyPlan, Emotion,
    FamilyBackground, Gender, Intention, OverallRank, PressureLevel, Role,
)
from sim.models.relationship import Relationship, RelationshipFile
from sim.models.scene import Scene, SceneDensity
from sim.world.grouping import (
    LABEL_BONUS,
    _compute_affinity,
    _should_be_solo,
    group_agents,
)


def _make_profile(aid: str, name: str, gender=Gender.MALE, **kw) -> AgentProfile:
    return AgentProfile(
        agent_id=aid, name=name, gender=gender, role=Role.STUDENT,
        academics=Academics(overall_rank=OverallRank.MIDDLE),
        family_background=FamilyBackground(pressure_level=PressureLevel.MEDIUM),
        **kw,
    )


def _make_scene(location="教室") -> Scene:
    return Scene(
        scene_index=0, day=1, time="08:45", name="课间",
        location=location, density=SceneDensity.HIGH,
    )


RNG = Random(42)


# --- _compute_affinity ---

def test_affinity_bidirectional_favorability():
    profiles = {
        "a": _make_profile("a", "张伟"),
        "b": _make_profile("b", "李明"),
    }
    rels = {
        "a": RelationshipFile(relationships={
            "b": Relationship(target_name="李明", target_id="b", favorability=10),
        }),
        "b": RelationshipFile(relationships={
            "a": Relationship(target_name="张伟", target_id="a", favorability=5),
        }),
    }
    # Use fixed seed to isolate random noise
    rng = Random(0)
    score = _compute_affinity("a", "b", profiles, rels, _make_scene(), rng)
    # 10 + 5 (fav) + 0 (label=同学) + 5 (same gender) + noise
    assert score > 10  # At minimum bidirectional fav + gender bonus


def test_affinity_label_bonus():
    profiles = {
        "a": _make_profile("a", "张伟"),
        "b": _make_profile("b", "李明"),
    }
    # Roommate label
    rels_roommate = {
        "a": RelationshipFile(relationships={
            "b": Relationship(target_name="李明", target_id="b", label="室友"),
        }),
        "b": RelationshipFile(relationships={}),
    }
    rels_classmate = {
        "a": RelationshipFile(relationships={
            "b": Relationship(target_name="李明", target_id="b", label="同学"),
        }),
        "b": RelationshipFile(relationships={}),
    }
    rng1 = Random(99)
    rng2 = Random(99)
    score_roommate = _compute_affinity("a", "b", profiles, rels_roommate, _make_scene(), rng1)
    score_classmate = _compute_affinity("a", "b", profiles, rels_classmate, _make_scene(), rng2)
    assert score_roommate - score_classmate == LABEL_BONUS["室友"] - LABEL_BONUS["同学"]


def test_affinity_dorm_gender_bonus():
    profiles = {
        "a": _make_profile("a", "张伟", gender=Gender.MALE),
        "b": _make_profile("b", "李明", gender=Gender.MALE),
    }
    rels = {"a": RelationshipFile(), "b": RelationshipFile()}
    rng1 = Random(99)
    rng2 = Random(99)
    score_dorm = _compute_affinity("a", "b", profiles, rels, _make_scene("宿舍"), rng1)
    score_class = _compute_affinity("a", "b", profiles, rels, _make_scene("教室"), rng2)
    # Dorm: +100, classroom: +5
    assert score_dorm - score_class == 95


def test_affinity_cross_gender_no_bonus():
    profiles = {
        "a": _make_profile("a", "张伟", gender=Gender.MALE),
        "b": _make_profile("b", "王芳", gender=Gender.FEMALE),
    }
    rels = {"a": RelationshipFile(), "b": RelationshipFile()}
    rng = Random(99)
    score = _compute_affinity("a", "b", profiles, rels, _make_scene(), rng)
    # No gender bonus, just noise
    assert -15 < score < 15


def test_affinity_intention_bonus():
    profiles = {
        "a": _make_profile("a", "张伟"),
        "b": _make_profile("b", "李明"),
    }
    rels = {"a": RelationshipFile(), "b": RelationshipFile()}
    states = {
        "a": AgentState(daily_plan=DailyPlan(intentions=[
            Intention(target="李明", goal="聊作业", reason="想问"),
        ])),
        "b": AgentState(),
    }
    rng1 = Random(99)
    rng2 = Random(99)
    score_with = _compute_affinity("a", "b", profiles, rels, _make_scene(), rng1, states=states)
    score_without = _compute_affinity("a", "b", profiles, rels, _make_scene(), rng2, states=None)
    assert score_with - score_without == 25


# --- _should_be_solo ---

def test_solo_low_energy():
    profile = _make_profile("a", "张伟")
    state = AgentState(energy=20)
    assert _should_be_solo("a", profile, state, {}, RNG) is True


def test_solo_normal_energy():
    profile = _make_profile("a", "张伟")
    state = AgentState(energy=60)
    assert _should_be_solo("a", profile, state, {}, RNG) is False


def test_solo_introvert_no_close():
    """Introvert without close relationships → 50% solo."""
    profile = _make_profile("a", "张伟", personality=["内向"])
    state = AgentState(energy=60)
    rels = {"a": RelationshipFile(relationships={
        "b": Relationship(target_name="B", target_id="b", favorability=5),  # Not close (< 15)
    })}
    results = set()
    for seed in range(100):
        results.add(_should_be_solo("a", profile, state, rels, Random(seed)))
    # Should see both True and False with 50% probability
    assert True in results and False in results


def test_solo_introvert_with_close():
    """Introvert with close relationship → not solo (from introvert check)."""
    profile = _make_profile("a", "张伟", personality=["内向"])
    state = AgentState(energy=60)
    rels = {"a": RelationshipFile(relationships={
        "b": Relationship(target_name="B", target_id="b", favorability=20),  # Close (>= 15)
    })}
    # This should skip the introvert solo check
    assert _should_be_solo("a", profile, state, rels, Random(42)) is False


def test_solo_sad_low_energy():
    """SAD + energy < 50 → 60% solo."""
    profile = _make_profile("a", "张伟")
    state = AgentState(energy=40, emotion=Emotion.SAD)
    results = set()
    for seed in range(100):
        results.add(_should_be_solo("a", profile, state, {}, Random(seed)))
    assert True in results and False in results


def test_solo_sad_high_energy():
    """SAD but energy >= 50 → not solo from sad check."""
    profile = _make_profile("a", "张伟")
    state = AgentState(energy=60, emotion=Emotion.SAD)
    assert _should_be_solo("a", profile, state, {}, Random(42)) is False


# --- group_agents ---

def test_group_agents_creates_solo_groups():
    profiles = {
        "a": _make_profile("a", "张伟"),
        "b": _make_profile("b", "李明"),
    }
    states = {
        "a": AgentState(energy=10),  # Low energy → solo
        "b": AgentState(energy=80),
    }
    scene = _make_scene()
    groups = group_agents(["a", "b"], profiles, states, {}, scene, Random(42))
    solo_groups = [g for g in groups if g.is_solo]
    assert any(g.agent_ids == ["a"] for g in solo_groups)


def test_group_agents_pairs_social_agents():
    profiles = {
        "a": _make_profile("a", "张伟"),
        "b": _make_profile("b", "李明"),
        "c": _make_profile("c", "王芳", gender=Gender.FEMALE),
    }
    states = {aid: AgentState(energy=80) for aid in profiles}
    rels = {}
    scene = _make_scene()
    groups = group_agents(["a", "b", "c"], profiles, states, rels, scene, Random(42))
    # Should have at least one non-solo group
    non_solo = [g for g in groups if not g.is_solo]
    assert len(non_solo) >= 1


def test_group_agents_max_group_size():
    """Groups should not exceed 5 members."""
    profiles = {f"agent_{i}": _make_profile(f"agent_{i}", f"学生{i}") for i in range(10)}
    states = {aid: AgentState(energy=80) for aid in profiles}
    scene = _make_scene()
    groups = group_agents(list(profiles.keys()), profiles, states, {}, scene, Random(42))
    for g in groups:
        if not g.is_solo:
            assert len(g.agent_ids) <= 5


def test_group_agents_all_assigned():
    """Every agent must appear in exactly one group."""
    profiles = {f"a{i}": _make_profile(f"a{i}", f"学生{i}") for i in range(8)}
    states = {aid: AgentState(energy=80) for aid in profiles}
    scene = _make_scene()
    groups = group_agents(list(profiles.keys()), profiles, states, {}, scene, Random(42))
    all_assigned = []
    for g in groups:
        all_assigned.extend(g.agent_ids)
    assert sorted(all_assigned) == sorted(profiles.keys())


def test_group_agents_single_agent():
    profiles = {"a": _make_profile("a", "张伟")}
    states = {"a": AgentState(energy=80)}
    scene = _make_scene()
    groups = group_agents(["a"], profiles, states, {}, scene, Random(42))
    assert len(groups) == 1
    assert groups[0].agent_ids == ["a"]


def test_group_agents_empty():
    scene = _make_scene()
    groups = group_agents([], {}, {}, {}, scene, Random(42))
    assert groups == []
