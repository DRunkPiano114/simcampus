"""Tests for apply_results helpers: concern_match, add_concern,
trivial scene detection, relationship auto-extension, and event grounding."""

import random

from sim.agent.storage import WorldStorage, atomic_write_json
from sim.models.agent import (
    Academics,
    ActiveConcern,
    AgentProfile,
    AgentState,
    Emotion,
    FamilyBackground,
    Gender,
    OverallRank,
    PressureLevel,
    Role,
)
from sim.models.dialogue import (
    ActionType,
    AgentMemoryCandidate,
    AgentReflection,
    AgentRelChange,
    NarrativeExtraction,
    NewEventCandidate,
    PerceptionOutput,
)
from sim.models.event import EventQueue
from sim.models.relationship import Relationship, RelationshipFile
from sim.models.scene import Scene, SceneDensity
from sim.world.event_queue import EventQueueManager
from sim.interaction.apply_results import (
    add_concern,
    apply_scene_end_results,
    apply_trivial_scene_result,
    concern_match,
    is_trivial_scene,
)


def _make_perception(
    action_type: ActionType = ActionType.OBSERVE,
    is_disruptive: bool = False,
    action_content: str | None = None,
) -> PerceptionOutput:
    return PerceptionOutput(
        observation="x",
        inner_thought="x",
        emotion=Emotion.NEUTRAL,
        action_type=action_type,
        action_content=action_content,
        urgency=3,
        is_disruptive=is_disruptive,
    )


# --- concern_match ---

def test_concern_match_exact():
    assert concern_match("被嘲笑", "被嘲笑") is True


def test_concern_match_substring_forward():
    assert concern_match("被江浩天当众嘲笑数学成绩", "当众嘲笑") is True


def test_concern_match_substring_reverse():
    assert concern_match("当众嘲笑", "被江浩天当众嘲笑数学成绩") is True


def test_concern_match_non_contiguous_fails():
    """Non-contiguous substring does NOT match."""
    assert concern_match("被江浩天当众嘲笑数学成绩", "被嘲笑") is False


def test_concern_match_no_match():
    assert concern_match("考试压力", "被嘲笑") is False


def test_concern_match_none():
    assert concern_match("anything", None) is False


def test_concern_match_empty_string():
    """Empty text_b is falsy → returns False."""
    assert concern_match("被嘲笑", "") is False


def test_concern_match_both_empty():
    """Both empty → text_b is falsy → returns False."""
    assert concern_match("", "") is False


# --- add_concern + topic-based dedup ---


def _make_concern(
    text: str = "test",
    intensity: int = 5,
    topic: str = "其他",
    people: list[str] | None = None,
    positive: bool = False,
    day: int = 1,
) -> ActiveConcern:
    return ActiveConcern(
        text=text,
        source_day=day,
        source_scene="课间",
        intensity=intensity,
        topic=topic,  # type: ignore[arg-type]
        related_people=people or [],
        positive=positive,
    )


def test_add_concern_merges_same_topic_with_people_overlap():
    """Two 学业焦虑 concerns with overlapping people merge: intensity bumps
    by 1, text and last_reinforced_day refresh."""
    state = AgentState()
    state.active_concerns.append(
        _make_concern(text="数学考砸", intensity=5, topic="学业焦虑", people=["张伟"])
    )
    new = _make_concern(text="物理也不行", intensity=4, topic="学业焦虑", people=["张伟", "李明"])
    add_concern(state, new, today=3)

    assert len(state.active_concerns) == 1
    merged = state.active_concerns[0]
    assert merged.topic == "学业焦虑"
    assert merged.intensity == 6  # 5 + 1
    assert merged.text == "物理也不行"
    assert merged.last_reinforced_day == 3


def test_other_topic_requires_exact_people_match():
    """For topic='其他' with non-empty people, only EXACT people set match merges."""
    state = AgentState()
    state.active_concerns.append(
        _make_concern(topic="其他", people=["张伟", "李明"])
    )
    # Same set, different order — should merge
    same_set = _make_concern(topic="其他", people=["李明", "张伟"])
    add_concern(state, same_set, today=2)
    assert len(state.active_concerns) == 1


def test_other_topic_different_people_not_merged():
    """For topic='其他', different (overlapping but not equal) people → not merged."""
    state = AgentState()
    state.active_concerns.append(
        _make_concern(topic="其他", people=["张伟"])
    )
    new = _make_concern(topic="其他", people=["张伟", "王芳"])
    add_concern(state, new, today=2)
    # Two separate entries
    assert len(state.active_concerns) == 2


def test_other_topic_empty_people_never_merges():
    """Two topic='其他' concerns with empty related_people → NEVER merge.
    Frankenstein guard: empty-people 其他 buckets are almost always unrelated
    things; merging produces a useless meta-concern."""
    state = AgentState()
    state.active_concerns.append(
        _make_concern(text="一些焦虑的事", topic="其他", people=[])
    )
    add_concern(
        state,
        _make_concern(text="另一件不相关的事", topic="其他", people=[]),
        today=2,
    )
    # Both concerns kept separately
    assert len(state.active_concerns) == 2


def test_add_concern_caps_intensity_at_6():
    """Default reflection-originated concerns are capped at
    `concern_autogen_max_intensity` (=6)."""
    state = AgentState()
    new = _make_concern(intensity=10, topic="学业焦虑", people=["张伟"])
    add_concern(state, new, today=1)
    assert state.active_concerns[0].intensity == 6


