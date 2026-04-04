from __future__ import annotations

import asyncio
import time

from loguru import logger

from ..agent.context import prepare_context
from ..agent.storage import AgentStorage
from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..models.agent import AgentProfile, AgentState, Emotion
from ..models.dialogue import ActionType, PerceptionOutput
from ..models.event import Event
from ..models.scene import Scene
from .narrative import format_agent_transcript, format_latest_event
from .resolution import ResolutionState, resolve_tick


async def run_perception(
    storage: AgentStorage,
    profile: AgentProfile,
    state: AgentState,
    scene: Scene,
    all_profiles: dict[str, AgentProfile],
    known_events: list[Event],
    next_exam_in_days: int,
    latest_event: str,
    scene_transcript: str,
    private_history: list[str],
    tick_emotion: Emotion,
    day: int,
    exam_context: str = "",
    emotion_trace: list[str] | None = None,
) -> PerceptionOutput:
    ctx = prepare_context(
        storage, profile, state, scene, all_profiles,
        known_events, next_exam_in_days, exam_context=exam_context,
        latest_event=latest_event,
        scene_transcript=scene_transcript,
        private_history=private_history,
        emotion_override=tick_emotion,
        emotion_trace=emotion_trace,
    )

    system_msg = render("perception_decision.j2", **ctx)
    messages = [{"role": "user", "content": system_msg}]

    start = time.time()
    result = await structured_call(
        PerceptionOutput,
        messages,
        temperature=settings.perception_temperature,
        max_tokens=settings.max_tokens_perception,
    )
    latency = (time.time() - start) * 1000

    log_llm_call(
        day=day,
        scene_name=scene.name,
        group_id=scene.scene_index,
        call_type="perception",
        input_messages=messages,
        output=result,
        latency_ms=latency,
        temperature=settings.perception_temperature,
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
    semaphore: asyncio.Semaphore,
    exam_context: str = "",
) -> list[dict]:
    """Run a full group dialogue using the PDA tick loop."""
    tick_records: list[dict] = []
    resolution_state = ResolutionState(
        active_agents=set(group_agent_ids),
    )
    tick_emotions: dict[str, Emotion] = {
        aid: states[aid].emotion for aid in group_agent_ids
    }
    emotion_history: dict[str, list[str]] = {
        aid: [states[aid].emotion.value] for aid in group_agent_ids
    }
    # Tick 0: opening event from scene
    latest_event = scene.opening_event or scene.description
    last_resolved_speech = None

    for tick in range(settings.max_ticks_per_scene):
        active_agents = list(resolution_state.active_agents)
        if len(active_agents) < 2:
            break

        # Determine which agents need to perceive (skip queued agents)
        perceiving = [
            aid for aid in active_agents
            if aid not in resolution_state.queued_agents
        ]

        # PERCEIVE: all non-queued agents concurrently
        async def _perceive(aid: str) -> tuple[str, PerceptionOutput]:
            transcript, priv = format_agent_transcript(tick_records, aid, profiles)
            trace = emotion_history[aid][-5:]
            async with semaphore:
                result = await run_perception(
                    storages[aid], profiles[aid], states[aid],
                    scene, profiles,
                    known_events_by_agent.get(aid, []),
                    next_exam_in_days,
                    latest_event, transcript, priv,
                    tick_emotions[aid], day, exam_context,
                    emotion_trace=trace,
                )
            return aid, result

        perception_results = await asyncio.gather(
            *[_perceive(aid) for aid in perceiving]
        )
        outputs: dict[str, PerceptionOutput] = dict(perception_results)

        # Safety net: convert whisper to speech in dorm scenes
        if scene.location == "宿舍":
            for aid, out in outputs.items():
                if out.action_type == ActionType.WHISPER:
                    out.action_type = ActionType.SPEAK

        # Update in-memory emotions
        for aid, out in outputs.items():
            tick_emotions[aid] = out.emotion
            emotion_history[aid].append(out.emotion.value)

        # RESOLVE
        result = resolve_tick(
            outputs, resolution_state, profiles, states,
            last_resolved_speech, rng,
        )
        resolution_state = result.updated_state

        # RECORD
        tick_record = {
            "tick": tick,
            "agent_outputs": outputs,
            "resolved_speech": result.resolved_speech,
            "resolved_actions": result.resolved_actions,
            "whisper_events": result.whisper_events,
            "environmental_event": result.environmental_event,
            "exits": result.exits,
        }
        tick_records.append(tick_record)

        # Log
        if result.resolved_speech:
            aid, out = result.resolved_speech
            target = f"→{out.action_target}" if out.action_target else ""
            logger.info(f"  Tick {tick}: {profiles[aid].name}(说话{target}): {out.action_content}")
            last_resolved_speech = result.resolved_speech
        else:
            logger.info(f"  Tick {tick}: (安静)")

        for aid, out in result.resolved_actions:
            logger.info(f"  Tick {tick}: {profiles[aid].name}(动作): {out.action_content}")

        for from_id, to_id, _ in result.whisper_events:
            logger.info(f"  Tick {tick}: {profiles[from_id].name}(悄悄话→{profiles[to_id].name})")

        for aid in result.exits:
            logger.info(f"  Tick {tick}: {profiles[aid].name} 离开了")

        # Update latest_event for next tick
        latest_event = format_latest_event(
            result.resolved_speech,
            result.resolved_actions,
            result.whisper_events,
            result.environmental_event,
            result.exits,
            profiles,
        )

        if result.scene_should_end:
            logger.info(f"  Scene ends naturally at tick {tick}")
            break

    return tick_records
