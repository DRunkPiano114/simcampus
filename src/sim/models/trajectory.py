from pydantic import BaseModel, Field


class AgentSlot(BaseModel):
    time: str
    scene_name: str
    location: str
    activity: str = ""
    emotion: str = ""


class DayTrajectory(BaseModel):
    day: int
    agents: dict[str, list[AgentSlot]] = Field(default_factory=dict)
