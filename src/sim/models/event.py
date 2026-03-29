from pydantic import BaseModel, Field


class Event(BaseModel):
    id: str
    source_scene: str = ""
    source_day: int = 1
    text: str
    category: str = ""
    witnesses: list[str] = Field(default_factory=list)
    known_by: list[str] = Field(default_factory=list)
    spread_probability: float = Field(default=0.5, ge=0.0, le=1.0)
    active: bool = True


class EventQueue(BaseModel):
    events: list[Event] = Field(default_factory=list)
    next_id: int = 1
