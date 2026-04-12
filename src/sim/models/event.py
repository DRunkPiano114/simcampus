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
    # 1-indexed tick numbers the source LLM call grounded this event in.
    # Empty for system-generated events with no LLM source.
    cite_ticks: list[int] = Field(default_factory=list)
    # Group inside the source scene the event came out of. cite_ticks are
    # group-local, so any per-group cite validation must scope by this.
    # None for system-generated events.
    group_index: int | None = None


class EventQueue(BaseModel):
    events: list[Event] = Field(default_factory=list)
    next_id: int = 1
