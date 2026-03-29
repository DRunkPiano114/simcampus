from pydantic import BaseModel, Field


class Relationship(BaseModel):
    target_name: str
    target_id: str
    favorability: int = Field(default=0, ge=-100, le=100)
    trust: int = Field(default=0, ge=-100, le=100)
    understanding: int = Field(default=0, ge=0, le=100)
    label: str = "同学"
    recent_interactions: list[str] = Field(default_factory=list)


class RelationshipFile(BaseModel):
    relationships: dict[str, Relationship] = Field(default_factory=dict)


class RelationshipChange(BaseModel):
    from_agent: str
    to_agent: str
    favorability: int = 0
    trust: int = 0
    understanding: int = 0
