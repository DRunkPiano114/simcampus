import pytest
from pydantic import ValidationError

from sim.models.agent import Emotion
from sim.models.dialogue import ActionType, PerceptionOutput


def test_perception_output_required_fields():
    out = PerceptionOutput(
        observation="看到有人在说话",
        inner_thought="没什么意思",
        emotion=Emotion.NEUTRAL,
        action_type=ActionType.OBSERVE,
        urgency=3,
    )
    assert out.action_content is None
    assert out.action_target is None
    assert out.is_disruptive is False


def test_urgency_range_lower_bound():
    with pytest.raises(ValidationError):
        PerceptionOutput(
            observation="x",
            inner_thought="x",
            emotion=Emotion.NEUTRAL,
            action_type=ActionType.OBSERVE,
            urgency=0,
        )


def test_urgency_range_upper_bound():
    with pytest.raises(ValidationError):
        PerceptionOutput(
            observation="x",
            inner_thought="x",
            emotion=Emotion.NEUTRAL,
            action_type=ActionType.OBSERVE,
            urgency=11,
        )


def test_urgency_valid_boundaries():
    out1 = PerceptionOutput(
        observation="x", inner_thought="x", emotion=Emotion.NEUTRAL,
        action_type=ActionType.OBSERVE, urgency=1,
    )
    out10 = PerceptionOutput(
        observation="x", inner_thought="x", emotion=Emotion.NEUTRAL,
        action_type=ActionType.OBSERVE, urgency=10,
    )
    assert out1.urgency == 1
    assert out10.urgency == 10


def test_is_disruptive_default():
    out = PerceptionOutput(
        observation="x", inner_thought="x", emotion=Emotion.NEUTRAL,
        action_type=ActionType.NON_VERBAL, urgency=5,
        action_content="低头写字",
    )
    assert out.is_disruptive is False


def test_action_types():
    assert ActionType.SPEAK == "speak"
    assert ActionType.WHISPER == "whisper"
    assert ActionType.NON_VERBAL == "non_verbal"
    assert ActionType.OBSERVE == "observe"
    assert ActionType.EXIT == "exit"
