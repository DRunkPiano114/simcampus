"""Tests for exam system: score generation, effects, context formatting."""

from random import Random

import pytest

from sim.agent.storage import WorldStorage, atomic_write_json
from sim.models.agent import (
    Academics, AgentProfile, AgentState, Emotion, FamilyBackground,
    Gender, OverallRank, PressureLevel, Role,
)
from sim.world.exam import (
    apply_exam_effects,
    format_exam_context,
    format_teacher_exam_context,
    generate_exam_results,
)


def _make_student(aid: str, name: str, rank=OverallRank.MIDDLE, **kw) -> AgentProfile:
    return AgentProfile(
        agent_id=aid, name=name, gender=Gender.MALE, role=Role.STUDENT,
        academics=Academics(overall_rank=rank, study_attitude="很努力"),
        family_background=FamilyBackground(pressure_level=PressureLevel.MEDIUM),
        **kw,
    )


def _make_teacher(aid: str, name: str) -> AgentProfile:
    return AgentProfile(
        agent_id=aid, name=name, gender=Gender.FEMALE, role=Role.HOMEROOM_TEACHER,
        academics=Academics(overall_rank=OverallRank.MIDDLE),
        family_background=FamilyBackground(pressure_level=PressureLevel.LOW),
    )


# --- generate_exam_results ---

def test_generate_exam_results_excludes_teacher():
    profiles = {
        "s1": _make_student("s1", "张伟"),
        "t1": _make_teacher("t1", "何敏"),
    }
    states = {"s1": AgentState(), "t1": AgentState()}
    results = generate_exam_results(profiles, states, Random(42))
    assert "s1" in results
    assert "t1" not in results


def test_generate_exam_results_ranks_assigned():
    profiles = {
        f"s{i}": _make_student(f"s{i}", f"学生{i}")
        for i in range(5)
    }
    states = {aid: AgentState() for aid in profiles}
    results = generate_exam_results(profiles, states, Random(42))
    ranks = sorted(r["rank"] for r in results.values())
    assert ranks == [1, 2, 3, 4, 5]


def test_generate_exam_results_rank_change():
    profiles = {
        "s1": _make_student("s1", "张伟"),
        "s2": _make_student("s2", "李明"),
    }
    states = {aid: AgentState() for aid in profiles}
    previous = {"s1": {"rank": 1}, "s2": {"rank": 2}}
    results = generate_exam_results(profiles, states, Random(42), previous)
    # Every student should have rank_change
    for r in results.values():
        assert "rank_change" in r


def test_generate_exam_results_no_previous():
    profiles = {"s1": _make_student("s1", "张伟")}
    states = {"s1": AgentState()}
    results = generate_exam_results(profiles, states, Random(42))
    assert results["s1"]["rank_change"] == 0


# --- format_exam_context ---

def test_format_exam_context_found():
    results = {
        "s1": {
            "name": "张伟", "total": 450, "rank": 3,
            "rank_change": 2, "scores": {"语文": 80, "数学": 85},
        },
    }
    ctx = format_exam_context(results, "s1")
    assert "450" in ctx
    assert "第3名" in ctx
    assert "进步了2名" in ctx


def test_format_exam_context_not_found():
    assert format_exam_context({}, "missing") == ""


def test_format_exam_context_rank_drop():
    results = {
        "s1": {
            "name": "张伟", "total": 400, "rank": 5,
            "rank_change": -3, "scores": {"语文": 70},
        },
    }
    ctx = format_exam_context(results, "s1")
    assert "退步了3名" in ctx


# --- format_teacher_exam_context ---

def test_teacher_exam_context_empty():
    assert format_teacher_exam_context({}) == ""


def test_teacher_exam_context_class_overview():
    results = {
        "s1": {"name": "张伟", "total": 500, "rank": 1, "rank_change": 0, "scores": {}},
        "s2": {"name": "李明", "total": 450, "rank": 2, "rank_change": -4, "scores": {}},
        "s3": {"name": "王芳", "total": 400, "rank": 3, "rank_change": 3, "scores": {}},
    }
    ctx = format_teacher_exam_context(results)
    assert "3人" in ctx
    assert "张伟" in ctx  # Top 3
    assert "退步明显" in ctx
    assert "李明" in ctx  # Struggling (rank_change <= -3)
    assert "进步明显" in ctx
    assert "王芳" in ctx  # Improved (rank_change >= 3)


