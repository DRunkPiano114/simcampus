import time

from loguru import logger
from pydantic import BaseModel

from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile, AgentState, Role
from .storage import AgentStorage


class SelfNarrativeResult(BaseModel):
    narrative: str


async def generate_self_narrative(
    storage: AgentStorage,
    profile: AgentProfile,
    state: AgentState,
    day: int,
) -> str:
    rels = storage.load_relationships()
    recent_summary = storage.read_recent_md_last_n_days(3)

    # Build profile summary
    parts = [
        f"姓名：{profile.name}",
        f"性格：{'、'.join(profile.personality)}",
    ]
    if profile.role == Role.STUDENT:
        parts.append(f"成绩：{profile.academics.overall_rank.value}")
        parts.append(f"目标：{profile.academics.target.value}")
    parts.append(f"家庭情况：{profile.family_background.situation}")
    if profile.long_term_goals:
        parts.append(f"长期目标：{'；'.join(profile.long_term_goals)}")
    profile_summary = "\n".join(parts)

    relationships = list(rels.relationships.values())

    prompt = render(
        "self_narrative.j2",
        name=profile.name,
        profile_summary=profile_summary,
        recent_summary=recent_summary or "（刚开学，还没什么特别的经历）",
        concerns=state.active_concerns,
        relationships=relationships,
    )

    messages = [{"role": "user", "content": prompt}]

    start = time.time()
    result = await structured_call(
        SelfNarrativeResult,
        messages,
        temperature=settings.self_narrative_temperature,
        max_tokens=settings.max_tokens_self_narrative,
    )
    latency = (time.time() - start) * 1000

    log_llm_call(
        day=day,
        scene_name="self_narrative",
        group_id=storage.agent_id,
        call_type="self_narrative",
        input_messages=messages,
        output=result,
        latency_ms=latency,
        temperature=settings.self_narrative_temperature,
    )

    storage.write_self_narrative(result.narrative)

    logger.info(f"  {profile.name}: self-narrative updated")

    return result.narrative