def test_add_concern_skip_cap_preserves_high_intensity():
    """High-priority paths (e.g. exam shock) pass skip_cap=True so the
    concern lands at full intensity."""
    state = AgentState()
    new = _make_concern(intensity=9, topic="学业焦虑", people=["张伟"])
    add_concern(state, new, today=1, skip_cap=True)
    assert state.active_concerns[0].intensity == 9


def test_add_concern_merge_ignores_high_intensity_claim_without_skip_cap():
    """Without skip_cap, a merge bumps existing by 1 — it cannot jump to a
    high LLM-claimed value, which would otherwise sneak past the cap."""
    state = AgentState()
    state.active_concerns.append(
        _make_concern(text="数学焦虑", intensity=5, topic="学业焦虑", people=["张伟"])
    )
    new = _make_concern(intensity=9, topic="学业焦虑", people=["张伟"])
    add_concern(state, new, today=2)

    assert state.active_concerns[0].intensity == 6


def test_add_concern_merge_does_not_demote_existing_high_intensity():
    """Reinforcement never reduces intensity. A regular reflection touching
    an existing intensity-9 concern bumps it to 10, not down to the cap."""
    state = AgentState()
    state.active_concerns.append(
        _make_concern(text="月考焦虑", intensity=9, topic="学业焦虑", people=["张伟"])
    )
    new = _make_concern(intensity=4, topic="学业焦虑", people=["张伟"])
    add_concern(state, new, today=2)

    assert state.active_concerns[0].intensity == 10


def test_add_concern_merge_skip_cap_jumps_to_max_plus_one():
    """With skip_cap=True the merge takes max(existing, new) + 1 — a
    follow-up shock can drive the floor up."""
    state = AgentState()
    state.active_concerns.append(
        _make_concern(intensity=5, topic="学业焦虑", people=["张伟"])
    )
    new = _make_concern(intensity=9, topic="学业焦虑", people=["张伟"])
    add_concern(state, new, today=2, skip_cap=True)

    assert state.active_concerns[0].intensity == 10


def test_positive_concern_uses_positive_topic_bucket():
    """A positive concern tagged with 兴趣爱好 / 期待的事 stays in that
    bucket — not merged with negative '其他' concerns."""
    state = AgentState()
    state.active_concerns.append(
        _make_concern(text="数学焦虑", intensity=5, topic="学业焦虑", people=["张伟"])
    )
    state.active_concerns.append(
        _make_concern(text="一件杂事", intensity=3, topic="其他", people=["李明"])
    )
    new = _make_concern(
        text="周末约朋友打球",
        intensity=4,
        topic="兴趣爱好",
        people=["王芳"],
        positive=True,
    )
    add_concern(state, new, today=2)
    # Three distinct entries; the positive one is in its own bucket
    assert len(state.active_concerns) == 3
    bucket = next(c for c in state.active_concerns if c.topic == "兴趣爱好")
    assert bucket.positive is True


def test_add_concern_merge_no_leading_delimiter_when_existing_empty():
    """Merging into a concern with empty source_event must not produce
    a leading '；'."""
    state = AgentState()
    state.active_concerns.append(
        ActiveConcern(
            text="数学焦虑",
            source_event="",  # default empty (e.g. concern from compression path)
            source_scene="课间",
            source_day=1,
            intensity=5,
            topic="学业焦虑",
            related_people=["张伟"],
        )
    )
    new = _make_concern(intensity=4, topic="学业焦虑", people=["张伟"])
    new.source_event = "数学小测又不及格"
    add_concern(state, new, today=2)

    merged = state.active_concerns[0]
    assert merged.source_event == "数学小测又不及格"
    assert not merged.source_event.startswith("；")


def test_add_concern_merge_no_trailing_delimiter_when_new_empty():
    """Merging an empty source_event must not produce a trailing '；'."""
    state = AgentState()
    state.active_concerns.append(
        ActiveConcern(
            text="数学焦虑",
            source_event="数学小测又不及格",
            source_scene="课间",
            source_day=1,
            intensity=5,
            topic="学业焦虑",
            related_people=["张伟"],
        )
    )
    new = _make_concern(intensity=4, topic="学业焦虑", people=["张伟"])
    new.source_event = ""
    add_concern(state, new, today=2)

    merged = state.active_concerns[0]
    assert merged.source_event == "数学小测又不及格"
    assert not merged.source_event.endswith("；")


def test_add_concern_merge_concatenates_with_delimiter_when_both_present():
    """Both sides non-empty → 'a；b'."""
    state = AgentState()
    state.active_concerns.append(
        ActiveConcern(
            text="数学焦虑",
            source_event="月考分数下滑",
            source_scene="课间",
            source_day=1,
            intensity=5,
            topic="学业焦虑",
            related_people=["张伟"],
        )
    )
    new = _make_concern(intensity=4, topic="学业焦虑", people=["张伟"])
    new.source_event = "数学小测又不及格"
    add_concern(state, new, today=2)

    merged = state.active_concerns[0]
    assert merged.source_event == "月考分数下滑；数学小测又不及格"


