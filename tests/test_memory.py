"""Tests for memory retrieval (trigger extraction, overlap, ranking) and
the per-day key_memories cap."""

from sim.agent.storage import AgentStorage
from sim.memory.compression import cap_today_memories
from sim.memory.retrieval import _extract_triggers, _overlap, get_relevant_memories
from sim.models.agent import (
    Academics, AgentProfile, FamilyBackground, Gender, OverallRank,
    PressureLevel, Role,
)
from sim.models.memory import KeyMemory, KeyMemoryFile
from sim.models.scene import Scene, SceneDensity


def _make_profile(aid: str, name: str) -> AgentProfile:
    return AgentProfile(
        agent_id=aid, name=name, gender=Gender.MALE, role=Role.STUDENT,
        academics=Academics(overall_rank=OverallRank.MIDDLE),
        family_background=FamilyBackground(pressure_level=PressureLevel.MEDIUM),
    )


def _make_scene(**kw) -> Scene:
    defaults = dict(
        scene_index=0, day=1, time="08:45", name="课间",
        location="教室", density=SceneDensity.HIGH,
        agent_ids=["a", "b"],
    )
    defaults.update(kw)
    return Scene(**defaults)


PROFILES = {
    "a": _make_profile("a", "张伟"),
    "b": _make_profile("b", "李明"),
}


# --- _extract_triggers ---

def test_extract_triggers_includes_names():
    scene = _make_scene()
    triggers = _extract_triggers(scene, PROFILES)
    assert "张伟" in triggers
    assert "李明" in triggers


def test_extract_triggers_includes_ids():
    scene = _make_scene()
    triggers = _extract_triggers(scene, PROFILES)
    assert "a" in triggers
    assert "b" in triggers


def test_extract_triggers_includes_location():
    scene = _make_scene(location="操场")
    triggers = _extract_triggers(scene, PROFILES)
    assert "操场" in triggers


def test_extract_triggers_includes_scene_name():
    scene = _make_scene(name="午饭")
    triggers = _extract_triggers(scene, PROFILES)
    assert "午饭" in triggers


# --- _overlap ---

def test_overlap_full_match():
    mem = KeyMemory(
        date="Day 1", day=1, text="test",
        people=["张伟"], topics=["考试"], location="教室",
    )
    triggers = {"张伟", "考试", "教室"}
    assert _overlap(mem, triggers) == 3


def test_overlap_no_match():
    mem = KeyMemory(
        date="Day 1", day=1, text="test",
        people=["王芳"], topics=["篮球"], location="操场",
    )
    triggers = {"张伟", "考试", "教室"}
    assert _overlap(mem, triggers) == 0


def test_overlap_partial_match():
    mem = KeyMemory(
        date="Day 1", day=1, text="test",
        people=["张伟", "王芳"], topics=[], location="操场",
    )
    triggers = {"张伟", "教室"}
    assert _overlap(mem, triggers) == 1


# --- get_relevant_memories ---

def test_relevant_memories_filters_irrelevant():
    mem_relevant = KeyMemory(
        date="Day 1", day=1, text="张伟在教室说了什么",
        people=["张伟"], location="教室", importance=8,
    )
    mem_irrelevant = KeyMemory(
        date="Day 1", day=1, text="操场上的事",
        people=["王芳"], location="操场", importance=9,
    )
    memory_file = KeyMemoryFile(memories=[mem_relevant, mem_irrelevant])
    scene = _make_scene()
    result = get_relevant_memories(memory_file, scene, PROFILES)
    assert len(result) == 1
    assert result[0].text == "张伟在教室说了什么"


def test_relevant_memories_sorted_by_importance():
    mem_high = KeyMemory(
        date="Day 1", day=1, text="重要事件",
        people=["张伟"], location="教室", importance=9,
    )
    mem_low = KeyMemory(
        date="Day 1", day=1, text="普通事件",
        people=["张伟"], location="教室", importance=5,
    )
    memory_file = KeyMemoryFile(memories=[mem_low, mem_high])
    scene = _make_scene()
    result = get_relevant_memories(memory_file, scene, PROFILES)
    assert result[0].importance == 9
    assert result[1].importance == 5


