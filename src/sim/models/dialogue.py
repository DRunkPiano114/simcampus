from enum import Enum
from typing import Literal

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


# --- Per-agent self-reflection models (replaces god's-eye SceneEndAnalysis) ---


class NarrativeExtraction(BaseModel):
    """客观叙事提取（不涉及任何 agent 的主观感受）"""
    key_moments: list[str] = Field(default_factory=list)
    fulfilled_intentions: list[str] = Field(default_factory=list)
    events_discussed: list[str] = Field(default_factory=list)
    new_events: list[NewEventCandidate] = Field(default_factory=list)


class AgentRelChange(BaseModel):
    """从 focal agent 视角出发的单向关系变化"""
    to_agent: str
    favorability: int = 0
    trust: int = 0
    understanding: int = 0


class AgentMemoryCandidate(BaseModel):
    """focal agent 认为值得记住的事"""
    text: str
    emotion: str = ""
    importance: int = Field(default=5, ge=1, le=10)
    people: list[str] = Field(default_factory=list)
    location: str = ""
    topics: list[str] = Field(default_factory=list)


class AgentConcernCandidate(BaseModel):
    """focal agent 产生的新牵挂"""
    text: str
    source_event: str = ""
    emotion: str = ""
    intensity: int = Field(default=5, ge=1, le=10)
    related_people: list[str] = Field(default_factory=list)
    positive: bool = False


class AgentConcernUpdate(BaseModel):
    """focal agent 已有牵挂的强度变化"""
    concern_text: str
    adjustment: int


class IntentionOutcome(BaseModel):
    """Agent 对自己一条 intention 的自评"""
    goal: str
    status: Literal["fulfilled", "attempted", "frustrated", "abandoned", "pending"] = "pending"
    brief_reason: str = ""


class AgentReflection(BaseModel):
    """单个 agent 对一段对话的自我反思"""
    emotion: Emotion = Emotion.NEUTRAL
    relationship_changes: list[AgentRelChange] = Field(default_factory=list)
    memories: list[AgentMemoryCandidate] = Field(default_factory=list)
    new_concerns: list[AgentConcernCandidate] = Field(default_factory=list)
    concern_updates: list[AgentConcernUpdate] = Field(default_factory=list)
    intention_outcomes: list[IntentionOutcome] = Field(default_factory=list)


class SoloReflection(BaseModel):
    inner_thought: str = ""
    emotion: Emotion = Emotion.NEUTRAL
    activity: str = ""
