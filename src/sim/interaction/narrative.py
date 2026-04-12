from __future__ import annotations

from ..models.agent import AgentProfile
from ..models.dialogue import PerceptionOutput


def _format_speech(name: str, output: PerceptionOutput) -> str:
    target = f"→{output.action_target}" if output.action_target else ""
    return f"  {name}(说话{target}): {output.action_content}"


def _format_non_verbal(name: str, output: PerceptionOutput) -> str:
    return f"  {name}(动作): {output.action_content}"


def _format_exit(name: str, output: PerceptionOutput) -> str:
    content = output.action_content or "离开了"
    return f"  {name}(离开): {content}"


def _summarize_ticks(tick_records: list[dict], start: int, end: int, profiles: dict[str, AgentProfile]) -> str:
    speakers = set()
    topics = []
    for rec in tick_records[start:end]:
        if rec.get("resolved_speech"):
            aid, output = rec["resolved_speech"]
            speakers.add(profiles[aid].name)
            if output.action_content and len(topics) < 3:
                # Take first ~10 chars as topic hint
                topics.append(output.action_content[:15] + "...")
    speaker_str = "、".join(speakers) if speakers else "无人"
    return f"  [Tick {start + 1}-{end}: {speaker_str}聊了几句]"


def format_public_transcript(
    tick_records: list[dict],
    profiles: dict[str, AgentProfile],
) -> str:
    lines: list[str] = []
    total = len(tick_records)

    # Mid-scene summarization: after tick 12, summarize ticks 1-6
    summarize_cutoff = 0
    if total > 12:
        summarize_cutoff = 6
        lines.append(_summarize_ticks(tick_records, 0, summarize_cutoff, profiles))
        lines.append("")

    for i, rec in enumerate(tick_records):
        if i < summarize_cutoff:
            continue

        tick_num = rec["tick"]
        tick_lines = [f"[Tick {tick_num + 1}]"]

        if rec.get("environmental_event"):
            tick_lines.append(f"  环境：{rec['environmental_event']}")

        if rec.get("resolved_speech"):
            aid, output = rec["resolved_speech"]
            tick_lines.append(_format_speech(profiles[aid].name, output))

        for aid, output in rec.get("resolved_actions", []):
            tick_lines.append(_format_non_verbal(profiles[aid].name, output))

        for aid in rec.get("exits", []):
            output = rec["agent_outputs"].get(aid)
            if output:
                tick_lines.append(_format_exit(profiles[aid].name, output))

        # Only add tick if something visible happened
        if len(tick_lines) > 1:
            lines.extend(tick_lines)

    return "\n".join(lines)


def format_agent_transcript(
    tick_records: list[dict],
    agent_id: str,
    profiles: dict[str, AgentProfile],
) -> tuple[str, list[str]]:
    """Returns (public_transcript, private_history) for a specific agent."""
    public_lines: list[str] = []
    private_history: list[str] = []
    total = len(tick_records)

    summarize_cutoff = 0
    if total > 12:
        summarize_cutoff = 6
        public_lines.append(_summarize_ticks(tick_records, 0, summarize_cutoff, profiles))
        public_lines.append("")

    for i, rec in enumerate(tick_records):
        # PDA gating: skip the agent's own private_history entry for ticks
        # where they were gated. Their perception was reused verbatim from
        # a prior fresh tick, so re-rendering it just produces duplicate
        # observation/inner_thought lines and confuses downstream prompts.
        is_self_gated = agent_id in set(rec.get("gated_agents", []))

        if i < summarize_cutoff:
            # Still collect private history from summarized ticks
            agent_out = rec["agent_outputs"].get(agent_id)
            if agent_out and not is_self_gated:
                private_history.append(f"[Tick {rec['tick'] + 1}] {agent_out.observation}")
                private_history.append(f"  (内心) {agent_out.inner_thought}")
            continue

        tick_num = rec["tick"]
        tick_lines = [f"[Tick {tick_num + 1}]"]

        if rec.get("environmental_event"):
            tick_lines.append(f"  环境：{rec['environmental_event']}")

        if rec.get("resolved_speech"):
            aid, output = rec["resolved_speech"]
            tick_lines.append(_format_speech(profiles[aid].name, output))

        for aid, output in rec.get("resolved_actions", []):
            tick_lines.append(_format_non_verbal(profiles[aid].name, output))

        for aid in rec.get("exits", []):
            agent_out = rec["agent_outputs"].get(aid)
            if agent_out:
                tick_lines.append(_format_exit(profiles[aid].name, agent_out))

        if len(tick_lines) > 1:
            public_lines.extend(tick_lines)

        # Private history for this agent
        agent_out = rec["agent_outputs"].get(agent_id)
        if agent_out and not is_self_gated:
            private_history.append(f"[Tick {tick_num + 1}] {agent_out.observation}")
            private_history.append(f"  (内心) {agent_out.inner_thought}")

    return "\n".join(public_lines), private_history


def format_latest_event(
    result_resolved_speech: tuple[str, PerceptionOutput] | None,
    result_resolved_actions: list[tuple[str, PerceptionOutput]],
    result_environmental_event: str | None,
    result_exits: list[str],
    profiles: dict[str, AgentProfile],
) -> str:
    parts: list[str] = []

    if result_environmental_event:
        parts.append(result_environmental_event)

    if result_resolved_speech:
        aid, output = result_resolved_speech
        name = profiles[aid].name
        target = f"对{output.action_target}" if output.action_target else ""
        parts.append(f"{name}{target}说：{output.action_content}")

    for aid, output in result_resolved_actions:
        parts.append(f"{profiles[aid].name}{output.action_content}")

    for aid in result_exits:
        parts.append(f"{profiles[aid].name}离开了")

    return "；".join(parts) if parts else "一片安静"