def test_relevant_memories_respects_max_k():
    memories = [
        KeyMemory(
            date="Day 1", day=1, text=f"事件{i}",
            people=["张伟"], location="教室", importance=5,
        )
        for i in range(20)
    ]
    memory_file = KeyMemoryFile(memories=memories)
    scene = _make_scene()
    result = get_relevant_memories(memory_file, scene, PROFILES, max_k=5)
    assert len(result) == 5


def test_relevant_memories_empty():
    memory_file = KeyMemoryFile(memories=[])
    scene = _make_scene()
    result = get_relevant_memories(memory_file, scene, PROFILES)
    assert result == []


def test_relevant_memories_overlap_tiebreak():
    """Same importance → more overlap wins."""
    mem_more_overlap = KeyMemory(
        date="Day 1", day=1, text="多重叠",
        people=["张伟", "李明"], location="教室", importance=7,
    )
    mem_less_overlap = KeyMemory(
        date="Day 1", day=1, text="少重叠",
        people=["张伟"], location="操场", importance=7,
    )
    memory_file = KeyMemoryFile(memories=[mem_less_overlap, mem_more_overlap])
    scene = _make_scene()
    result = get_relevant_memories(memory_file, scene, PROFILES)
    # Same importance, but more overlap should rank first
    assert result[0].text == "多重叠"


# --- per-day memory cap (cap_today_memories) ---


def test_per_day_cap_enforced(tmp_path):
    """5 memories on day 3 (importances 3-9) → kept top 2."""
    storage = AgentStorage("a", base_dir=tmp_path)
    storage.write_key_memories(KeyMemoryFile(memories=[
        KeyMemory(date="Day 3", day=3, text=f"m{i}", importance=imp)
        for i, imp in enumerate([3, 5, 9, 4, 7])
    ]))
    dropped = cap_today_memories(storage, day=3)
    assert dropped == 3

    loaded = storage.load_key_memories()
    today = [m for m in loaded.memories if m.day == 3]
    importances = sorted(m.importance for m in today)
    assert importances == [7, 9]  # top 2 by importance


# Behavioral tests for the importance write threshold live in
# tests/test_apply_results.py (test_importance_below_threshold_dropped,
# test_importance_at_threshold_persists) — they exercise the actual
# apply_scene_end_results code path that enforces the threshold.


def test_older_day_memories_preserved_in_cap(tmp_path):
    """The cap only touches today's memories; older days are untouched."""
    storage = AgentStorage("a", base_dir=tmp_path)
    storage.write_key_memories(KeyMemoryFile(memories=[
        KeyMemory(date="Day 1", day=1, text="old1", importance=3),
        KeyMemory(date="Day 1", day=1, text="old2", importance=5),
        KeyMemory(date="Day 1", day=1, text="old3", importance=4),
        KeyMemory(date="Day 2", day=2, text="new1", importance=8),
        KeyMemory(date="Day 2", day=2, text="new2", importance=4),
        KeyMemory(date="Day 2", day=2, text="new3", importance=6),
    ]))
    cap_today_memories(storage, day=2)
    loaded = storage.load_key_memories()

    # Day 1: all 3 still there
    day1 = [m for m in loaded.memories if m.day == 1]
    assert len(day1) == 3

    # Day 2: capped to 2 (importance 8 and 6)
    day2 = sorted([m for m in loaded.memories if m.day == 2], key=lambda m: -m.importance)
    assert len(day2) == 2
    assert day2[0].importance == 8
    assert day2[1].importance == 6


def test_cap_is_noop_when_under_threshold(tmp_path):
    """If today's count ≤ cap, no writes happen and dropped == 0."""
    storage = AgentStorage("a", base_dir=tmp_path)
    storage.write_key_memories(KeyMemoryFile(memories=[
        KeyMemory(date="Day 4", day=4, text="m1", importance=5),
        KeyMemory(date="Day 4", day=4, text="m2", importance=7),
    ]))
    dropped = cap_today_memories(storage, day=4)
    assert dropped == 0

    loaded = storage.load_key_memories()
    assert len(loaded.memories) == 2