def test_add_concern_merge_source_event_truncates_oldest_when_over_cap():
    """When the concatenated source_event exceeds 500 chars, truncation
    must preserve the MOST RECENT trigger and drop the oldest prefix.
    Design intent: readers of `source_event` want to see 'what set this
    concern off lately', not 'the first thing that ever triggered it' —
    the latter is valuable for lore but the former is what the LLM and
    human reviewers consume tick-to-tick. Slicing with [:500] (keep head)
    would do the opposite and silently discard every reinforcement after
    the buffer filled."""
    state = AgentState()
    long_existing = "旧" * 499  # 499 chars, almost at the 500 cap
    state.active_concerns.append(
        ActiveConcern(
            text="学业焦虑",
            source_event=long_existing,
            source_scene="课间",
            source_day=1,
            intensity=5,
            topic="学业焦虑",
            related_people=["张伟"],
        )
    )
    new = _make_concern(intensity=4, topic="学业焦虑", people=["张伟"])
    new_trigger = "数学小测又不及格"  # fresh 8-char trigger
    new.source_event = new_trigger
    add_concern(state, new, today=2)

    merged = state.active_concerns[0]
    # Cap is respected.
    assert len(merged.source_event) == 500
    # Newest trigger is fully preserved at the tail.
    assert merged.source_event.endswith(new_trigger)
    # Arithmetic: pre-truncation length = 499 (old) + 1 (delimiter "；") +
    # len(new_trigger) = 508. Slicing [-500:] drops 508 - 500 = 8 chars
    # from the HEAD (oldest), so 499 - 8 = 491 "旧" characters survive.
    # The delimiter and the 8-char new trigger are untouched at the tail.
    dropped_from_head = (499 + 1 + len(new_trigger)) - 500
    assert merged.source_event.count("旧") == 499 - dropped_from_head
    # And the full string is exactly that many "旧" + delimiter + new.
    assert merged.source_event == (
        "旧" * (499 - dropped_from_head) + "；" + new_trigger
    )


def test_add_concern_merge_source_event_keeps_chronological_order():
    """Even when truncation kicks in, surviving content stays in 'oldest
    first, newest last' order so a reader scans the log naturally."""
    state = AgentState()
    state.active_concerns.append(
        ActiveConcern(
            text="学业焦虑",
            source_event="事件A；事件B；事件C",
            source_scene="课间",
            source_day=1,
            intensity=5,
            topic="学业焦虑",
            related_people=["张伟"],
        )
    )
    new = _make_concern(intensity=4, topic="学业焦虑", people=["张伟"])
    new.source_event = "事件D"
    add_concern(state, new, today=2)

    merged = state.active_concerns[0]
    # Well under 500 chars so no truncation here — just confirms the
    # append order of old-then-new, which is what [-500:] preserves when
    # the cap eventually triggers.
    assert merged.source_event == "事件A；事件B；事件C；事件D"


def test_add_concern_evicts_lowest_intensity():
    """When at max_active_concerns, a higher-intensity new concern evicts
    the lowest one."""
    state = AgentState()
    for i in range(4):  # max_active_concerns is 4
        state.active_concerns.append(
            _make_concern(text=f"c{i}", intensity=2 + i, topic="其他", people=[f"p{i}"])
        )
    # All four occupy slots, lowest intensity = 2
    new = _make_concern(text="newer", intensity=8, topic="学业焦虑", people=["zz"])
    add_concern(state, new, today=2)  # cap brings 8 → 6
    assert len(state.active_concerns) == 4
    # The intensity-2 concern was evicted
    intensities = sorted(c.intensity for c in state.active_concerns)
    assert 2 not in intensities
    assert 6 in intensities  # the new one (capped at 6)


# --- is_trivial_scene ---


def _make_tick(
    tick: int = 0,
    speech=None,
    actions=None,
    env_event: str | None = None,
) -> dict:
    return {
        "tick": tick,
        "agent_outputs": {},
        "resolved_speech": speech,
        "resolved_actions": actions or [],
        "environmental_event": env_event,
        "exits": [],
    }


def test_is_trivial_scene_empty():
    """Empty turn_records → trivial (defensive guard)."""
    assert is_trivial_scene([]) is True


def test_is_trivial_scene_no_speech_no_env():
    """No speech, no environmental events anywhere → trivial."""
    ticks = [
        _make_tick(tick=0, actions=[("a", _make_perception(ActionType.OBSERVE))]),
        _make_tick(tick=1, actions=[("b", _make_perception(ActionType.OBSERVE))]),
        _make_tick(tick=2, actions=[("a", _make_perception(ActionType.OBSERVE))]),
    ]
    assert is_trivial_scene(ticks) is True


def test_is_trivial_scene_few_observe_only_ticks():
    """≤2 ticks with only observe actions → trivial."""
    ticks = [
        _make_tick(tick=0, actions=[("a", _make_perception(ActionType.OBSERVE))]),
        _make_tick(tick=1, actions=[("b", _make_perception(ActionType.OBSERVE))]),
    ]
    assert is_trivial_scene(ticks) is True


def test_is_trivial_scene_normal_with_speech():
    """A regular scene with multiple speaking ticks is not trivial."""
    speech = ("a", _make_perception(ActionType.SPEAK, action_content="嘿"))
    ticks = [
        _make_tick(tick=0, speech=speech),
        _make_tick(tick=1, speech=speech),
        _make_tick(tick=2, speech=speech),
    ]
    assert is_trivial_scene(ticks) is False