def test_teacher_exam_context_no_struggling():
    results = {
        "s1": {"name": "张伟", "total": 500, "rank": 1, "rank_change": 0, "scores": {}},
    }
    ctx = format_teacher_exam_context(results)
    assert "退步" not in ctx


def test_teacher_exam_context_class_average():
    results = {
        "s1": {"name": "A", "total": 600, "rank": 1, "rank_change": 0, "scores": {}},
        "s2": {"name": "B", "total": 400, "rank": 2, "rank_change": 0, "scores": {}},
    }
    ctx = format_teacher_exam_context(results)
    assert "500" in ctx  # (600 + 400) / 2 = 500


# --- apply_exam_effects ---

def _setup_agent(agents_dir, aid, name, pressure=PressureLevel.MEDIUM, **state_kw):
    """Create agent profile + state files in a temp directory."""
    profile = AgentProfile(
        agent_id=aid, name=name, gender=Gender.MALE, role=Role.STUDENT,
        academics=Academics(overall_rank=OverallRank.MIDDLE),
        family_background=FamilyBackground(pressure_level=pressure),
    )
    agent_dir = agents_dir / aid
    agent_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(agent_dir / "profile.json", profile.model_dump())
    defaults = {"energy": 80, "academic_pressure": 40}
    defaults.update(state_kw)
    atomic_write_json(agent_dir / "state.json", AgentState(**defaults).model_dump())
    return profile


@pytest.fixture
def exam_env(tmp_path):
    """Two students: s1 (MEDIUM pressure), s2 (HIGH pressure)."""
    agents_dir = tmp_path / "agents"
    world_dir = tmp_path / "world"
    agents_dir.mkdir()
    world_dir.mkdir()

    profiles = {}
    profiles["s1"] = _setup_agent(agents_dir, "s1", "张伟")
    profiles["s2"] = _setup_agent(agents_dir, "s2", "李明", pressure=PressureLevel.HIGH)

    world = WorldStorage(agents_dir=agents_dir, world_dir=world_dir)
    world.load_all_agents()
    return world, profiles


def test_exam_rank_drop_increases_pressure(exam_env):
    """Dropping 3 ranks should increase academic pressure by 6."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": -3, "rank": 5}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s1").load_state()
    assert state.academic_pressure == 46  # 40 + 3*2


def test_exam_no_rank_drop_no_pressure_change(exam_env):
    """No rank drop → pressure unchanged by exam shock."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": 2, "rank": 3}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s1").load_state()
    assert state.academic_pressure == 40


def test_exam_big_improvement_excited(exam_env):
    """Improving ≥5 ranks → EXCITED."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": 5, "rank": 1}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s1").load_state()
    assert state.emotion == Emotion.EXCITED


def test_exam_big_drop_sad(exam_env):
    """Dropping ≥5 ranks → SAD."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": -5, "rank": 10}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s1").load_state()
    assert state.emotion == Emotion.SAD


def test_exam_moderate_drop_no_emotion_change(exam_env):
    """Dropping 4 ranks is bad but not ≥5, no special emotion for MEDIUM pressure."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": -4, "rank": 3}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s1").load_state()
    # MEDIUM pressure + rank ≤ 5 → no emotion override
    assert state.emotion == Emotion.NEUTRAL


def test_exam_high_pressure_family_low_rank_anxious(exam_env):
    """HIGH pressure family + rank > 5 → ANXIOUS."""
    world, profiles = exam_env
    results = {"s2": {"rank_change": 0, "rank": 6}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s2").load_state()
    assert state.emotion == Emotion.ANXIOUS


def test_exam_high_pressure_family_good_rank_not_anxious(exam_env):
    """HIGH pressure family but rank ≤ 5 → no anxiety."""
    world, profiles = exam_env
    results = {"s2": {"rank_change": 0, "rank": 5}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s2").load_state()
    assert state.emotion != Emotion.ANXIOUS


def test_exam_energy_drain(exam_env):
    """Every student loses 15 energy from the exam."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": 0, "rank": 3}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s1").load_state()
    assert state.energy == 65  # 80 - 15


