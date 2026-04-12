from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# Discrete concern topic enum. Using a Literal forces Pydantic / Instructor
# to enforce the closed set, preventing LLM-driven drift like "学业焦虑" /
# "学习压力" / "学习焦虑" leaking in as separate buckets.
ConcernTopic = Literal[
    "学业焦虑",
    "家庭压力",
    "人际矛盾",
    "恋爱",
    "自我认同",
    "未来规划",
    "健康",
    "兴趣爱好",    # positive bucket — keeps "looking forward to X" out of "其他"
    "期待的事",    # positive bucket
    "其他",
]


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"


class Role(str, Enum):
    STUDENT = "student"
    HOMEROOM_TEACHER = "homeroom_teacher"


class OverallRank(str, Enum):
    TOP = "top"
    UPPER = "上游"
    UPPER_MIDDLE = "中上"
    MIDDLE = "中游"
    LOWER_MIDDLE = "中下"
    LOWER = "下游"


class AcademicTarget(str, Enum):
    C9 = "985"
    P211 = "211"
    TIER1 = "一本"
    TIER2 = "二本"
    NONE = "没想过"


class PressureLevel(str, Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class Emotion(str, Enum):
    HAPPY = "happy"
    SAD = "sad"
    ANXIOUS = "anxious"
    ANGRY = "angry"
    EXCITED = "excited"
    CALM = "calm"
    EMBARRASSED = "embarrassed"
    BORED = "bored"
    NEUTRAL = "neutral"
    JEALOUS = "jealous"
    PROUD = "proud"
    GUILTY = "guilty"
    FRUSTRATED = "frustrated"
    TOUCHED = "touched"
    CURIOUS = "curious"


class Academics(BaseModel):
    overall_rank: OverallRank
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    study_attitude: str = ""
    target: AcademicTarget = AcademicTarget.NONE
    homework_habit: str = ""


class FamilyBackground(BaseModel):
    pressure_level: PressureLevel
    expectation: str = ""
    situation: str = ""


class BehavioralAnchors(BaseModel):
    must_do: list[str] = Field(default_factory=list, max_length=5)
    never_do: list[str] = Field(default_factory=list, max_length=5)
    speech_patterns: list[str] = Field(default_factory=list, max_length=6)


class AgentProfile(BaseModel):
    agent_id: str
    name: str
    gender: Gender
    role: Role
    seat_number: int | None = None
    dorm_id: str | None = None
    position: str | None = None
    personality: list[str] = Field(default_factory=list)
    speaking_style: str = ""
    academics: Academics
    family_background: FamilyBackground
    long_term_goals: list[str] = Field(default_factory=list)
    backstory: str = ""
    inner_conflicts: list[str] = Field(default_factory=list)
    behavioral_anchors: BehavioralAnchors = Field(default_factory=BehavioralAnchors)
    joy_sources: list[str] = Field(default_factory=list)


class Intention(BaseModel):
    target: str | None = None
    goal: str
    reason: str
    fulfilled: bool = False
    abandoned: bool = False
    satisfies_concern: str | None = None
    origin_day: int = 0
    pursued_days: int = 1


class ActiveConcern(BaseModel):
    text: str                    # "被江浩天当众嘲笑数学成绩"
    source_event: str = ""       # Brief trigger description
    source_scene: str = ""       # e.g. "课间" — used for structural dedup
    source_day: int = 0
    emotion: str = ""            # "羞耻"
    intensity: int = Field(default=5, ge=1, le=10)
    related_people: list[str] = Field(default_factory=list)
    positive: bool = False
    topic: ConcernTopic = "其他"            # bucket key for topic-based dedup
    last_reinforced_day: int = 0             # day this concern was last touched
    text_history: list[str] = Field(default_factory=list, max_length=3)


class LocationPreference(BaseModel):
    morning_break: str = "教室"      # 课间 08:45
    lunch: str = "食堂"              # 午饭 12:00
    afternoon_break: str = "教室"    # 课间 15:30


class DailyPlan(BaseModel):
    intentions: list[Intention] = Field(default_factory=list, max_length=3)
    mood_forecast: Emotion = Emotion.NEUTRAL
    location_preferences: LocationPreference = Field(default_factory=LocationPreference)


class AgentState(BaseModel):
    emotion: Emotion = Emotion.NEUTRAL
    energy: int = Field(default=85, ge=0, le=100)
    academic_pressure: int = Field(default=30, ge=0, le=100)
    location: str = "教室"
    daily_plan: DailyPlan = Field(default_factory=DailyPlan)
    day: int = 1
    active_concerns: list[ActiveConcern] = Field(default_factory=list)  # max 4