def test_is_trivial_scene_disruptive_action_in_long_scene():
    """In a >2-tick scene, a disruptive non_verbal that production routes
    through environmental_event is NOT trivial."""
    disruptive = ("a", _make_perception(
        ActionType.NON_VERBAL,
        is_disruptive=True,
        action_content="拍桌子",
    ))
    # Production: resolve_tick sets environmental_event when is_disruptive=True
    ticks = [
        _make_tick(tick=0, actions=[disruptive], env_event="【动作】张伟: 拍桌子"),
        _make_tick(tick=1),
        _make_tick(tick=2),
    ]
    assert is_trivial_scene(ticks) is False


def test_is_trivial_scene_short_with_only_env_is_still_trivial():
    """≤2 ticks with env but no speech and no disruptive action → trivial.
    Background environment events alone don't justify a reflection LLM call."""
    ticks = [
        _make_tick(tick=0, env_event="老师走进来"),
    ]
    assert is_trivial_scene(ticks) is True


# --- apply_trivial_scene_result ---


def _setup_world(tmp_path):
    agents_dir = tmp_path / "agents"
    world_dir = tmp_path / "world"
    agents_dir.mkdir()
    world_dir.mkdir()
    return WorldStorage(agents_dir=agents_dir, world_dir=world_dir), agents_dir


def _setup_agent(
    agents_dir,
    aid: str,
    name: str = "张伟",
    role: Role = Role.STUDENT,
) -> AgentProfile:
    profile = AgentProfile(
        agent_id=aid, name=name, gender=Gender.MALE, role=role,
        academics=Academics(overall_rank=OverallRank.MIDDLE),
        family_background=FamilyBackground(pressure_level=PressureLevel.MEDIUM),
    )
    agent_dir = agents_dir / aid
    agent_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(agent_dir / "profile.json", profile.model_dump())
    state = AgentState(
        emotion=Emotion.HAPPY,
        active_concerns=[ActiveConcern(text="existing", intensity=5)],
    )
    atomic_write_json(agent_dir / "state.json", state.model_dump())
    rels = RelationshipFile(relationships={
        "other": Relationship(target_name="李明", target_id="other", favorability=10),
    })
    atomic_write_json(agent_dir / "relationships.json", rels.model_dump())
    return profile


def _make_scene(
    scene_index: int = 0,
    day: int = 1,
    time: str = "08:45",
    name: str = "课间",
    location: str = "教室",
    agent_ids: list[str] | None = None,
) -> Scene:
    return Scene(
        scene_index=scene_index, day=day, time=time, name=name,
        location=location, density=SceneDensity.LOW,
        agent_ids=agent_ids or ["a"],
    )


def test_trivial_scene_no_state_change(tmp_path):
    """apply_trivial_scene_result must NOT touch emotion / concerns / memories / relationships."""
    world, agents_dir = _setup_world(tmp_path)
    profile = _setup_agent(agents_dir, "a")
    profiles = {"a": profile}
    scene = _make_scene()

    apply_trivial_scene_result(["a"], world, scene, day=1, profiles=profiles)

    state = world.get_agent("a").load_state()
    rels = world.get_agent("a").load_relationships()
    km = world.get_agent("a").load_key_memories()

    # State preserved
    assert state.emotion == Emotion.HAPPY
    assert len(state.active_concerns) == 1
    assert state.active_concerns[0].text == "existing"
    assert state.active_concerns[0].intensity == 5

    # Relationships preserved
    assert rels.relationships["other"].favorability == 10

    # No new key memories
    assert len(km.memories) == 0

    # today.md got the placeholder entry
    today = world.get_agent("a").read_today_md()
    assert "课间" in today
    assert "没有特别发生什么" in today


# --- relationship auto-extension ---


def _setup_two_agent_world(tmp_path):
    """Create a two-agent world: 'a' (张伟) and 'b' (李明)."""
    world, agents_dir = _setup_world(tmp_path)
    profile_a = _setup_agent(agents_dir, "a", "张伟")
    profile_b = _setup_agent(agents_dir, "b", "李明")
    profiles = {"a": profile_a, "b": profile_b}
    # Wipe a's relationships file (default to empty so we can test
    # auto-insertion from a clean slate)
    empty_rels = RelationshipFile()
    atomic_write_json(agents_dir / "a" / "relationships.json", empty_rels.model_dump())
    return world, profiles


def _make_event_manager() -> EventQueueManager:
    return EventQueueManager(EventQueue(), random.Random(0))


