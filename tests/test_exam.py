"""Tests for exam system: score generation, effects, context formatting."""

from random import Random

from sim.models.agent import (
    Academics, AgentProfile, AgentState, FamilyBackground,
    Gender, OverallRank, PressureLevel, Role,
)
from sim.world.exam import (
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
