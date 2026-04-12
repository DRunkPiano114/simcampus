"""Tests for PDA gated-tick storage hygiene.

When an agent is gated by the PDA loop (no fresh LLM perception this tick,
reusing the last output verbatim), their observation/inner_thought are
stale copies. They must NOT be:

- re-rendered into the agent's private_history via format_agent_transcript
- serialized into the scene JSON log's minds dict via serialize_tick_records

Either leak causes the same long line to appear across consecutive ticks,
which pollutes downstream reflection prompts and confuses human review of
scene logs.
"""

from sim.interaction.narrative import format_agent_transcript
from sim.interaction.orchestrator import serialize_tick_records
from sim.models.agent import (
    Academics,
    AgentProfile,
    Emotion,
    FamilyBackground,
    Gender,
    OverallRank,
    PressureLevel,
    Role,
)
from sim.models.dialogue import ActionType, PerceptionOutput


def _make_profile(aid: str, name: str) -> AgentProfile:
    return AgentProfile(
        agent_id=aid, name=name, gender=Gender.MALE, role=Role.STUDENT,
        academics=Academics(overall_rank=OverallRank.MIDDLE),
        family_background=FamilyBackground(pressure_level=PressureLevel.MEDIUM),
    )


def _observe_output(text: str) -> PerceptionOutput:
    """Passive OBSERVE output as would be produced by _make_gated_output
    (same observation/inner_thought across multiple ticks)."""
    return PerceptionOutput(
        observation=text,
        inner_thought=f"心里想：{text}",
        emotion=Emotion.CALM,
        action_type=ActionType.OBSERVE,
        action_content=None,
        action_target=None,
        urgency=2,
        is_disruptive=False,
    )


def _fresh_speech_output(text: str) -> PerceptionOutput:
    return PerceptionOutput(
        observation=f"我刚说完：{text}",
        inner_thought=f"希望他们听进去了：{text}",
        emotion=Emotion.HAPPY,
        action_type=ActionType.SPEAK,
        action_content=text,
        action_target=None,
        urgency=5,
        is_disruptive=True,
    )


# --- narrative.format_agent_transcript ---


def test_private_history_skips_self_gated_ticks():
    """If agent 'a' was gated on tick 2, their own private_history for that
    tick must NOT be appended — the observation/inner_thought there is just
    a stale reuse of tick 1's fresh perception."""
    profiles = {"a": _make_profile("a", "张伟"), "b": _make_profile("b", "李明")}

    shared_observation = "宿舍里重新陷入了沉默"
    fresh_a_tick_1 = _observe_output(shared_observation)
    gated_a_tick_2 = _observe_output(shared_observation)  # same strings
    gated_a_tick_3 = _observe_output(shared_observation)

    tick_records = [
        {
            "tick": 0,
            "agent_outputs": {"a": fresh_a_tick_1, "b": _fresh_speech_output("早睡吧")},
            "gated_agents": [],
            "resolved_speech": ("b", _fresh_speech_output("早睡吧")),
            "resolved_actions": [],
            "environmental_event": None,
            "exits": [],
        },
        {
            "tick": 1,
            "agent_outputs": {"a": gated_a_tick_2, "b": _fresh_speech_output("困了")},
            "gated_agents": ["a"],
            "resolved_speech": ("b", _fresh_speech_output("困了")),
            "resolved_actions": [],
            "environmental_event": None,
            "exits": [],
        },
        {
            "tick": 2,
            "agent_outputs": {"a": gated_a_tick_3, "b": _fresh_speech_output("晚安")},
            "gated_agents": ["a"],
            "resolved_speech": ("b", _fresh_speech_output("晚安")),
            "resolved_actions": [],
            "environmental_event": None,
            "exits": [],
        },
    ]

    _, private = format_agent_transcript(tick_records, "a", profiles)

    # Agent 'a' had 1 fresh tick (tick 0) + 2 gated (ticks 1, 2).
    # Each rendered tick adds two lines: "[Tick N] <obs>" and "  (内心) <thought>".
    # Count tick headers to assert exactly one tick contributed.
    tick_headers = [ln for ln in private if ln.startswith("[Tick ")]
    assert len(tick_headers) == 1, (
        f"Expected exactly 1 tick header, got {len(tick_headers)}: {private}"
    )
    # The surviving entry should be from tick 1 (the 1-indexed label of tick 0)
    assert tick_headers[0].startswith("[Tick 1]")
    # The stale reused strings must not appear under [Tick 2] or [Tick 3]
    assert not any(ln.startswith("[Tick 2]") for ln in private)
    assert not any(ln.startswith("[Tick 3]") for ln in private)