def test_relationship_auto_insert_for_unknown_target(tmp_path):
    """When LLM names an in-profiles agent that's not yet in this agent's
    relationships file, the entry should be auto-inserted (not dropped)."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])

    refl = AgentReflection(
        emotion=Emotion.CALM,
        relationship_changes=[
            AgentRelChange(to_agent="李明", favorability=3, trust=2, understanding=1),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world,
        scene=scene,
        group_agent_ids=["a", "b"],
        day=1,
        group_id=0,
        profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    assert "b" in rels_a.relationships
    assert rels_a.relationships["b"].target_name == "李明"
    assert rels_a.relationships["b"].label == "同学"
    # Auto-inserted at zero, then delta applied
    assert rels_a.relationships["b"].favorability == 3
    assert rels_a.relationships["b"].trust == 2
    assert rels_a.relationships["b"].understanding == 1


def test_relationship_change_dropped_for_hallucinated_name(tmp_path):
    """LLM-fabricated target name (not in profiles) should be dropped, not crash."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])

    refl = AgentReflection(
        emotion=Emotion.CALM,
        relationship_changes=[
            AgentRelChange(to_agent="幽灵同学", favorability=5, trust=5, understanding=5),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world,
        scene=scene,
        group_agent_ids=["a", "b"],
        day=1,
        group_id=0,
        profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    # No entry created for the hallucinated name
    assert "幽灵同学" not in rels_a.relationships
    assert len(rels_a.relationships) == 0


def test_relationship_change_applied_to_existing_target(tmp_path):
    """Regression: when target already exists, the delta is applied to the
    snapshotted baseline (idempotent)."""
    world, profiles = _setup_two_agent_world(tmp_path)
    # Pre-seed a's relationship with b at favorability=10
    rels = RelationshipFile(relationships={
        "b": Relationship(
            target_name="李明", target_id="b",
            favorability=10, trust=5, understanding=20,
        ),
    })
    atomic_write_json(world.agents_dir / "a" / "relationships.json", rels.model_dump())

    scene = _make_scene(agent_ids=["a", "b"])
    refl = AgentReflection(
        emotion=Emotion.CALM,
        relationship_changes=[
            AgentRelChange(to_agent="李明", favorability=2, trust=-1, understanding=3),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world,
        scene=scene,
        group_agent_ids=["a", "b"],
        day=1,
        group_id=0,
        profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    assert rels_a.relationships["b"].favorability == 12  # 10 + 2
    assert rels_a.relationships["b"].trust == 4         # 5 - 1
    assert rels_a.relationships["b"].understanding == 23  # 20 + 3


# --- relationship label respects source role ---


def _setup_teacher_student_world(tmp_path):
    """Create a two-agent world: teacher 't' (何老师) and student 's' (林昭宇)."""
    world, agents_dir = _setup_world(tmp_path)
    profile_t = _setup_agent(agents_dir, "t", "何老师", role=Role.HOMEROOM_TEACHER)
    profile_s = _setup_agent(agents_dir, "s", "林昭宇", role=Role.STUDENT)
    profiles = {"t": profile_t, "s": profile_s}
    # Wipe both sides' relationships so auto-insert fires from a clean slate.
    empty_rels = RelationshipFile()
    atomic_write_json(agents_dir / "t" / "relationships.json", empty_rels.model_dump())
    atomic_write_json(agents_dir / "s" / "relationships.json", empty_rels.model_dump())
    return world, profiles


def test_relationship_auto_insert_label_teacher_to_student(tmp_path):
    """When a HOMEROOM_TEACHER agent auto-inserts a student into their
    relationships, the label must be '学生' — not '同学'. Prior bug: label was
    only picked from the TARGET's role, which meant teacher→student fell
    through to '同学' and produced obviously wrong labels in state dumps."""
    world, profiles = _setup_teacher_student_world(tmp_path)
    scene = _make_scene(agent_ids=["t", "s"], name="早读")

    refl = AgentReflection(
        emotion=Emotion.CALM,
        relationship_changes=[
            AgentRelChange(to_agent="林昭宇", favorability=2, trust=1, understanding=3),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"t": refl},
        world=world, scene=scene,
        group_agent_ids=["t", "s"],
        day=1, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_t = world.get_agent("t").load_relationships()
    assert "s" in rels_t.relationships
    assert rels_t.relationships["s"].label == "学生"
    assert rels_t.relationships["s"].target_name == "林昭宇"


def test_relationship_auto_insert_label_student_to_teacher(tmp_path):
    """When a STUDENT agent auto-inserts a teacher into their relationships,
    the label must be '老师'."""
    world, profiles = _setup_teacher_student_world(tmp_path)
    scene = _make_scene(agent_ids=["t", "s"], name="早读")

    refl = AgentReflection(
        emotion=Emotion.NEUTRAL,
        relationship_changes=[
            AgentRelChange(to_agent="何老师", favorability=3, trust=2, understanding=1),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"s": refl},
        world=world, scene=scene,
        group_agent_ids=["t", "s"],
        day=1, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_s = world.get_agent("s").load_relationships()
    assert "t" in rels_s.relationships
    assert rels_s.relationships["t"].label == "老师"


def test_relationship_auto_insert_label_student_to_student_is_tongxue(tmp_path):
    """Regression: student→student auto-insert must still land on '同学'."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])

    refl = AgentReflection(
        emotion=Emotion.CALM,
        relationship_changes=[
            AgentRelChange(to_agent="李明", favorability=1, trust=1, understanding=1),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=1, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    assert rels_a.relationships["b"].label == "同学"


# --- recent_interactions population ---


def test_recent_interactions_recorded_on_any_nonzero_change(tmp_path):
    """Every relationship_change with non-zero deltas must append an
    interaction tag so later consumers can see 'we interacted'."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"], name="午饭", day=2)

    refl = AgentReflection(
        emotion=Emotion.HAPPY,
        relationship_changes=[
            AgentRelChange(to_agent="李明", favorability=3, trust=0, understanding=0),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=2, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    # Positive favorability delta → '+' valence prefix on the scene name.
    assert rels_a.relationships["b"].recent_interactions == ["Day 2 +午饭"]


def test_recent_interactions_not_recorded_for_zero_change(tmp_path):
    """A relationship_change with all deltas == 0 must NOT add a tag —
    the LLM produced a no-op and there's no interaction to record."""
    world, profiles = _setup_two_agent_world(tmp_path)
    # Pre-seed existing relationship so the edit path runs.
    rels = RelationshipFile(relationships={
        "b": Relationship(
            target_name="李明", target_id="b",
            favorability=5, trust=5, understanding=5,
            recent_interactions=[],
        ),
    })
    atomic_write_json(world.agents_dir / "a" / "relationships.json", rels.model_dump())
    scene = _make_scene(agent_ids=["a", "b"], name="早读")

    refl = AgentReflection(
        emotion=Emotion.NEUTRAL,
        relationship_changes=[
            AgentRelChange(to_agent="李明", favorability=0, trust=0, understanding=0),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=1, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    assert rels_a.relationships["b"].recent_interactions == []


def test_recent_interactions_dedup_within_same_scene(tmp_path):
    """Multiple relationship_change records in the SAME (day, scene) pair
    should collapse to a single tag — no spam from multi-tick reflections."""
    world, profiles = _setup_two_agent_world(tmp_path)
    # Pre-seed so we can feed two changes against the same target.
    rels = RelationshipFile(relationships={
        "b": Relationship(
            target_name="李明", target_id="b",
            favorability=0, trust=0, understanding=0,
            recent_interactions=[],
        ),
    })
    atomic_write_json(world.agents_dir / "a" / "relationships.json", rels.model_dump())
    scene = _make_scene(agent_ids=["a", "b"], name="课间", day=1)

    refl = AgentReflection(
        emotion=Emotion.CALM,
        relationship_changes=[
            AgentRelChange(to_agent="李明", favorability=1, trust=0, understanding=0),
            AgentRelChange(to_agent="李明", favorability=1, trust=0, understanding=0),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=1, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    # Two positive-delta rows against the same target in the same scene
    # dedup to a single "+课间" tag — they share a valence so the full tag
    # string is identical.
    assert rels_a.relationships["b"].recent_interactions == ["Day 1 +课间"]


def test_recent_interactions_capped_at_setting(tmp_path):
    """The per-relationship interaction log must be capped at
    settings.max_recent_interactions (default 10), keeping the most
    recent entries."""
    from sim.config import settings

    world, profiles = _setup_two_agent_world(tmp_path)
    # Pre-seed with a full 10-entry log at the current cap.
    seeded = [f"Day {d} 预存" for d in range(1, 11)]
    rels = RelationshipFile(relationships={
        "b": Relationship(
            target_name="李明", target_id="b",
            favorability=0, trust=0, understanding=0,
            recent_interactions=list(seeded),
        ),
    })
    atomic_write_json(world.agents_dir / "a" / "relationships.json", rels.model_dump())
    scene = _make_scene(agent_ids=["a", "b"], name="午饭", day=11)

    refl = AgentReflection(
        emotion=Emotion.CALM,
        relationship_changes=[
            AgentRelChange(to_agent="李明", favorability=1, trust=0, understanding=0),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=11, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    log = rels_a.relationships["b"].recent_interactions
    assert len(log) == settings.max_recent_interactions
    # Oldest seeded entry (Day 1) should have been evicted to make room
    # for the new Day 11 entry. The new entry carries a '+' valence prefix
    # since favorability delta was positive.
    assert "Day 1 预存" not in log
    assert "Day 11 +午饭" == log[-1]


def test_recent_interactions_negative_valence_marker(tmp_path):
    """A net-negative favorability+trust delta must produce a '−' valence
    prefix so downstream prompts can distinguish friction interactions
    from warm ones at a glance, without having to re-derive affect from
    the current absolute scores."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"], name="宿舍夜聊", day=4)

    refl = AgentReflection(
        emotion=Emotion.ANGRY,
        relationship_changes=[
            AgentRelChange(
                to_agent="李明", favorability=-4, trust=-2, understanding=1,
            ),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=4, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    assert rels_a.relationships["b"].recent_interactions == ["Day 4 −宿舍夜聊"]


def test_recent_interactions_neutral_valence_marker(tmp_path):
    """A non-empty change whose favorability+trust sum is zero (e.g. pure
    understanding bump, or offsetting fav/trust) must use the neutral '·'
    marker — still records the interaction happened, but without claiming
    a direction."""
    world, profiles = _setup_two_agent_world(tmp_path)
    # Pre-seed so the edit path runs.
    rels = RelationshipFile(relationships={
        "b": Relationship(
            target_name="李明", target_id="b",
            favorability=0, trust=0, understanding=0,
            recent_interactions=[],
        ),
    })
    atomic_write_json(world.agents_dir / "a" / "relationships.json", rels.model_dump())
    scene = _make_scene(agent_ids=["a", "b"], name="上课", day=5)

    refl = AgentReflection(
        emotion=Emotion.CALM,
        relationship_changes=[
            # understanding-only change: fav+trust = 0, but the row still
            # represents a real interaction that should be logged.
            AgentRelChange(
                to_agent="李明", favorability=0, trust=0, understanding=3,
            ),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=5, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    assert rels_a.relationships["b"].recent_interactions == ["Day 5 ·上课"]


def test_recent_interactions_mixed_valence_not_deduped(tmp_path):
    """Two relationship_change rows against the same target in the same
    scene with OPPOSITE valences must NOT collapse — they represent
    genuinely different moments within the scene (e.g. "disagreed, then
    reconciled") and both tags belong in the timeline."""
    world, profiles = _setup_two_agent_world(tmp_path)
    rels = RelationshipFile(relationships={
        "b": Relationship(
            target_name="李明", target_id="b",
            favorability=0, trust=0, understanding=0,
            recent_interactions=[],
        ),
    })
    atomic_write_json(world.agents_dir / "a" / "relationships.json", rels.model_dump())
    scene = _make_scene(agent_ids=["a", "b"], name="课间", day=3)

    refl = AgentReflection(
        emotion=Emotion.NEUTRAL,
        relationship_changes=[
            AgentRelChange(to_agent="李明", favorability=-2, trust=0, understanding=0),
            AgentRelChange(to_agent="李明", favorability=3, trust=1, understanding=0),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=3, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    rels_a = world.get_agent("a").load_relationships()
    log = rels_a.relationships["b"].recent_interactions
    assert "Day 3 −课间" in log
    assert "Day 3 +课间" in log


# --- importance write threshold ---


def test_importance_below_threshold_dropped(tmp_path):
    """A memory with importance < settings.key_memory_write_threshold (=3)
    must not land in key_memories.json."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])

    refl = AgentReflection(
        emotion=Emotion.NEUTRAL,
        memories=[
            AgentMemoryCandidate(
                text="低强度记忆",
                importance=2,  # below threshold
                people=["李明"],
                location="教室",
            ),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=1, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    km = world.get_agent("a").load_key_memories()
    assert all(m.text != "低强度记忆" for m in km.memories)


def test_importance_at_threshold_persists(tmp_path):
    """A memory at importance == threshold (=3) lands in key_memories."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])

    refl = AgentReflection(
        emotion=Emotion.NEUTRAL,
        memories=[
            AgentMemoryCandidate(
                text="刚好达标的记忆",
                importance=3,  # at threshold
                people=["李明"],
                location="教室",
            ),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=1, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    km = world.get_agent("a").load_key_memories()
    assert any(m.text == "刚好达标的记忆" for m in km.memories)


def test_importance_above_threshold_persists(tmp_path):
    """A high-importance memory passes the threshold gate."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])

    refl = AgentReflection(
        emotion=Emotion.NEUTRAL,
        memories=[
            AgentMemoryCandidate(
                text="重要记忆",
                importance=8,
                people=["李明"],
                location="教室",
            ),
        ],
    )

    apply_scene_end_results(
        narrative=NarrativeExtraction(),
        reflections={"a": refl},
        world=world, scene=scene,
        group_agent_ids=["a", "b"],
        day=1, group_id=0, profiles=profiles,
        event_manager=_make_event_manager(),
    )

    km = world.get_agent("a").load_key_memories()
    assert any(m.text == "重要记忆" for m in km.memories)


# --- cite_ticks 3-layer validation for new_events ---


def _make_speech_perception(content: str) -> PerceptionOutput:
    return PerceptionOutput(
        observation="x",
        inner_thought="x",
        emotion=Emotion.NEUTRAL,
        action_type=ActionType.SPEAK,
        action_content=content,
        action_target=None,
        urgency=5,
        is_disruptive=False,
    )


def _make_speech_tick(tick_idx: int, agent_id: str, content: str) -> dict:
    out = _make_speech_perception(content)
    return {
        "tick": tick_idx,
        "agent_outputs": {agent_id: out},
        "resolved_speech": (agent_id, out),
        "resolved_actions": [],
        "environmental_event": None,
        "exits": [],
    }


def test_legit_event_passes_validation(tmp_path):
    """An event whose text overlaps strongly with its cited tick passes,
    and cite_ticks + group_index are persisted on the Event."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])
    tick_records = [
        _make_speech_tick(0, "a", "我昨晚和朋友去打篮球了"),
        _make_speech_tick(1, "b", "我也喜欢篮球"),
    ]

    narrative = NarrativeExtraction(
        new_events=[
            NewEventCandidate(
                text="昨晚和朋友去打篮球",
                category="八卦",
                witnesses=["张伟", "李明"],
                cite_ticks=[1],  # 1-indexed → tick_records[0]
                spread_probability=0.5,
            ),
        ],
    )

    em = _make_event_manager()
    apply_scene_end_results(
        narrative=narrative,
        reflections={},
        world=world,
        scene=scene,
        group_agent_ids=["a", "b"],
        day=1,
        group_id=2,  # non-zero to make group_index propagation observable
        profiles=profiles,
        event_manager=em,
        tick_records=tick_records,
    )
    assert len(em.eq.events) == 1
    persisted = em.eq.events[0]
    assert persisted.cite_ticks == [1]
    assert persisted.group_index == 2


def test_missing_cite_ticks_drops_event(tmp_path):
    """Layer 1: an event with no cite_ticks must be dropped."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])
    tick_records = [_make_speech_tick(0, "a", "随便聊一句")]

    narrative = NarrativeExtraction(
        new_events=[
            NewEventCandidate(
                text="某个未注明 source 的 event",
                cite_ticks=[],  # empty
            ),
        ],
    )
    em = _make_event_manager()
    apply_scene_end_results(
        narrative=narrative, reflections={}, world=world, scene=scene,
        group_agent_ids=["a", "b"], day=1, group_id=0, profiles=profiles,
        event_manager=em, tick_records=tick_records,
    )
    assert len(em.eq.events) == 0


def test_invalid_cite_ticks_drops_event(tmp_path):
    """Layer 2: cite into a tick number that doesn't exist (e.g. 0 in
    1-indexed space, or 99) must be dropped."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])
    tick_records = [_make_speech_tick(0, "a", "随便聊一句")]

    narrative = NarrativeExtraction(
        new_events=[
            NewEventCandidate(text="event A", cite_ticks=[0]),  # 0 not valid
            NewEventCandidate(text="event B", cite_ticks=[99]),  # out of range
        ],
    )
    em = _make_event_manager()
    apply_scene_end_results(
        narrative=narrative, reflections={}, world=world, scene=scene,
        group_agent_ids=["a", "b"], day=1, group_id=0, profiles=profiles,
        event_manager=em, tick_records=tick_records,
    )
    assert len(em.eq.events) == 0


def test_cite_tick_1_indexed_matches_tick_record_0(tmp_path):
    """Regression: LLM emits cite_ticks=[1] and that must map to
    tick_records[0] (the 0-indexed first tick), because narrative.py
    displays `[Tick {tick + 1}]`."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])
    tick_records = [_make_speech_tick(0, "a", "听说今天食堂出新菜了")]

    narrative = NarrativeExtraction(
        new_events=[
            NewEventCandidate(
                text="食堂出新菜",
                cite_ticks=[1],  # 1-indexed → maps to tick 0 raw content
            ),
        ],
    )
    em = _make_event_manager()
    apply_scene_end_results(
        narrative=narrative, reflections={}, world=world, scene=scene,
        group_agent_ids=["a", "b"], day=1, group_id=0, profiles=profiles,
        event_manager=em, tick_records=tick_records,
    )
    assert len(em.eq.events) == 1


def test_bigram_overlap_blocks_fabricated_event(tmp_path):
    """Layer 3: an event with little textual overlap with the cited tick
    (the 'hallucinated/expanded' failure mode) must be dropped."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])
    tick_records = [_make_speech_tick(0, "a", "数学考试要到了")]

    narrative = NarrativeExtraction(
        new_events=[
            NewEventCandidate(
                # Hallucination: the tick mentioned no such thing
                text="昨晚玩手机被教导处抓到然后被全班同学嘲笑",
                cite_ticks=[1],
            ),
        ],
    )
    em = _make_event_manager()
    apply_scene_end_results(
        narrative=narrative, reflections={}, world=world, scene=scene,
        group_agent_ids=["a", "b"], day=1, group_id=0, profiles=profiles,
        event_manager=em, tick_records=tick_records,
    )
    assert len(em.eq.events) == 0


def test_bigram_overlap_blocks_expansion_case(tmp_path):
    """Layer 3 specifically targets the 'short cite, long event' failure:
    LLM cites a short tick like '被批评了' but writes a long elaborated
    event with details that aren't in the cite."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])
    tick_records = [_make_speech_tick(0, "a", "被批评了")]

    narrative = NarrativeExtraction(
        new_events=[
            NewEventCandidate(
                text="昨晚玩手机被教导处主任在走廊发现并叫到办公室谈话半小时",
                cite_ticks=[1],
            ),
        ],
    )
    em = _make_event_manager()
    apply_scene_end_results(
        narrative=narrative, reflections={}, world=world, scene=scene,
        group_agent_ids=["a", "b"], day=1, group_id=0, profiles=profiles,
        event_manager=em, tick_records=tick_records,
    )
    assert len(em.eq.events) == 0


def test_cite_ticks_in_summarized_range_drops_event(tmp_path):
    """When tick_records > 12, ticks 0-5 (0-indexed) are summarized away in
    narrative.py and the LLM cannot have legitimately cited them. Such cites
    must be treated as invalid (Layer 2 drop)."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])
    # Build 15 ticks → triggers mid-scene summarization (ticks 0-5 collapsed)
    tick_records = [
        _make_speech_tick(i, "a" if i % 2 == 0 else "b", f"内容{i}")
        for i in range(15)
    ]

    narrative = NarrativeExtraction(
        new_events=[
            NewEventCandidate(
                text="内容3",
                cite_ticks=[3],  # 1-indexed → tick 2, inside summarized range
            ),
        ],
    )
    em = _make_event_manager()
    apply_scene_end_results(
        narrative=narrative, reflections={}, world=world, scene=scene,
        group_agent_ids=["a", "b"], day=1, group_id=0, profiles=profiles,
        event_manager=em, tick_records=tick_records,
    )
    assert len(em.eq.events) == 0


def test_cite_ticks_valid_when_scene_short_enough(tmp_path):
    """At exactly 12 ticks (the threshold) summarization does NOT trigger,
    so all tick numbers are valid."""
    world, profiles = _setup_two_agent_world(tmp_path)
    scene = _make_scene(agent_ids=["a", "b"])
    tick_records = [
        _make_speech_tick(i, "a" if i % 2 == 0 else "b", f"今天数学课讲了三角函数{i}")
        for i in range(12)
    ]

    narrative = NarrativeExtraction(
        new_events=[
            NewEventCandidate(
                text="数学课讲了三角函数",
                cite_ticks=[3],  # 1-indexed → tick 2
            ),
        ],
    )
    em = _make_event_manager()
    apply_scene_end_results(
        narrative=narrative, reflections={}, world=world, scene=scene,
        group_agent_ids=["a", "b"], day=1, group_id=0, profiles=profiles,
        event_manager=em, tick_records=tick_records,
    )
    assert len(em.eq.events) == 1
