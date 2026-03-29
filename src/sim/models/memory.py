from pydantic import BaseModel, Field


class KeyMemory(BaseModel):
    date: str
    day: int
    people: list[str] = Field(default_factory=list)
    location: str = ""
    emotion: str = ""
    importance: int = Field(default=5, ge=1, le=10)
    topics: list[str] = Field(default_factory=list)
    text: str


class KeyMemoryFile(BaseModel):
    memories: list[KeyMemory] = Field(default_factory=list)
