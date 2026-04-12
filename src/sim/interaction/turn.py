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


def _compute_pacing_label(tick: int, max_rounds: int) -> str:
    """Translate tick/max_rounds ratio into an embodied pacing label.

    Gives the LLM a participant-side cue ("scene is winding down") instead
    of forcing it to count ticks. Labels are deliberately deflationary
    ("差不多该散了") to discourage staged drama at scene boundaries.
    """
    if max_rounds <= 0:
        return ""
    progress = tick / max_rounds
    if progress < 0.3:
        return "刚开始"
    if progress < 0.7:
        return "在聊"
    return "差不多该散了"


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
    group_index: int = 0,
    scene_pacing_label: str = "",
) -> PerceptionOutput:
    ctx = prepare_context(
        storage, profile, state, scene, all_profiles,
        known_events, next_exam_in_days, exam_context=exam_context,
        latest_event=latest_event,
        scene_transcript=scene_transcript,
        private_history=private_history,
        emotion_override=tick_emotion,
        emotion_trace=emotion_trace,
        scene_pacing_label=scene_pacing_label,
    )

    static_msg = render("perception_static.j2", **ctx)
    dynamic_msg = render("perception_dynamic.j2", **ctx)
    messages = [
        {"role": "system", "content": static_msg},
        {"role": "user", "content": dynamic_msg},
    ]

    start = time.time()
    llm_result = await structured_call(
        PerceptionOutput,
        messages,
        temperature=settings.perception_temperature,
        max_tokens=settings.max_tokens_perception,
    )
    latency = (time.time() - start) * 1000
    result = llm_result.data

    log_llm_call(
        day=day,
        scene_name=scene.name,
        group_id=group_index,
        call_type="perception",
        input_messages=messages,
        output=result,
        tokens_prompt=llm_result.tokens_prompt,
        tokens_completion=llm_result.tokens_completion,
        cost_usd=llm_result.cost_usd,
        latency_ms=latency,
        temperature=settings.perception_temperature,
    )

    return result


def _should_perceive(
    aid: str,
    tick: int,
    last_resolved_speech: tuple[str, PerceptionOutput] | None,
    environmental_event: str | None,
    latest_event: str,
    profiles: dict[str, AgentProfile],
    states: dict[str, AgentState],
    last_perceive_tick: dict[str, int],
) -> bool:
    """Decide whether an agent needs a fresh perception this tick."""
    # Rule 1: Tick 0 — everyone must perceive
    if tick == 0:
        return True

    # Rule 2: Directly targeted by last speech
    if last_resolved_speech:
        _, last_out = last_resolved_speech
        if last_out.action_target and last_out.action_target == profiles[aid].name:
            return True

    # Rule 3: Name mentioned in latest_event text
    if profiles[aid].name in latest_event:
        return True

    # Rule 4: Environmental event this tick (disruptive action)
    if environmental_event:
        return True

    # Rule 5: Concern-related person mentioned in latest_event
    state = states.get(aid)
    if state:
        for concern in state.active_concerns:
            for rp in concern.related_people:
                if rp in latest_event:
                    return True

    # Rule 6: 4-tick cadence — force perceive if silent too long
    last_tick = last_perceive_tick.get(aid, -4)
    if tick - last_tick >= 4:
        return True

    return False


