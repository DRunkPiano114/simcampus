import time

from loguru import logger

from ..agent.context import prepare_context
from ..agent.storage import AgentStorage
from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile, AgentState
from ..models.dialogue import TurnOutput
from ..models.event import Event
from ..models.scene import Scene
from .speaker_selection import pick_first_speaker, pick_next_speaker


def _format_turn(name: str, turn: TurnOutput) -> str:
    parts = [f"【{name}】"]
    if turn.directed_to:
        parts.append(f"（对{turn.directed_to}）")
    parts.append(f"：{turn.speech}")
    if turn.action:
        parts.append(f"  [{turn.action}]")
    return "".join(parts)


async def run_turn(
    agent_id: str,
    storage: AgentStorage,
    profile: AgentProfile,
    state: AgentState,
    scene: Scene,
    all_profiles: dict[str, AgentProfile],
    known_events: list[Event],
    next_exam_in_days: int,
    conversation_history: list[str],
    day: int,
    exam_context: str = "",
) -> TurnOutput:
    ctx = prepare_context(
        storage, profile, state, scene, all_profiles,
        known_events, next_exam_in_days, exam_context=exam_context,
    )
    ctx["conversation_history"] = conversation_history

    system_msg = render("dialogue_turn.j2", **ctx)
    messages = [{"role": "user", "content": system_msg}]

    start = time.time()
    result = await structured_call(
        TurnOutput,
        messages,
        temperature=settings.creative_temperature,
        max_tokens=settings.max_tokens_per_turn,
    )
    latency = (time.time() - start) * 1000

    log_llm_call(
        day=day,
        scene_name=scene.name,
        group_id=scene.scene_index,
        call_type="dialogue_turn",
        input_messages=messages,
        output=result,
        latency_ms=latency,
        temperature=settings.creative_temperature,
    )

    return result


async def run_group_dialogue(
    group_agent_ids: list[str],
    scene: Scene,
    storages: dict[str, AgentStorage],
    profiles: dict[str, AgentProfile],
    states: dict[str, AgentState],
    known_events_by_agent: dict[str, list[Event]],
    next_exam_in_days: int,
    day: int,
    rng,
    exam_context: str = "",
) -> list[dict]:
    """Run a full group dialogue, return list of turn records."""
    conversation_history: list[str] = []
    turn_records: list[dict] = []
    silent_counts: dict[str, int] = {aid: 0 for aid in group_agent_ids}
    active_agents = list(group_agent_ids)

    # Pick first speaker
    speaker = pick_first_speaker(active_agents, profiles, states, rng)
    last_directed_to: str | None = None

    for round_num in range(scene.max_rounds):
        if len(active_agents) < 2:
            break

        # Safety valve
        if round_num >= 50:
            logger.warning(f"Safety valve: 50 rounds reached for {scene.name}")
            break

        # Run turn
        result = await run_turn(
            speaker, storages[speaker], profiles[speaker], states[speaker],
            scene, profiles, known_events_by_agent.get(speaker, []),
            next_exam_in_days, conversation_history, day, exam_context,
        )

        # Format and append
        formatted = _format_turn(profiles[speaker].name, result)
        conversation_history.append(formatted)
        turn_records.append({
            "round": round_num,
            "speaker": speaker,
            "speaker_name": profiles[speaker].name,
            "output": result.model_dump(),
        })

        logger.info(f"  Round {round_num}: {formatted[:80]}")

        # Update silent counts
        for aid in active_agents:
            if aid == speaker:
                silent_counts[aid] = 0
            else:
                silent_counts[aid] = silent_counts.get(aid, 0) + 1

        # Check want_to_continue
        if not result.want_to_continue:
            active_agents.remove(speaker)
            if len(active_agents) < 2:
                break

        last_directed_to = result.directed_to

        # Pick next speaker
        speaker = pick_next_speaker(
            active_agents, profiles, states,
            speaker, last_directed_to,
            silent_counts, scene.teacher_present, rng,
        )

    return turn_records
