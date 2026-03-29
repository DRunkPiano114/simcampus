from enum import Enum

from pydantic import BaseModel, Field


class SceneDensity(str, Enum):
    HIGH = "high"
    HIGH_LIGHT = "high_light"
    LOW = "low"


class SceneConfig(BaseModel):
    time: str
    name: str
    location: str
    density: SceneDensity
    max_rounds: int = 12
    trigger_probability: float = 1.0
    description: str = ""


class GroupAssignment(BaseModel):
    group_id: int
    agent_ids: list[str]
    is_solo: bool = False


class Scene(BaseModel):
    scene_index: int
    day: int
    time: str
    name: str
    location: str
    density: SceneDensity
    max_rounds: int = 12
    description: str = ""
    agent_ids: list[str] = Field(default_factory=list)
    groups: list[GroupAssignment] = Field(default_factory=list)
    injected_events: list[str] = Field(default_factory=list)
    teacher_present: bool = False
    teacher_action: str | None = None
