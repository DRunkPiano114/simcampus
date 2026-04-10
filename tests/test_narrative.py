from sim.models.agent import (
    Academics, AgentProfile, Emotion, FamilyBackground,
    Gender, OverallRank, PressureLevel, Role,
)
from sim.models.dialogue import ActionType, PerceptionOutput
from sim.interaction.narrative import (
    format_agent_transcript,
    format_latest_event,
    format_public_transcript,
)


def _make_profile(aid: str, name: str) -> AgentProfile:
    return AgentProfile(
        agent_id=aid, name=name, gender=Gender.MALE, role=Role.STUDENT,
        academics=Academics(overall_rank=OverallRank.MIDDLE),
        family_background=FamilyBackground(pressure_level=PressureLevel.MEDIUM),
    )


def _make_output(
    action_type=ActionType.OBSERVE, urgency=5, action_content=None,
    action_target=None, emotion=Emotion.NEUTRAL,
) -> PerceptionOutput:
    return PerceptionOutput(
        observation="看了一下", inner_thought="没啥",
        emotion=emotion, action_type=action_type,
        action_content=action_content, action_target=action_target,
        urgency=urgency,
    )


PROFILES = {
    "a": _make_profile("a", "张伟"),
    "b": _make_profile("b", "李明"),
}


def test_public_transcript_speech():
    records = [{
        "tick": 0,
        "agent_outputs": {
            "a": _make_output(ActionType.SPEAK, action_content="你好"),
        },
        "resolved_speech": ("a", _make_output(ActionType.SPEAK, action_content="你好")),
        "resolved_actions": [],
        "environmental_event": None,
        "exits": [],
    }]
    result = format_public_transcript(records, PROFILES)
    assert "张伟" in result
    assert "你好" in result


def test_agent_transcript_includes_private():
    records = [{
        "tick": 0,
        "agent_outputs": {
            "a": _make_output(ActionType.OBSERVE),
        },
        "resolved_speech": None,
        "resolved_actions": [],
        "environmental_event": None,
        "exits": [],
    }]
    public, private = format_agent_transcript(records, "a", PROFILES)
    assert len(private) >= 1  # observation + inner thought


def test_mid_scene_summarization():
    """After 12 ticks, first 6 are summarized."""
    records = []
    for i in range(14):
        records.append({
            "tick": i,
            "agent_outputs": {
                "a": _make_output(ActionType.SPEAK, action_content=f"话{i}"),
            },
            "resolved_speech": ("a", _make_output(ActionType.SPEAK, action_content=f"话{i}")),
            "resolved_actions": [],
            "environmental_event": None,
            "exits": [],
        })
    result = format_public_transcript(records, PROFILES)
    # Should see summary line for early ticks
    assert "Tick 1-6" in result
    # Should NOT see individual early tick content
    assert "话0" not in result
    # Should see later ticks
    assert "话13" in result


def test_format_latest_event_speech():
    speech = ("a", _make_output(ActionType.SPEAK, action_content="你好", action_target="李明"))
    result = format_latest_event(speech, [], None, [], PROFILES)
    assert "张伟" in result
    assert "你好" in result


def test_format_latest_event_quiet():
    result = format_latest_event(None, [], None, [], PROFILES)
    assert "安静" in result
