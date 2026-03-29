import time

from loguru import logger
from pydantic import BaseModel, Field

from ..agent.storage import AgentStorage
from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile, Role
from ..models.memory import KeyMemory


class CompressionMemoryCandidate(BaseModel):
    text: str
    emotion: str = ""
    importance: int = Field(default=5, ge=1, le=10)
    people: list[str] = Field(default_factory=list)
    location: str = ""
    topics: list[str] = Field(default_factory=list)


class CompressionResult(BaseModel):
    daily_summary: str
    permanent_memories: list[CompressionMemoryCandidate] = Field(default_factory=list)


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
    profile_summary = "\n".join(parts)

    prompt = render(
        "nightly_compress.j2",
        role_description=role_desc,
        profile_summary=profile_summary,
        today_md_content=today_content,
    )

    messages = [{"role": "user", "content": prompt}]

    start = time.time()
    result = await structured_call(
        CompressionResult,
        messages,
        temperature=settings.compression_temperature,
        max_tokens=settings.max_tokens_compression,
    )
    latency = (time.time() - start) * 1000

    log_llm_call(
        day=day,
        scene_name="compression",
        group_id=storage.agent_id,
        call_type="nightly_compress",
        input_messages=messages,
        output=result,
        latency_ms=latency,
        temperature=settings.compression_temperature,
    )

    # Append daily summary to recent.md
    recent = storage.read_recent_md()
    day_entry = f"\n# Day {day}\n{result.daily_summary}\n"
    storage.write_recent_md(recent + day_entry)

    # Save permanent memories
    for mem in result.permanent_memories:
        if mem.importance >= 7:
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

    # Clear today.md
    storage.clear_today_md()

    logger.info(
        f"  {profile.name}: compressed → \"{result.daily_summary}\" "
        f"({len(result.permanent_memories)} permanent memories)"
    )
