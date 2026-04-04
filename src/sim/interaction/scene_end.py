import time

from loguru import logger

from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile
from ..models.dialogue import SceneEndAnalysis
from ..models.scene import Scene
from .narrative import format_public_transcript


async def run_scene_end_analysis(
    tick_records: list[dict],
    group_agent_ids: list[str],
    profiles: dict[str, AgentProfile],
    scene: Scene,
    day: int,
    group_id: int,
    agent_concerns: dict[str, list] | None = None,
) -> SceneEndAnalysis:
    full_log = format_public_transcript(tick_records, profiles)
    long_conversation = len(tick_records) > 12

    group_members = [
        {"name": profiles[aid].name, "personality": profiles[aid].personality}
        for aid in group_agent_ids
        if aid in profiles
    ]

    scene_info = {
        "time": scene.time,
        "location": scene.location,
        "name": scene.name,
    }

    prompt = render(
        "scene_end_analysis.j2",
        full_conversation_log=full_log,
        group_members=group_members,
        scene_info=scene_info,
        long_conversation=long_conversation,
        agent_concerns=agent_concerns,
    )

    messages = [{"role": "user", "content": prompt}]

    start = time.time()
    result = await structured_call(
        SceneEndAnalysis,
        messages,
        temperature=settings.analytical_temperature,
        max_tokens=settings.max_tokens_scene_end,
    )
    latency = (time.time() - start) * 1000

    log_llm_call(
        day=day,
        scene_name=scene.name,
        group_id=group_id,
        call_type="scene_end",
        input_messages=messages,
        output=result,
        latency_ms=latency,
        temperature=settings.analytical_temperature,
    )

    logger.info(
        f"  Scene-end analysis: {len(result.key_moments)} moments, "
        f"{len(result.relationship_changes)} rel changes, "
        f"{len(result.memories)} memories"
    )

    return result
