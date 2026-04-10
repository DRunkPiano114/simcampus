from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from statistics import variance

from ..config import settings
from ..models.agent import AgentProfile, AgentState
from ..models.dialogue import ActionType, PerceptionOutput
from .apply_results import concern_match

QUEUE_EXPIRY_TICKS = 3


@dataclass
class ResolutionState:
    queued_agents: dict[str, tuple[PerceptionOutput, int]] = field(default_factory=dict)
    consecutive_quiet: int = 0
    tick_count: int = 0
    active_agents: set[str] = field(default_factory=set)


@dataclass
class ResolutionResult:
    resolved_speech: tuple[str, PerceptionOutput] | None = None
    resolved_actions: list[tuple[str, PerceptionOutput]] = field(default_factory=list)
    environmental_event: str | None = None
    exits: list[str] = field(default_factory=list)
    scene_should_end: bool = False
    updated_state: ResolutionState = field(default_factory=ResolutionState)


def _build_name_to_id(profiles: dict[str, AgentProfile]) -> dict[str, str]:
    return {p.name: aid for aid, p in profiles.items()}


def _compute_resolution_score(
    aid: str,
    output: PerceptionOutput,
    ticks_queued: int,
    last_resolved_speech: tuple[str, PerceptionOutput] | None,
    agent_states: dict[str, AgentState],
    active_names: set[str],
    profiles: dict[str, AgentProfile],
    use_clustering_fallback: bool,
) -> float:
    bonus = 0

    if last_resolved_speech is not None:
        _, last_output = last_resolved_speech
        if last_output.action_target and last_output.action_target == profiles[aid].name:
            bonus += 5

    state = agent_states.get(aid)
    if state:
        best_intent_bonus = 0
        for intention in state.daily_plan.intentions:
            if not intention.fulfilled and intention.target and intention.target in active_names:
                base = 3
                if intention.satisfies_concern:
                    for c in state.active_concerns:
                        if concern_match(c.text, intention.satisfies_concern):
                            base = 3 * max(1.0, c.intensity / 5.0)
                            break
                best_intent_bonus = max(best_intent_bonus, base)
        bonus += int(best_intent_bonus)

    bonus += 3 * ticks_queued

    if use_clustering_fallback:
        return bonus + output.urgency * 0.1
    return output.urgency + bonus


def resolve_tick(
    agent_outputs: dict[str, PerceptionOutput],
    state: ResolutionState,
    profiles: dict[str, AgentProfile],
    agent_states: dict[str, AgentState],
    last_resolved_speech: tuple[str, PerceptionOutput] | None,
    rng: Random,
) -> ResolutionResult:
    active = set(state.active_agents)
    exits: list[str] = []
    resolved_actions: list[tuple[str, PerceptionOutput]] = []
    environmental_event: str | None = None
    name_to_id = _build_name_to_id(profiles)
    active_names = {profiles[aid].name for aid in active}

    # --- Handle exits ---
    for aid, output in agent_outputs.items():
        if output.action_type == ActionType.EXIT:
            exits.append(aid)
            active.discard(aid)
            active_names.discard(profiles[aid].name)

    # --- Handle non-verbal actions ---
    for aid, output in agent_outputs.items():
        if output.action_type == ActionType.NON_VERBAL:
            resolved_actions.append((aid, output))
            if output.is_disruptive and output.action_content:
                environmental_event = f"\u3010\u52a8\u4f5c\u3011{profiles[aid].name}: {output.action_content}"

    # --- Speaker resolution ---
    current_speakers: dict[str, tuple[PerceptionOutput, int]] = {}
    for aid, output in agent_outputs.items():
        if output.action_type == ActionType.SPEAK and aid in active:
            current_speakers[aid] = (output, 0)

    # Merge with queued agents
    all_candidates: dict[str, tuple[PerceptionOutput, int]] = {}
    for aid, (output, ticks) in state.queued_agents.items():
        if aid in active and aid not in exits:
            target_name = output.action_target
            if target_name:
                target_aid = name_to_id.get(target_name)
                if target_aid and target_aid not in active:
                    continue
            if ticks + 1 > QUEUE_EXPIRY_TICKS:
                continue
            all_candidates[aid] = (output, ticks + 1)

    all_candidates.update(current_speakers)

    # Determine clustering fallback
    use_clustering_fallback = False
    if len(current_speakers) >= 2:
        urgencies = [out.urgency for out, _ in current_speakers.values()]
        if variance(urgencies) <= 2:
            use_clustering_fallback = True

    resolved_speech: tuple[str, PerceptionOutput] | None = None
    new_queue: dict[str, tuple[PerceptionOutput, int]] = {}

    if all_candidates:
        scored: list[tuple[str, float]] = []
        for aid, (output, ticks_queued) in all_candidates.items():
            score = _compute_resolution_score(
                aid=aid,
                output=output,
                ticks_queued=ticks_queued,
                last_resolved_speech=last_resolved_speech,
                agent_states=agent_states,
                active_names=active_names,
                profiles=profiles,
                use_clustering_fallback=use_clustering_fallback,
            )
            scored.append((aid, score))

        max_score = max(s for _, s in scored)
        tied = [aid for aid, s in scored if s == max_score]
        winner = rng.choice(tied)
        winner_output, _ = all_candidates[winner]
        resolved_speech = (winner, winner_output)

        for aid, (output, ticks_queued) in all_candidates.items():
            if aid != winner:
                new_queue[aid] = (output, ticks_queued)

    # --- Quiet-tick check ---
    quiet_tick = (
        resolved_speech is None
        and len(new_queue) == 0
        and environmental_event is None
    )
    consecutive_quiet = state.consecutive_quiet + 1 if quiet_tick else 0

    # --- Scene end ---
    tick_count = state.tick_count + 1
    scene_should_end = (
        consecutive_quiet >= settings.consecutive_quiet_to_end
        and tick_count >= settings.min_ticks_before_termination
    )

    updated_state = ResolutionState(
        queued_agents=new_queue,
        consecutive_quiet=consecutive_quiet,
        tick_count=tick_count,
        active_agents=active,
    )

    return ResolutionResult(
        resolved_speech=resolved_speech,
        resolved_actions=resolved_actions,
        environmental_event=environmental_event,
        exits=exits,
        scene_should_end=scene_should_end,
        updated_state=updated_state,
    )
