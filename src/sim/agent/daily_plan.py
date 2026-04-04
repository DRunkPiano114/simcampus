import time

from loguru import logger

from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile, AgentState, DailyPlan, Role
from .storage import AgentStorage


async def generate_daily_plan(
    agent_id: str,
    storage: AgentStorage,
    profile: AgentProfile,
    state: AgentState,
    next_exam_in_days: int,
    day: int,
) -> DailyPlan:
    rels = storage.load_relationships()
    recent_days = storage.read_recent_md_last_n_days(3)

    # Collect unfulfilled intentions from yesterday
    yesterday_unfulfilled = [
        f"{i.goal}（{i.reason}）"
        for i in state.daily_plan.intentions
        if not i.fulfilled
    ]

    relationships = list(rels.relationships.values())

    role_desc = "学生" if profile.role == Role.STUDENT else "班主任兼语文老师"

    # Build profile summary
    parts = [
        f"姓名：{profile.name}",
        f"性格：{'、'.join(profile.personality)}",
        f"成绩：{profile.academics.overall_rank.value}",
    ]
    if profile.academics.strengths:
        parts.append(f"擅长科目：{'、'.join(profile.academics.strengths)}")
    if profile.academics.weaknesses:
        parts.append(f"弱势科目：{'、'.join(profile.academics.weaknesses)}")
    parts.append(f"学习态度：{profile.academics.study_attitude}")
    parts.append(f"目标：{profile.academics.target.value}")
    if profile.position:
        parts.append(f"职务：{profile.position}")
    parts.append(f"家庭期望：{profile.family_background.expectation}")
    parts.append(f"家庭情况：{profile.family_background.situation}")
    if profile.long_term_goals:
        parts.append(f"长期目标：{'；'.join(profile.long_term_goals)}")
    profile_summary = "\n".join(parts)

    # Load concerns and self-narrative for context
    active_concerns = [c for c in state.active_concerns]
    self_narrative = storage.read_self_narrative()

    prompt = render(
        "daily_plan.j2",
        role_description=role_desc,
        profile_summary=profile_summary,
        current_state=state,
        next_exam_in_days=next_exam_in_days,
        relationships=relationships,
        recent_days=recent_days,
        yesterday_unfulfilled=yesterday_unfulfilled,
        active_concerns=active_concerns,
        self_narrative=self_narrative,
    )

    messages = [{"role": "user", "content": prompt}]

    start = time.time()
    result = await structured_call(
        DailyPlan,
        messages,
        temperature=settings.plan_temperature,
        max_tokens=settings.max_tokens_daily_plan,
    )
    latency = (time.time() - start) * 1000

    log_llm_call(
        day=day,
        scene_name="daily_plan",
        group_id=agent_id,
        call_type="daily_plan",
        input_messages=messages,
        output=result,
        latency_ms=latency,
        temperature=settings.plan_temperature,
    )

    # Validate location preferences
    valid_break = set(settings.free_period_locations)
    valid_lunch = set(settings.lunch_locations)
    prefs = result.location_preferences
    if prefs.morning_break not in valid_break:
        prefs.morning_break = "教室"
    if prefs.lunch not in valid_lunch:
        prefs.lunch = "食堂"
    if prefs.afternoon_break not in valid_break:
        prefs.afternoon_break = "教室"

    logger.info(
        f"  {profile.name} plan: {len(result.intentions)} intentions, "
        f"mood={result.mood_forecast.value}"
    )

    return result
