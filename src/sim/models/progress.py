from typing import Literal

from pydantic import BaseModel, Field


class GroupCompletion(BaseModel):
    group_index: int
    status: Literal["pending", "llm_done", "applied"] = "pending"
    result_file: str | None = None


class SceneProgress(BaseModel):
    scene_index: int
    scene_id: str = ""
    phase: Literal["grouping", "interaction", "scene_end", "applying", "complete"] = "grouping"
    groups: list[GroupCompletion] = Field(default_factory=list)


class Progress(BaseModel):
    current_day: int = 1
    current_date: str = ""
    day_phase: Literal["daily_plan", "scenes", "compression", "complete"] = "daily_plan"
    current_scene_index: int = 0
    scenes: list[SceneProgress] = Field(default_factory=list)
    next_exam_in_days: int = 30
    total_days_simulated: int = 0
    last_updated: str = ""