def test_private_history_keeps_other_agents_gated_ticks():
    """When 'a' was gated but 'b' was not, 'b'-perspective transcript must
    still contain 'b'-perspective private_history for those ticks."""
    profiles = {"a": _make_profile("a", "张伟"), "b": _make_profile("b", "李明")}

    tick_records = [
        {
            "tick": 0,
            "agent_outputs": {
                "a": _observe_output("看着李明"),
                "b": _fresh_speech_output("我开始说话了"),
            },
            "gated_agents": ["a"],  # 'a' gated, 'b' fresh
            "resolved_speech": ("b", _fresh_speech_output("我开始说话了")),
            "resolved_actions": [],
            "environmental_event": None,
            "exits": [],
        },
    ]

    _, private_b = format_agent_transcript(tick_records, "b", profiles)

    # 'b' was NOT gated this tick, so their private history should include
    # their own observation/inner_thought.
    assert any("我刚说完：我开始说话了" in ln for ln in private_b)


def test_private_history_backward_compat_without_gated_field():
    """Tick records that predate the gated_agents field (empty / missing)
    must still render full private_history. Backward compatibility for
    older scene JSONs in logs/."""
    profiles = {"a": _make_profile("a", "张伟")}

    tick_records = [
        {
            "tick": 0,
            "agent_outputs": {"a": _fresh_speech_output("hi")},
            # no "gated_agents" key at all
            "resolved_speech": ("a", _fresh_speech_output("hi")),
            "resolved_actions": [],
            "environmental_event": None,
            "exits": [],
        },
    ]

    _, private = format_agent_transcript(tick_records, "a", profiles)

    assert any("我刚说完：hi" in ln for ln in private)


# --- orchestrator.serialize_tick_records ---


def test_serialize_tick_records_omits_gated_agents_from_minds():
    """Gated agents must not appear in the serialized `minds` dict — their
    perception is a stale reuse and would pollute the scene JSON log with
    duplicate lines across consecutive ticks."""
    profiles = {"a": _make_profile("a", "张伟"), "b": _make_profile("b", "李明")}

    tick_records = [
        {
            "tick": 0,
            "agent_outputs": {
                "a": _observe_output("看着李明"),
                "b": _fresh_speech_output("你好"),
            },
            "gated_agents": ["a"],
            "resolved_speech": ("b", _fresh_speech_output("你好")),
            "resolved_actions": [],
            "environmental_event": None,
            "exits": [],
        },
    ]

    serialized = serialize_tick_records(tick_records, profiles)

    assert len(serialized) == 1
    minds = serialized[0]["minds"]
    assert "a" not in minds  # gated — excluded
    assert "b" in minds      # fresh — kept
    # gated_agents list preserved for downstream debug tooling
    assert serialized[0]["gated_agents"] == ["a"]


def test_serialize_tick_records_backward_compat_without_gated_field():
    """Tick records without a gated_agents key must serialize every agent's
    output as before (no ticks filtered)."""
    profiles = {"a": _make_profile("a", "张伟")}

    tick_records = [
        {
            "tick": 0,
            "agent_outputs": {"a": _fresh_speech_output("hi")},
            "resolved_speech": ("a", _fresh_speech_output("hi")),
            "resolved_actions": [],
            "environmental_event": None,
            "exits": [],
        },
    ]

    serialized = serialize_tick_records(tick_records, profiles)

    assert serialized[0]["minds"] == {
        "a": serialized[0]["minds"]["a"],  # presence
    }
    assert "a" in serialized[0]["minds"]
    assert serialized[0]["gated_agents"] == []
