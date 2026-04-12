import time

from loguru import logger
from pydantic import BaseModel, Field

from ..agent.storage import AgentStorage
from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..agent.qualitative import intensity_label
from ..models.agent import ActiveConcern, AgentProfile, ConcernTopic, Role
from ..models.memory import KeyMemory


class CompressionMemoryCandidate(BaseModel):
    text: str
    emotion: str = ""
    importance: int = Field(default=5, ge=1, le=10)
    people: list[str] = Field(default_factory=list)
    location: str = ""
    topics: list[str] = Field(default_factory=list)


class CompressionConcernCandidate(BaseModel):
    text: str
    source_event: str = ""
    emotion: str = ""
    intensity: int = Field(default=5, ge=1, le=10)
    related_people: list[str] = Field(default_factory=list)
    positive: bool = False
    topic: ConcernTopic = "其他"


class CompressionResult(BaseModel):
    daily_summary: str
    permanent_memories: list[CompressionMemoryCandidate] = Field(default_factory=list)
    new_concerns: list[CompressionConcernCandidate] = Field(default_factory=list)


def cap_today_memories(
    storage: AgentStorage,
    day: int,
    profile_name: str = "",
) -> int:
    """Drop the lowest-importance memories from `day` until at most
    `settings.per_day_memory_cap` remain. Returns the number dropped."""
    km_file = storage.load_key_memories()
    today_memories = [m for m in km_file.memories if m.day == day]
    other_memories = [m for m in km_file.memories if m.day != day]
    if len(today_memories) <= settings.per_day_memory_cap:
        return 0
    today_sorted = sorted(today_memories, key=lambda m: -m.importance)
    top_n = today_sorted[:settings.per_day_memory_cap]
    dropped = len(today_memories) - len(top_n)
    km_file.memories = other_memories + top_n
    storage.write_key_memories(km_file)
    if profile_name:
        logger.info(
            f"  {profile_name}: capped today's key_memories "
            f"({len(today_memories)} → {len(top_n)}, dropped {dropped})"
        )
    return dropped


async def nightly_compress(
    storage: AgentStorage,
    profile: AgentProfile,
    day: int,
) -> None:
    today_content = storage.read_today_md()
    if not today_content.strip():
        logger.debug(f"  {profile.name}: nothing to compress")
        return

    # Build profile summary
    role_desc = "学生" if profile.role == Role.STUDENT else "班主任兼语文老师"
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

    # Load active concerns for context
    state = storage.load_state()
    active_concerns = [
        {**c.model_dump(), "intensity_label": intensity_label(c.intensity)}
        for c in state.active_concerns
    ]

    unfulfilled_intentions = [
        f"{i.goal}（{i.reason}）"
        for i in state.daily_plan.intentions
        if not i.fulfilled
    ]

    prompt = render(
        "nightly_compress.j2",
        role_description=role_desc,
        profile_summary=profile_summary,
        today_md_content=today_content,
        active_concerns=active_concerns,
        unfulfilled_intentions=unfulfilled_intentions,
    )

    messages = [{"role": "user", "content": prompt}]

    start = time.time()
    llm_result = await structured_call(
        CompressionResult,
        messages,
        temperature=settings.compression_temperature,
        max_tokens=settings.max_tokens_compression,
    )
    latency = (time.time() - start) * 1000
    result = llm_result.data

    log_llm_call(
        day=day,
        scene_name="compression",
        group_id=storage.agent_id,
        call_type="nightly_compress",
        input_messages=messages,
        output=result,
        tokens_prompt=llm_result.tokens_prompt,
        tokens_completion=llm_result.tokens_completion,
        cost_usd=llm_result.cost_usd,
        latency_ms=latency,
        temperature=settings.compression_temperature,
    )

    # Append daily summary to recent.md
    recent = storage.read_recent_md()
    day_entry = f"\n# Day {day}\n{result.daily_summary}\n"
    storage.write_recent_md(recent + day_entry)

    # Save permanent memories above the configured importance threshold.
    for mem in result.permanent_memories:
        if mem.importance >= settings.key_memory_write_threshold:
            km = KeyMemory(
                date=f"Day {day}",
                day=day,
                people=mem.people,
                location=mem.location,
                emotion=mem.emotion,
                importance=mem.importance,
                topics=mem.topics,
                text=mem.text,
            )
            storage.append_key_memory(km)

    # Deferred import — apply_results lives in the interaction layer.
    from ..interaction.apply_results import add_concern
    for cc in result.new_concerns:
        new_concern = ActiveConcern(
            text=cc.text, source_event=cc.source_event,
            source_scene="", source_day=day, emotion=cc.emotion,
            intensity=cc.intensity, related_people=cc.related_people,
            positive=cc.positive, topic=cc.topic,
        )
        add_concern(state, new_concern, today=day)
    storage.save_state(state)

    # Per-day top-N cap on key_memories. Both apply_scene_end_results and
    # nightly_compress feed key_memories above the importance threshold,
    # so a single busy day could otherwise blow out an agent's memory list.
    cap_today_memories(storage, day, profile_name=profile.name)

    # Clear today.md
    storage.clear_today_md()

    logger.info(
        f"  {profile.name}: compressed → \"{result.daily_summary}\" "
        f"({len(result.permanent_memories)} permanent memories)"
    )
