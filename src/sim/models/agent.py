from enum import Enum

from pydantic import BaseModel, Field


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
