from pydantic import BaseModel, Field

from .agent import Emotion
from .relationship import RelationshipChange


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


class SceneEndAnalysis(BaseModel):
    key_moments: list[str] = Field(default_factory=list)
    relationship_changes: list[RelationshipChange] = Field(default_factory=list)
    fulfilled_intentions: list[str] = Field(default_factory=list)
    events_discussed: list[str] = Field(default_factory=list)
    memories: list[MemoryCandidate] = Field(default_factory=list)
    new_events: list[NewEventCandidate] = Field(default_factory=list)
    final_emotions: dict[str, str] = Field(default_factory=dict)


class SoloReflection(BaseModel):
    inner_thought: str = ""
    emotion: Emotion = Emotion.NEUTRAL
    activity: str = ""
