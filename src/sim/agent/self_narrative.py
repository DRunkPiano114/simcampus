import time

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile, AgentState, Role
from .qualitative import relationship_label
from .storage import AgentStorage


class SelfNarrativeResult(BaseModel):
    narrative: str = ""
    self_concept: list[str] = Field(default_factory=list, max_length=4)
    current_tensions: list[str] = Field(default_factory=list, max_length=3)


async def generate_self_narrative(
    storage: AgentStorage,
    profile: AgentProfile,
    state: AgentState,
    day: int,
) -> SelfNarrativeResult:
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
    if profile.backstory:
        parts.append(f"背景：{profile.backstory}")
    if profile.long_term_goals:
        parts.append(f"长期目标：{'；'.join(profile.long_term_goals)}")
    if profile.inner_conflicts:
        parts.append(f"内心矛盾：{'；'.join(profile.inner_conflicts)}")
    profile_summary = "\n".join(parts)

    relationships = [
        {**r.model_dump(), "label_text": relationship_label(r.favorability, r.trust)}
        for r in rels.relationships.values()
    ]

    # Load previous structured result for continuity
    prev = storage.load_self_narrative_structured()

    prompt = render(
        "self_narrative.j2",
        name=profile.name,
        is_teacher=(profile.role != Role.STUDENT),
        profile_summary=profile_summary,
        recent_summary=recent_summary or "（刚开学，还没什么特别的经历）",
        concerns=state.active_concerns,
        relationships=relationships,
        prev_self_concept=prev.self_concept,
        prev_current_tensions=prev.current_tensions,
    )

    messages = [{"role": "user", "content": prompt}]

    start = time.time()
    llm_result = await structured_call(
        SelfNarrativeResult,
        messages,
        temperature=settings.self_narrative_temperature,
        max_tokens=settings.max_tokens_self_narrative,
    )
    latency = (time.time() - start) * 1000
    result = llm_result.data

    log_llm_call(
        day=day,
        scene_name="self_narrative",
        group_id=storage.agent_id,
        call_type="self_narrative",
        input_messages=messages,
        output=result,
        tokens_prompt=llm_result.tokens_prompt,
        tokens_completion=llm_result.tokens_completion,
        cost_usd=llm_result.cost_usd,
        latency_ms=latency,
        temperature=settings.self_narrative_temperature,
    )

    storage.save_self_narrative_structured(result)

    logger.info(f"  {profile.name}: self-narrative updated")

    return result
