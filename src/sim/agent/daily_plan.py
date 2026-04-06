import time

from loguru import logger

from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile, AgentState, DailyPlan, Intention, Role
from .qualitative import (
    energy_label,
    intensity_label,
    next_exam_label,
    pressure_label,
    relationship_label,
)
from .storage import AgentStorage


def _concern_match(text_a: str, text_b: str | None) -> bool:
    """Bidirectional substring match for concern/intention alignment."""
    if not text_b:
        return False
    return text_b in text_a or text_a in text_b


def _match_old_intention(new_intent: Intention, old_intentions: list[Intention]) -> Intention | None:
    """Fuzzy match: same target + goal has substring overlap → continuation. Skip abandoned."""
    for old in old_intentions:
        if old.abandoned:
            continue
        if new_intent.target == old.target and _concern_match(new_intent.goal, old.goal):
            return old
    return None


async def generate_daily_plan(
    agent_id: str,
    storage: AgentStorage,
    profile: AgentProfile,
    state: AgentState,
    next_exam_in_days: int,
    day: int,
    all_profiles: dict[str, AgentProfile] | None = None,
) -> DailyPlan:
    rels = storage.load_relationships()
    recent_days = storage.read_recent_md_last_n_days(3)

    # Preserve yesterday's intentions for carry-forward (before state.daily_plan is replaced)
    yesterday_intentions = state.daily_plan.intentions

    relationships = [
        {**r.model_dump(), "label_text": relationship_label(r.favorability, r.trust)}
        for r in rels.relationships.values()
    ]

    role_desc = "学生" if profile.role == Role.STUDENT else "班主任兼语文老师"

    # Build profile summary
    parts = [
        f"姓名：{profile.name}",
        f"性格：{'、'.join(profile.personality)}",
    ]
    if profile.role == Role.STUDENT:
        parts.append(f"成绩：{profile.academics.overall_rank.value}")
        if profile.academics.strengths:
            parts.append(f"擅长科目：{'、'.join(profile.academics.strengths)}")
        if profile.academics.weaknesses:
            parts.append(f"弱势科目：{'、'.join(profile.academics.weaknesses)}")
        parts.append(f"学习态度：{profile.academics.study_attitude}")
        parts.append(f"目标：{profile.academics.target.value}")
    if profile.position:
        parts.append(f"职务：{profile.position}")
    if profile.family_background.expectation:
        parts.append(f"家庭期望：{profile.family_background.expectation}")
    parts.append(f"家庭情况：{profile.family_background.situation}")
    if profile.backstory:
        parts.append(f"背景：{profile.backstory}")
    if profile.long_term_goals:
        parts.append(f"长期目标：{'；'.join(profile.long_term_goals)}")
    if profile.inner_conflicts:
        parts.append(f"内心矛盾：{'；'.join(profile.inner_conflicts)}")
    profile_summary = "\n".join(parts)

    is_student = profile.role == Role.STUDENT

    # Load concerns and self-narrative for context
    active_concerns = [
        {**c.model_dump(), "intensity_label": intensity_label(c.intensity)}
        for c in state.active_concerns
    ]
    narr = storage.load_self_narrative_structured()

    prompt = render(
        "daily_plan.j2",
        role_description=role_desc,
        profile_summary=profile_summary,
        current_state=state,
        next_exam_in_days=next_exam_in_days,
        energy_label=energy_label(state.energy),
        pressure_label=pressure_label(state.academic_pressure),
        exam_label=next_exam_label(next_exam_in_days),
        relationships=relationships,
        recent_days=recent_days,
        yesterday_intentions=yesterday_intentions,
        active_concerns=active_concerns,
        self_narrative=narr.narrative,
        self_concept=narr.self_concept,
        current_tensions=narr.current_tensions,
        inner_conflicts=profile.inner_conflicts,
        is_student=is_student,
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

    # Carry-forward: match new intentions to yesterday's for lifecycle tracking
    for intent in result.intentions:
        matched = _match_old_intention(intent, yesterday_intentions)
        if matched:
            intent.origin_day = matched.origin_day or day
            intent.pursued_days = matched.pursued_days + 1
        else:
            intent.origin_day = day
            intent.pursued_days = 1

    # Audit: high-intensity addressable concerns without matching intention
    if all_profiles:
        known_names = {p.name for p in all_profiles.values()}
        addressable = [
            c for c in state.active_concerns
            if c.intensity >= 6 and any(rp in known_names for rp in c.related_people)
        ]
        for c in addressable:
            if not any(_concern_match(c.text, i.satisfies_concern) for i in result.intentions):
                logger.warning(f"  {profile.name}: 高强度牵挂 '{c.text[:20]}...' 没有被挂钩")

    logger.info(
        f"  {profile.name} plan: {len(result.intentions)} intentions, "
        f"mood={result.mood_forecast.value}"
    )

    return result
