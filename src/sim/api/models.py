from typing import Literal

from pydantic import BaseModel, Field

ActionType = Literal["speak", "action", "silence"]


class ChatMessage(BaseModel):
    role: str  # "user" or agent_id
    content: str
    agent_name: str | None = None


class ChatRequest(BaseModel):
    agent_id: str
    day: int
    time_period: str  # "08:45", "12:00", "15:30", "22:00"
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class RolePlayRequest(BaseModel):
    user_agent_id: str  # who the user is playing as
    target_agent_ids: list[str] = Field(min_length=1, max_length=4)
    day: int
    time_period: str
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class AgentReactionLLM(BaseModel):
    """LLM response model — excludes agent_id/agent_name to avoid wasting tokens."""
    action: ActionType
    target: str | None = None
    content: str
    inner_thought: str
    emotion: str


class AgentReaction(BaseModel):
    agent_id: str
    agent_name: str
    action: ActionType
    target: str | None = None
    content: str
    inner_thought: str
    emotion: str
