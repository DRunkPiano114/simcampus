from random import Random

from sim.models.agent import (
    AgentProfile, AgentState, Academics, DailyPlan, Emotion,
    FamilyBackground, Gender, Intention, OverallRank, PressureLevel, Role,
)
from sim.models.dialogue import ActionType, PerceptionOutput
from sim.interaction.resolution import ResolutionState, resolve_tick


def _make_profile(aid: str, name: str) -> AgentProfile:
    return AgentProfile(
        agent_id=aid, name=name, gender=Gender.MALE, role=Role.STUDENT,
        academics=Academics(overall_rank=OverallRank.MIDDLE),
        family_background=FamilyBackground(pressure_level=PressureLevel.MEDIUM),
    )


def _make_state(**kw) -> AgentState:
    return AgentState(**kw)


def _make_output(
    action_type=ActionType.OBSERVE, urgency=5, action_content=None,
    action_target=None, is_disruptive=False, emotion=Emotion.NEUTRAL,
) -> PerceptionOutput:
    return PerceptionOutput(
        observation="看了一下", inner_thought="没啥",
        emotion=emotion, action_type=action_type,
        action_content=action_content, action_target=action_target,
        urgency=urgency, is_disruptive=is_disruptive,
    )


PROFILES = {
    "a": _make_profile("a", "张伟"),
    "b": _make_profile("b", "李明"),
    "c": _make_profile("c", "王芳"),
}
STATES = {aid: _make_state() for aid in PROFILES}
RNG = Random(42)


def _fresh_state(agents=("a", "b", "c")) -> ResolutionState:
    return ResolutionState(active_agents=set(agents))


def test_quiet_no_termination_before_min_ticks():
    """Quiet ticks but tick_count < min_ticks → no end."""
    state = _fresh_state()
    for _ in range(3):
        outputs = {aid: _make_output() for aid in ("a", "b", "c")}
        result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
        state = result.updated_state
    # tick_count is 3 (meets min), but consecutive_quiet is 3 < 4 (new threshold)
    assert result.scene_should_end is False


def test_quiet_tick_termination():
    """4 consecutive quiet ticks after min_ticks → scene ends."""
    state = _fresh_state()
    state.tick_count = 5  # Already past min
    for _ in range(4):
        outputs = {aid: _make_output() for aid in ("a", "b", "c")}
        result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
        state = result.updated_state
    assert result.scene_should_end is True
    assert state.consecutive_quiet == 4


def test_min_tick_prevents_early_termination():
    """Quiet ticks on tick 1 and 2 shouldn't end scene."""
    state = _fresh_state()
    for _ in range(2):
        outputs = {aid: _make_output() for aid in ("a", "b", "c")}
        result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
        state = result.updated_state
    assert result.scene_should_end is False


def test_single_speaker_passthrough():
    """Only one agent speaks → they win automatically."""
    state = _fresh_state()
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=5, action_content="你好"),
        "b": _make_output(),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert result.resolved_speech is not None
    assert result.resolved_speech[0] == "a"


def test_multiple_speakers_highest_urgency_wins():
    """Multiple speakers → highest urgency wins."""
    state = _fresh_state()
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=8, action_content="我先说"),
        "b": _make_output(ActionType.SPEAK, urgency=3, action_content="我也想说"),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert result.resolved_speech[0] == "a"


def test_addressed_bonus():
    """Agent addressed in previous speech gets +5 bonus."""
    state = _fresh_state()
    # Previous speech addressed 李明 (agent "b")
    last_speech = ("a", _make_output(
        ActionType.SPEAK, urgency=5, action_content="李明你说呢",
        action_target="李明",
    ))
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=6, action_content="继续说"),
        "b": _make_output(ActionType.SPEAK, urgency=4, action_content="好的"),  # 4 + 5 = 9
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, last_speech, RNG)
    assert result.resolved_speech[0] == "b"