def _make_gated_output(last_output: PerceptionOutput) -> PerceptionOutput:
    """Create a passive OBSERVE output reusing last perception's emotion."""
    return PerceptionOutput(
        observation=last_output.observation,
        inner_thought=last_output.inner_thought,
        emotion=last_output.emotion,
        action_type=ActionType.OBSERVE,
        action_content=None,
        action_target=None,
        urgency=max(1, last_output.urgency - 1),
        is_disruptive=False,
    )


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
    exam_context: dict[str, str] | None = None,
    group_index: int = 0,
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

    # PDA gating state
    last_perception: dict[str, PerceptionOutput] = {}
    last_perceive_tick: dict[str, int] = {}
    # Track the environmental_event from previous tick for gating decisions
    prev_environmental_event: str | None = None
    # Pacing label state — only render on threshold transitions to avoid noise.
    # Init to "刚开始" so tick 0 is silently skipped (LLM already knows the
    # scene just started; the label would be pure noise).
    prev_pacing_label: str = "刚开始"

    for tick in range(scene.max_rounds):
        active_agents = list(resolution_state.active_agents)
        if len(active_agents) < 2:
            break

        # Compute pacing label for this tick — only inject when it crosses
        # a threshold ("刚开始" → "在聊" → "差不多该散了"); otherwise pass
        # an empty string and the template will skip rendering.
        current_pacing_label = _compute_pacing_label(tick, scene.max_rounds)
        if current_pacing_label != prev_pacing_label:
            tick_pacing_label = current_pacing_label
            prev_pacing_label = current_pacing_label
        else:
            tick_pacing_label = ""

        # Determine which agents need to perceive (skip queued agents entirely)
        non_queued = [
            aid for aid in active_agents
            if aid not in resolution_state.queued_agents
        ]

        # Gate: decide who actually needs a fresh LLM perception call
        perceiving = []
        gated = []
        for aid in non_queued:
            if _should_perceive(
                aid, tick, last_resolved_speech, prev_environmental_event,
                latest_event, profiles, states, last_perceive_tick,
            ):
                perceiving.append(aid)
            elif aid in last_perception:
                gated.append(aid)
            else:
                # No previous output to reuse, must perceive
                perceiving.append(aid)

        # PERCEIVE: agents that need fresh perception
        async def _perceive(aid: str) -> tuple[str, PerceptionOutput]:
            transcript, priv = format_agent_transcript(tick_records, aid, profiles)
            trace = emotion_history[aid][-5:]
            agent_exam_ctx = exam_context.get(aid, "") if exam_context else ""
            async with semaphore:
                result = await run_perception(
                    storages[aid], profiles[aid], states[aid],
                    scene, profiles,
                    known_events_by_agent.get(aid, []),
                    next_exam_in_days,
                    latest_event, transcript, priv,
                    tick_emotions[aid], day, agent_exam_ctx,
                    emotion_trace=trace,
                    group_index=group_index,
                    scene_pacing_label=tick_pacing_label,
                )
            return aid, result

        perception_results = await asyncio.gather(
            *[_perceive(aid) for aid in perceiving]
        )
        outputs: dict[str, PerceptionOutput] = dict(perception_results)

        # Update gating state for fresh perceptions
        for aid, out in outputs.items():
            last_perception[aid] = out
            last_perceive_tick[aid] = tick

        # Add gated agents with passive OBSERVE outputs
        for aid in gated:
            outputs[aid] = _make_gated_output(last_perception[aid])

        # Update in-memory emotions (only for fresh perceptions, not gated)
        for aid in perceiving:
            if aid in outputs:
                tick_emotions[aid] = outputs[aid].emotion
                emotion_history[aid].append(outputs[aid].emotion.value)

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
            # PDA gating: these agents reused last_perception verbatim this
            # tick (no fresh LLM call). Their observation/inner_thought are
            # stale copies and should NOT be re-rendered into transcripts or
            # serialized mind dumps, or they pollute logs and downstream
            # scene_end_analysis / reflection prompts with duplicate lines.
            "gated_agents": list(gated),
            "resolved_speech": result.resolved_speech,
            "resolved_actions": result.resolved_actions,
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

        for aid in result.exits:
            logger.info(f"  Tick {tick}: {profiles[aid].name} 离开了")

        # Track environmental_event for next tick's gating
        prev_environmental_event = result.environmental_event

        # Update latest_event for next tick
        latest_event = format_latest_event(
            result.resolved_speech,
            result.resolved_actions,
            result.environmental_event,
            result.exits,
            profiles,
        )

        if result.scene_should_end:
            logger.info(f"  Scene ends naturally at tick {tick}")
            break

    return tick_records
