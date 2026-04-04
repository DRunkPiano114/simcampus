from enum import Enum

from pydantic import BaseModel, Field

from .agent import Emotion
from .relationship import RelationshipChange


class ActionType(str, Enum):
    SPEAK = "speak"
    WHISPER = "whisper"
    NON_VERBAL = "non_verbal"
    OBSERVE = "observe"
    EXIT = "exit"


class PerceptionOutput(BaseModel):
    observation: str
    inner_thought: str
    emotion: Emotion
    action_type: ActionType
    action_content: str | None = None
    action_target: str | None = None
    urgency: int = Field(ge=1, le=10)
    is_disruptive: bool = False


class TurnOutput(BaseModel):
    speech: str
    directed_to: str | None = None
    inner_thought: str = ""
    action: str | None = None
    emotion: Emotion = Emotion.NEUTRAL
    want_to_continue: bool = True


class MemoryCandidate(BaseModel):
    agent: str
    text: str
    emotion: str = ""
    importance: int = Field(default=5, ge=1, le=10)
    people: list[str] = Field(default_factory=list)
    location: str = ""
    topics: list[str] = Field(default_factory=list)


class NewEventCandidate(BaseModel):
    text: str
    category: str = ""
    witnesses: list[str] = Field(default_factory=list)
    spread_probability: float = Field(default=0.5, ge=0.0, le=1.0)


class ConcernCandidate(BaseModel):
    agent: str                  # Agent name
    text: str
    source_event: str = ""
    emotion: str = ""
    intensity: int = Field(default=5, ge=1, le=10)
    related_people: list[str] = Field(default_factory=list)


class ConcernUpdate(BaseModel):
    """Adjustment to an existing concern's intensity from scene events."""
    agent: str                  # Agent name
    concern_text: str           # Text of existing concern being adjusted
    adjustment: int             # -3=greatly soothed, -1=slightly eased, +2=worsened, +5=much worse


class SceneEndAnalysis(BaseModel):
    key_moments: list[str] = Field(default_factory=list)
    relationship_changes: list[RelationshipChange] = Field(default_factory=list)
    fulfilled_intentions: list[str] = Field(default_factory=list)
    events_discussed: list[str] = Field(default_factory=list)
    memories: list[MemoryCandidate] = Field(default_factory=list)
    new_events: list[NewEventCandidate] = Field(default_factory=list)
    final_emotions: dict[str, str] = Field(default_factory=dict)
    new_concerns: list[ConcernCandidate] = Field(default_factory=list)
    concern_updates: list[ConcernUpdate] = Field(default_factory=list)


class SoloReflection(BaseModel):
    inner_thought: str = ""
    emotion: Emotion = Emotion.NEUTRAL
    activity: str = ""