def test_exam_energy_clamps_at_zero(tmp_path):
    """Energy drain shouldn't push below 0."""
    agents_dir = tmp_path / "agents"
    world_dir = tmp_path / "world"
    agents_dir.mkdir()
    world_dir.mkdir()
    profiles = {"s1": _setup_agent(agents_dir, "s1", "张伟", energy=10)}
    world = WorldStorage(agents_dir=agents_dir, world_dir=world_dir)
    world.load_all_agents()

    results = {"s1": {"rank_change": 0, "rank": 1}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s1").load_state()
    assert state.energy == 0  # 10 - 15 → clamped to 0


def test_exam_pressure_clamps_at_100(tmp_path):
    """Massive rank drop shouldn't push pressure above 100."""
    agents_dir = tmp_path / "agents"
    world_dir = tmp_path / "world"
    agents_dir.mkdir()
    world_dir.mkdir()
    profiles = {"s1": _setup_agent(agents_dir, "s1", "张伟", academic_pressure=90)}
    world = WorldStorage(agents_dir=agents_dir, world_dir=world_dir)
    world.load_all_agents()

    results = {"s1": {"rank_change": -10, "rank": 15}}
    apply_exam_effects(results, world, profiles, today=1)
    state = world.get_agent("s1").load_state()
    assert state.academic_pressure == 100  # 90 + 20 → clamped to 100


def test_exam_skips_unknown_agent(exam_env):
    """Agent ID not in profiles → silently skipped."""
    world, profiles = exam_env
    results = {"unknown_agent": {"rank_change": -3, "rank": 5}}
    apply_exam_effects(results, world, profiles, today=1)  # Should not raise


# --- exam shock writes a high-intensity 学业焦虑 concern ---


def test_exam_significant_drop_writes_high_intensity_concern(exam_env):
    """A 5-rank drop produces a 学业焦虑 concern at intensity 10 — the
    skip_cap path lets it bypass the autogen cap (=6)."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": -5, "rank": 10}}
    apply_exam_effects(results, world, profiles, today=7)

    state = world.get_agent("s1").load_state()
    learning_concerns = [c for c in state.active_concerns if c.topic == "学业焦虑"]
    assert len(learning_concerns) == 1
    concern = learning_concerns[0]
    assert concern.intensity == 10  # min(10, 5 + 5)
    assert concern.last_reinforced_day == 7
    assert concern.source_day == 7
    assert "退步" in concern.text
    assert concern.positive is False


def test_exam_minor_drop_writes_no_concern(exam_env):
    """rank_change=-2 is below the threshold; no shock concern created."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": -2, "rank": 4}}
    apply_exam_effects(results, world, profiles, today=1)

    state = world.get_agent("s1").load_state()
    assert not any(c.topic == "学业焦虑" for c in state.active_concerns)


def test_exam_improvement_writes_no_concern(exam_env):
    """A rank improvement creates no shock concern."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": 3, "rank": 2}}
    apply_exam_effects(results, world, profiles, today=1)

    state = world.get_agent("s1").load_state()
    assert not any(c.topic == "学业焦虑" for c in state.active_concerns)


def test_exam_drop_intensity_scales_with_magnitude(tmp_path):
    """Verify the 8 / 9 / 10 ladder for -3 / -4 / -5 rank drops."""
    agents_dir = tmp_path / "agents"
    world_dir = tmp_path / "world"
    agents_dir.mkdir()
    world_dir.mkdir()
    profiles = {
        "a": _setup_agent(agents_dir, "a", "甲"),
        "b": _setup_agent(agents_dir, "b", "乙"),
        "c": _setup_agent(agents_dir, "c", "丙"),
    }
    world = WorldStorage(agents_dir=agents_dir, world_dir=world_dir)
    world.load_all_agents()

    apply_exam_effects(
        {
            "a": {"rank_change": -3, "rank": 5},
            "b": {"rank_change": -4, "rank": 6},
            "c": {"rank_change": -5, "rank": 7},
        },
        world, profiles, today=1,
    )

    def _intensity(aid: str) -> int:
        state = world.get_agent(aid).load_state()
        return next(c.intensity for c in state.active_concerns if c.topic == "学业焦虑")

    assert _intensity("a") == 8
    assert _intensity("b") == 9
    assert _intensity("c") == 10


def test_exam_shock_concern_bypasses_cap(exam_env):
    """An exam shock concern lands above the autogen cap (=6)."""
    world, profiles = exam_env
    results = {"s1": {"rank_change": -4, "rank": 8}}
    apply_exam_effects(results, world, profiles, today=2)
    state = world.get_agent("s1").load_state()
    intensity = next(c.intensity for c in state.active_concerns if c.topic == "学业焦虑")
    assert intensity == 9
