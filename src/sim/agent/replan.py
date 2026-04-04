import time

from loguru import logger
from pydantic import BaseModel

from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile, AgentState, Role
from .storage import AgentStorage


class ReplanResult(BaseModel):
    changed: bool = False
    new_location: str | None = None
    reason: str = ""


async def maybe_replan(
    agent_id: str,
    storage: AgentStorage,
    profile: AgentProfile,
    state: AgentState,
    scene_summary: str,
    next_slot_field: str,
    available_locations: list[str],
    day: int,
) -> bool:
    """Returns True if location was changed."""
    prefs = state.daily_plan.location_preferences
    planned_location = getattr(prefs, next_slot_field, "教室")

    # Build profile summary
    parts = [
        f"姓名：{profile.name}",
        f"性格���{'、'.join(profile.personality)}",
    ]
    if profile.role == Role.STUDENT:
        parts.append(f"成绩：{profile.academics.overall_rank.value}")
    profile_summary = "\n".join(parts)

    prompt = render(
        "replan.j2",
        profile_summary=profile_summary,
        scene_summary=scene_summary,
        active_concerns=state.active_concerns,
        planned_location=planned_location,
        available_locations=available_locations,
    )

    messages = [{"role": "user", "content": prompt}]

    start = time.time()
    result = await structured_call(
        ReplanResult,
        messages,
        temperature=settings.replan_temperature,
        max_tokens=settings.max_tokens_replan,
    )
    latency = (time.time() - start) * 1000

    log_llm_call(
        day=day,
        scene_name="replan",
        group_id=agent_id,
        call_type="replan",
        input_messages=messages,
        output=result,
        latency_ms=latency,
        temperature=settings.replan_temperature,
    )

    if result.changed and result.new_location and result.new_location in available_locations:
        setattr(prefs, next_slot_field, result.new_location)
        storage.save_state(state)
        logger.info(
            f"  {profile.name} replanned: {planned_location} → {result.new_location} ({result.reason})"
        )
        return True

    return False