def test_intention_bonus():
    """Agent with unfulfilled intention targeting present agent gets +3."""
    states = {
        "a": _make_state(daily_plan=DailyPlan(intentions=[
            Intention(target="李明", goal="聊作业", reason="想问问"),
        ])),
        "b": _make_state(),
        "c": _make_state(),
    }
    state = _fresh_state()
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=5, action_content="诶"),  # 5 + 3 = 8
        "b": _make_output(ActionType.SPEAK, urgency=7, action_content="嗯"),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, states, None, RNG)
    assert result.resolved_speech[0] == "a"


def test_queue_carryover():
    """Losers get queued and carried over with +3/tick bonus."""
    state = _fresh_state()
    # Tick 1: a and b both speak, a wins (higher urgency)
    outputs1 = {
        "a": _make_output(ActionType.SPEAK, urgency=8, action_content="先说"),
        "b": _make_output(ActionType.SPEAK, urgency=5, action_content="我也说"),
        "c": _make_output(),
    }
    result1 = resolve_tick(outputs1, state, PROFILES, STATES, None, RNG)
    assert result1.resolved_speech[0] == "a"
    assert "b" in result1.updated_state.queued_agents

    # Tick 2: b is queued (+3), c speaks with urgency 6
    outputs2 = {
        "a": _make_output(),
        "c": _make_output(ActionType.SPEAK, urgency=6, action_content="换我说"),
    }
    result2 = resolve_tick(outputs2, result1.updated_state, PROFILES, STATES, None, RNG)
    # b's original urgency 5 + 3 (queued 1 tick) = 8 > c's 6
    assert result2.resolved_speech[0] == "b"


def test_queue_expiry():
    """Queued outputs expire after 3 ticks."""
    state = ResolutionState(
        active_agents={"a", "b", "c"},
        queued_agents={
            "b": (_make_output(ActionType.SPEAK, urgency=5, action_content="过期了"), 3),
        },
    )
    outputs = {
        "a": _make_output(),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    # b's queued output should be expired (3+1 > QUEUE_EXPIRY_TICKS=3)
    assert "b" not in result.updated_state.queued_agents
    assert result.resolved_speech is None


def test_queue_target_exit_discard():
    """Queued agent whose target exited gets discarded."""
    state = ResolutionState(
        active_agents={"a", "b", "c"},
        queued_agents={
            "b": (_make_output(ActionType.SPEAK, urgency=8, action_content="等等", action_target="王芳"), 0),
        },
    )
    # c (王芳) exits this tick
    outputs = {
        "a": _make_output(),
        "c": _make_output(ActionType.EXIT, action_content="走了"),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert "c" in result.exits
    assert result.resolved_speech is None  # b's target exited, discarded


def test_disruptive_non_verbal_creates_environmental_event():
    """Disruptive non-verbal action generates environmental event."""
    state = _fresh_state()
    outputs = {
        "a": _make_output(ActionType.NON_VERBAL, urgency=7, action_content="拍了一下桌子", is_disruptive=True),
        "b": _make_output(),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert result.environmental_event is not None
    assert "张伟" in result.environmental_event
    assert "拍了一下桌子" in result.environmental_event


def test_exit_removes_from_active_pool():
    """Exiting agent is removed from active agents."""
    state = _fresh_state()
    outputs = {
        "a": _make_output(ActionType.EXIT, action_content="走了"),
        "b": _make_output(),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert "a" not in result.updated_state.active_agents
    assert "a" in result.exits


def test_empty_group():
    """No agents → scene ends immediately next tick."""
    state = ResolutionState(active_agents=set())
    result = resolve_tick({}, state, PROFILES, STATES, None, RNG)
    assert result.resolved_speech is None


def test_tie_random_tiebreak():
    """Equal scores → winner determined by rng."""
    state = _fresh_state()
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=5, action_content="说1"),
        "b": _make_output(ActionType.SPEAK, urgency=5, action_content="说2"),
        "c": _make_output(),
    }
    # Run multiple times with different seeds, should see both win
    winners = set()
    for seed in range(50):
        result = resolve_tick(outputs, state, PROFILES, STATES, None, Random(seed))
        winners.add(result.resolved_speech[0])
    assert len(winners) == 2  # Both a and b should win at some point


def test_urgency_clustering_fallback():
    """When urgency variance <= 2, bonuses become primary."""
    # Give agent a an intention bonus (+3)
    states = {
        "a": _make_state(daily_plan=DailyPlan(intentions=[
            Intention(target="李明", goal="聊聊", reason="想问"),
        ])),
        "b": _make_state(),
        "c": _make_state(),
    }
    state = _fresh_state()
    # All urgencies are 5 (variance = 0, triggers clustering fallback)
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=5, action_content="诶"),
        "b": _make_output(ActionType.SPEAK, urgency=5, action_content="嗯"),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, states, None, RNG)
    # a has intention bonus +3, b has none → a wins
    assert result.resolved_speech[0] == "a"


