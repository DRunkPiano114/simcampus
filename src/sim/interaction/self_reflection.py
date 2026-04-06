import asyncio
import time

from loguru import logger

from ..agent.context import prepare_context
from ..agent.storage import AgentStorage
from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile, AgentState
from ..models.dialogue import AgentReflection
from ..models.scene import Scene
from .narrative import format_agent_transcript


async def run_agent_reflection(
    agent_id: str,
    tick_records: list[dict],
    storage: AgentStorage,
    profile: AgentProfile,
    state: AgentState,
    scene: Scene,
    all_profiles: dict[str, AgentProfile],
    day: int,
    group_index: int,
) -> AgentReflection:
    # Get agent-specific transcript (includes whispers they heard)
    conversation_log, _private_history = format_agent_transcript(
        tick_records, agent_id, all_profiles,
    )

    # Build agent context (reuse existing context assembly)
    ctx = prepare_context(
        storage, profile, state, scene, all_profiles,
        known_events=[], next_exam_in_days=0,
    )

    prompt = render(
        "self_reflection.j2",
        profile_summary=ctx["profile_summary"],
        relationships=ctx["relationships"],
        today_events=ctx["today_events"],
        recent_summary=ctx["recent_summary"],
        key_memories=ctx["key_memories"],
        active_concerns=ctx["active_concerns"],
        self_narrative=ctx["self_narrative"],
        self_concept=ctx["self_concept"],
        current_tensions=ctx["current_tensions"],
        scene_info=ctx["scene_info"],
        conversation_log=conversation_log,
        role_description=ctx["role_description"],
        pending_intentions=ctx["pending_intentions"],
    )

    messages = [{"role": "user", "content": prompt}]

    start = time.time()
    result = await structured_call(
        AgentReflection,
        messages,
        temperature=settings.reflection_temperature,
        max_tokens=settings.max_tokens_reflection,
    )
    latency = (time.time() - start) * 1000

    log_llm_call(
        day=day,
        scene_name=scene.name,
        group_id=f"{group_index}_{agent_id}",
        call_type="self_reflection",
        input_messages=messages,
        output=result,
        latency_ms=latency,
        temperature=settings.reflection_temperature,
    )

    logger.debug(
        f"  Reflection for {profile.name}: emotion={result.emotion.value}, "
        f"{len(result.relationship_changes)} rel changes, "
        f"{len(result.memories)} memories, "
        f"{len(result.new_concerns)} new concerns"
    )

    return result


async def run_all_reflections(
    group_agent_ids: list[str],
    tick_records: list[dict],
    storages: dict[str, AgentStorage],
    profiles: dict[str, AgentProfile],
    states: dict[str, AgentState],
    scene: Scene,
    day: int,
    group_index: int,
    semaphore: asyncio.Semaphore,
) -> dict[str, AgentReflection]:

    async def _reflect(aid: str) -> tuple[str, AgentReflection]:
        async with semaphore:
            return aid, await run_agent_reflection(
                aid, tick_records, storages[aid],
                profiles[aid], states[aid], scene,
                profiles, day, group_index,
            )

    tasks = [_reflect(aid) for aid in group_agent_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    reflections: dict[str, AgentReflection] = {}
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"  Reflection failed for an agent: {r}")
            continue
        aid, reflection = r
        reflections[aid] = reflection

    # Fill in defaults for any agents that failed
    for aid in group_agent_ids:
        if aid not in reflections:
            logger.warning(f"  Using default reflection for {profiles[aid].name}")
            reflections[aid] = AgentReflection()

    return reflections