def test_non_verbal_simultaneous_with_speech():
    """Non-verbal actions resolve alongside speech."""
    state = _fresh_state()
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=5, action_content="你好"),
        "b": _make_output(ActionType.NON_VERBAL, urgency=3, action_content="低头写字"),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert result.resolved_speech is not None
    assert len(result.resolved_actions) == 1
    assert result.resolved_actions[0][0] == "b"


def test_speech_resets_quiet_count():
    """Speech resets the consecutive quiet counter."""
    state = _fresh_state()
    # Two quiet ticks
    for _ in range(2):
        outputs = {aid: _make_output() for aid in ("a", "b", "c")}
        result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
        state = result.updated_state
    assert state.consecutive_quiet == 2

    # One tick with speech breaks the streak
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=5, action_content="说"),
        "b": _make_output(),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert result.updated_state.consecutive_quiet == 0


def test_non_verbal_allows_quiet_tick():
    """Non-disruptive NON_VERBAL + OBSERVE mix → quiet tick increments."""
    state = _fresh_state()
    outputs = {
        "a": _make_output(ActionType.NON_VERBAL, urgency=3, action_content="低头写字"),
        "b": _make_output(),  # OBSERVE
        "c": _make_output(),  # OBSERVE
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert result.updated_state.consecutive_quiet == 1


def test_disruptive_non_verbal_resets_quiet():
    """Disruptive NON_VERBAL sets environmental_event → counter resets."""
    state = _fresh_state()
    # First: one quiet tick
    outputs = {aid: _make_output() for aid in ("a", "b", "c")}
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    state = result.updated_state
    assert state.consecutive_quiet == 1

    # Then: disruptive action
    outputs = {
        "a": _make_output(ActionType.NON_VERBAL, urgency=7, action_content="拍桌子", is_disruptive=True),
        "b": _make_output(),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert result.updated_state.consecutive_quiet == 0


def test_queued_speaker_prevents_quiet():
    """Non-empty queue → not quiet even if no speech resolved this tick."""
    state = _fresh_state()
    # Two speakers: winner + loser queued
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=8, action_content="先说"),
        "b": _make_output(ActionType.SPEAK, urgency=5, action_content="我也说"),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    # Speech resolved, so not quiet anyway, but queue has b
    assert result.updated_state.consecutive_quiet == 0

    # Next tick: only observers, but b is still queued
    outputs2 = {
        "a": _make_output(),
        "c": _make_output(),
    }
    result2 = resolve_tick(outputs2, result.updated_state, PROFILES, STATES, None, RNG)
    # b speaks from queue → not quiet
    assert result2.updated_state.consecutive_quiet == 0


def test_speech_after_quiet_resets_counter():
    """consecutive_quiet=2 then someone SPEAKs → counter resets to 0."""
    state = _fresh_state()
    # Two quiet ticks
    for _ in range(2):
        outputs = {aid: _make_output() for aid in ("a", "b", "c")}
        result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
        state = result.updated_state
    assert state.consecutive_quiet == 2

    # Speech resumes
    outputs = {
        "a": _make_output(ActionType.SPEAK, urgency=5, action_content="其实我想说"),
        "b": _make_output(),
        "c": _make_output(),
    }
    result = resolve_tick(outputs, state, PROFILES, STATES, None, RNG)
    assert result.updated_state.consecutive_quiet == 0
