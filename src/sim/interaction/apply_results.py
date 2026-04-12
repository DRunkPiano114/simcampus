from pathlib import Path

from loguru import logger

from ..agent.storage import AgentStorage, WorldStorage, atomic_write_json
from ..config import settings
from ..models.agent import ActiveConcern, AgentProfile, AgentState, Role
from ..models.dialogue import AgentReflection, NarrativeExtraction, SoloReflection
from ..models.relationship import Relationship
from ..models.scene import Scene
from ..world.event_queue import EventQueueManager


def is_trivial_scene(turn_records: list[dict]) -> bool:
    """A scene is trivial if nothing worth reflecting on happened.

    Trivial cases:
    - empty turn_records (defensive: shouldn't happen for ≥2-agent groups
      because solo groups are routed elsewhere, but handled gracefully)
    - no speech AND no environmental event in any tick
    - ≤2 ticks containing only observe / non-disruptive non_verbal actions
    """
    if not turn_records:
        return True
    # No speech and no environmental event anywhere in the scene
    has_speech = any(t.get("resolved_speech") for t in turn_records)
    has_env = any(t.get("environmental_event") for t in turn_records)
    if not has_speech and not has_env:
        return True
    # ≤2 ticks with only observe / non-disruptive non_verbal
    if len(turn_records) <= 2:
        all_trivial = True
        for t in turn_records:
            if t.get("resolved_speech"):
                all_trivial = False
                break
            for _, out in t.get("resolved_actions", []):
                if out.is_disruptive:
                    all_trivial = False
                    break
            if not all_trivial:
                break
        if all_trivial:
            return True
    return False


def _extract_tick_content(tick_record: dict) -> str:
    """Concatenate all source text from a tick record (speech / actions / env)
    for bigram-overlap grounding."""
    parts: list[str] = []
    if tick_record.get("resolved_speech"):
        _, out = tick_record["resolved_speech"]
        if out.action_content:
            parts.append(out.action_content)
    for _, out in tick_record.get("resolved_actions", []):
        if out.action_content:
            parts.append(out.action_content)
    if tick_record.get("environmental_event"):
        parts.append(tick_record["environmental_event"])
    return " ".join(parts)


def _bigrams(text: str) -> set[str]:
    """Generate character bigrams from Chinese text, ignoring whitespace."""
    text = text.replace(" ", "").replace("\n", "")
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _bigram_ratios(event_text: str, cited_content: str) -> tuple[float, float, int]:
    """Return (event_ratio, min_ratio, overlap_count) for telemetry.

    event_ratio = |overlap| / |event_bigrams| is the primary grounding
    signal. Using event as denominator means longer / more elaborated
    event text must overlap more with the cited content, catching the
    "expansion" failure mode where the LLM cites one short tick but
    writes a long elaborated event description.

    min_ratio = |overlap| / min(|event_bigrams|, |cited_bigrams|) is kept
    alongside for threshold tuning.
    """
    event_bg = _bigrams(event_text)
    cited_bg = _bigrams(cited_content)
    if not event_bg or not cited_bg:
        return 0.0, 0.0, 0
    overlap = event_bg & cited_bg
    event_ratio = len(overlap) / len(event_bg)
    min_ratio = len(overlap) / min(len(event_bg), len(cited_bg))
    return event_ratio, min_ratio, len(overlap)


def apply_trivial_scene_result(
    group_agent_ids: list[str],
    world: WorldStorage,
    scene: Scene,
    day: int,
    profiles: dict[str, AgentProfile],
) -> None:
    """Minimal update for trivial scenes — no reflection LLM call.

    This does NOT touch:
    - state.emotion (emotion value)
    - active_concerns
    - key_memories
    - relationships

    Emotion decay is driven by `_end_of_day` with hardcoded `scenes_since_extreme=2`
    (overnight sleep semantics), so trivial scenes don't need to advance any counter.
    """
    for aid in group_agent_ids:
        storage = world.get_agent(aid)
        entry = f"\n## {scene.time} {scene.name} @ {scene.location}\n（场景没有特别发生什么）\n"
        storage.append_today_md(entry)
    logger.debug(f"  Trivial scene for {scene.name}, skipped reflection")


def write_scene_file(
    path: Path,
    scene: Scene,
    participant_names: dict[str, str],
    groups_data: list[dict],
) -> None:
    """Write a complete scene file with all groups."""
    data = {
        "scene": {
            "scene_index": scene.scene_index,
            "time": scene.time,
            "name": scene.name.split("@")[0],
            "location": scene.location,
            "description": scene.description,
            "day": scene.day,
        },
        "participant_names": participant_names,
        "groups": groups_data,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, data)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _build_direct_interaction_set(
    aid: str,
    tick_records: list[dict],
    profiles: dict[str, AgentProfile],
) -> set[str]:
    """Compute the set of agent_ids that *aid* actually directly interacted with.

    Criteria (any one counts as direct):
    - aid spoke and action_target points to someone → aid direct'd them
    - someone else spoke and action_target is aid's name → bidirectional
    - aid's non_verbal action has a target → aid direct'd target
    - someone else's non_verbal action targets aid → bidirectional
    """
    name_to_id = {p.name: pid for pid, p in profiles.items()}
    my_name = profiles[aid].name
    targets: set[str] = set()
    for rec in tick_records or []:
        if rec.get("resolved_speech"):
            spk_id, out = rec["resolved_speech"]
            if spk_id == aid and out.action_target:
                tid = name_to_id.get(out.action_target)
                if tid:
                    targets.add(tid)
            elif spk_id != aid and out.action_target == my_name:
                targets.add(spk_id)
        for a_id, out in rec.get("resolved_actions", []):
            if a_id == aid and out.action_target:
                tid = name_to_id.get(out.action_target)
                if tid:
                    targets.add(tid)
            elif a_id != aid and out.action_target == my_name:
                targets.add(a_id)
    return targets


def _find_existing_concern(
    state: AgentState,
    new_concern: ActiveConcern,
) -> ActiveConcern | None:
    """Find an existing concern that matches by topic and people.

    For topic="其他":
      - If either side has empty related_people, NEVER merge. Two empty-people
        其他 concerns are almost always unrelated and merging them produces a
        useless meta-concern; intensity cap + eviction is the only control.
      - Otherwise require an EXACT people-set match.

    For other (categorized) topics, any non-empty people overlap merges;
    empty-people collisions stay as separate entries.
    """
    for c in state.active_concerns:
        if c.topic != new_concern.topic:
            continue
        if new_concern.topic == "其他":
            # Frankenstein guard: refuse to merge when either side has no people
            if not new_concern.related_people or not c.related_people:
                continue
            if set(c.related_people) == set(new_concern.related_people):
                return c
        else:
            # Permissive: any non-empty people overlap merges
            if set(c.related_people) & set(new_concern.related_people):
                return c
    return None


def add_concern(
    state: AgentState,
    new_concern: ActiveConcern,
    today: int,
    skip_cap: bool = False,
) -> None:
    """Add a concern with topic-based dedup.

    `skip_cap=True` bypasses `concern_autogen_max_intensity` and lets the
    new concern land at its full claimed intensity. It's reserved for
    high-priority sources like exam shock; default reflection-originated
    concerns are capped to keep day-to-day drama from accumulating.

    Merge path: if a same-topic, people-matching concern exists, the new
    one is folded in — text and source_event refresh, last_reinforced_day
    updates, and intensity grows. Without skip_cap the merge bumps the
    existing intensity by 1 regardless of the new claim, so reinforcement
    cannot jump past the cap via the merge path. With skip_cap, intensity
    becomes max(existing, new) + 1 so a follow-up shock can drive the
    floor up.

    No-match path: cap the new intensity (unless skip_cap), then either
    append or evict the lowest-intensity active concern.
    """
    existing = _find_existing_concern(state, new_concern)
    if existing:
        if skip_cap:
            existing.intensity = min(10, max(existing.intensity, new_concern.intensity) + 1)
        else:
            existing.intensity = min(10, existing.intensity + 1)
        # Preserve old text in history before overwriting
        if existing.text != new_concern.text and existing.text not in existing.text_history:
            existing.text_history.append(existing.text)
            existing.text_history = existing.text_history[-3:]
        existing.text = new_concern.text
        if existing.source_event and new_concern.source_event:
            merged_source = existing.source_event + "；" + new_concern.source_event
        else:
            merged_source = existing.source_event or new_concern.source_event
        # Slice from the tail: when a concern is reinforced many times and
        # the concatenated source_event exceeds 500 chars, we want to keep
        # the MOST RECENT triggers (what the reader cares about: "what set
        # it off this time") and drop the oldest prefix. Using [:500] would
        # do the opposite — preserving the initial trigger and silently
        # discarding every subsequent reinforcement once the buffer filled.
        existing.source_event = merged_source[-500:]
        existing.last_reinforced_day = today
        return

    if not skip_cap:
        new_concern.intensity = min(
            new_concern.intensity, settings.concern_autogen_max_intensity,
        )
    new_concern.last_reinforced_day = today

    if len(state.active_concerns) >= settings.max_active_concerns:
        state.active_concerns.sort(key=lambda c: c.intensity)
        if new_concern.intensity > state.active_concerns[0].intensity:
            state.active_concerns.pop(0)
        else:
            return
    state.active_concerns.append(new_concern)


def concern_match(text_a: str, text_b: str | None) -> bool:
    """Bidirectional substring match for concern/intention alignment."""
    if not text_b:
        return False
    return text_b in text_a or text_a in text_b


def apply_scene_end_results(
    narrative: NarrativeExtraction,
    reflections: dict[str, AgentReflection],
    world: WorldStorage,
    scene: Scene,
    group_agent_ids: list[str],
    day: int,
    group_id: int,
    profiles: dict[str, AgentProfile],
    event_manager: EventQueueManager,
    tick_records: list[dict] | None = None,
) -> None:
    # Snapshot baselines for idempotent relationship updates
    baselines: dict[str, dict] = {}
    for aid in group_agent_ids:
        storage = world.get_agent(aid)
        rels = storage.load_relationships()
        baselines[aid] = {
            target_id: rel.model_dump()
            for target_id, rel in rels.relationships.items()
        }

    # Name → agent_id mapping
    name_to_id = {p.name: aid for aid, p in profiles.items()}

    # 2. Update each agent from their own reflection
    for aid in group_agent_ids:
        storage = world.get_agent(aid)
        state = storage.load_state()
        rels = storage.load_relationships()
        refl = reflections.get(aid, AgentReflection())

        # Update emotion directly from reflection (Emotion enum, no try/except needed)
        state.emotion = refl.emotion

        # Update today.md with key moments (shared objective record)
        if narrative.key_moments:
            entry = f"\n## {scene.time} {scene.name} @ {scene.location}\n"
            entry += "\n".join(f"- {m}" for m in narrative.key_moments)
            entry += f"\n当前情绪：{state.emotion.value}\n"
            storage.append_today_md(entry)

        # Append memories above the configured importance threshold.
        for mem in refl.memories:
            if mem.importance >= settings.key_memory_write_threshold:
                from ..models.memory import KeyMemory
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

        # Update relationships from agent's own reflection
        for change in refl.relationship_changes:
            to_id = name_to_id.get(change.to_agent)
            if not to_id:
                logger.warning(
                    f"  [{aid}] relationship_change target '{change.to_agent}' "
                    f"not in profiles, dropped"
                )
                continue

            # Auto-insert a zero-state entry if the target isn't yet in the
            # relationship map. The LLM legitimately discovers new connections
            # mid-scene; dropping such changes silently loses signal.
            if to_id not in rels.relationships:
                target_profile = profiles[to_id]
                source_profile = profiles[aid]
                # Label depends on BOTH source and target roles, not just target.
                # Prior bug: teacher auto-inserting a student got label="同学".
                if (
                    source_profile.role == Role.HOMEROOM_TEACHER
                    and target_profile.role != Role.HOMEROOM_TEACHER
                ):
                    label = "学生"
                elif target_profile.role == Role.HOMEROOM_TEACHER:
                    label = "老师"
                else:
                    label = "同学"
                rels.relationships[to_id] = Relationship(
                    target_name=target_profile.name,
                    target_id=to_id,
                    favorability=0,
                    trust=0,
                    understanding=0,
                    label=label,
                    recent_interactions=[],
                )
                logger.info(
                    f"  [{aid}] auto-inserted relationship → {target_profile.name} ({label})"
                )

            rel = rels.relationships[to_id]
            base = baselines.get(aid, {}).get(to_id)

            # Double-gate: LLM self-label is necessary, tick_records evidence
            # is sufficient. Both must agree for ±3; otherwise clamp to ±1.
            direct_set = _build_direct_interaction_set(aid, tick_records or [], profiles)
            effective_direct = change.direct_interaction and (to_id in direct_set)
            max_delta = 3 if effective_direct else 1
            fav_delta = _clamp(change.favorability, -max_delta, max_delta)
            trust_delta = _clamp(change.trust, -max_delta, max_delta)
            und_delta = _clamp(change.understanding, -max_delta, max_delta)

            if base:
                rel.favorability = _clamp(base["favorability"] + fav_delta, -100, 100)
                rel.trust = _clamp(base["trust"] + trust_delta, -100, 100)
                rel.understanding = _clamp(base["understanding"] + und_delta, 0, 100)
            else:
                rel.favorability = _clamp(rel.favorability + fav_delta, -100, 100)
                rel.trust = _clamp(rel.trust + trust_delta, -100, 100)
                rel.understanding = _clamp(rel.understanding + und_delta, 0, 100)

            # Record this scene as a recent interaction. Dedup on the
            # (day, scene_name) part of the tag so multiple
            # relationship_changes against the same target within one scene
            # don't spam the log. A valence marker is prepended to the scene
            # name (+ / − / ·) derived from the signed favorability+trust
            # delta, so downstream prompts can read a relationship's
            # interaction timeline and distinguish "Day 3 + 课间@走廊"
            # (warm) from "Day 4 − 宿舍夜聊" (friction) without having to
            # infer valence from the current absolute scores. Understanding
            # is excluded from the valence calc because it measures "how
            # well I know them", not affect.
            if change.favorability or change.trust or change.understanding:
                valence = change.favorability + change.trust
                if valence > 0:
                    mark = "+"
                elif valence < 0:
                    mark = "−"
                else:
                    mark = "·"
                interaction_tag = f"Day {day} {mark}{scene.name}"
                # Dedup check looks at the full tag — two changes with the
                # same sign in the same scene collapse; a mixed scene where
                # one delta is + and another is − would legitimately record
                # both (rare but possible across multi-target reflections).
                if interaction_tag not in rel.recent_interactions:
                    rel.recent_interactions.append(interaction_tag)
                if len(rel.recent_interactions) > settings.max_recent_interactions:
                    rel.recent_interactions = rel.recent_interactions[
                        -settings.max_recent_interactions:
                    ]

        # Mark intention outcomes from agent's own reflection
        for outcome in refl.intention_outcomes:
            for intent in state.daily_plan.intentions:
                if not intent.fulfilled and concern_match(intent.goal, outcome.goal):
                    if outcome.status == "fulfilled":
                        intent.fulfilled = True
                        # Concern decay on fulfillment
                        if intent.satisfies_concern:
                            for c in state.active_concerns:
                                if concern_match(c.text, intent.satisfies_concern):
                                    c.intensity = max(0, c.intensity - 2)
                                    break
                    elif outcome.status == "frustrated":
                        # Frustration can intensify the linked concern
                        if intent.satisfies_concern:
                            for c in state.active_concerns:
                                if concern_match(c.text, intent.satisfies_concern):
                                    c.intensity = min(10, c.intensity + 1)
                                    break
                    elif outcome.status == "abandoned":
                        intent.abandoned = True
                    break  # one outcome matches at most one intent

        # Apply new concerns from agent's own reflection
        for cc in refl.new_concerns:
            new_concern = ActiveConcern(
                text=cc.text, source_event=cc.source_event,
                source_scene=scene.name, source_day=day, emotion=cc.emotion,
                intensity=cc.intensity, related_people=cc.related_people,
                positive=cc.positive, topic=cc.topic,
            )
            add_concern(state, new_concern, today=day)

        # Apply concern intensity adjustments from agent's own reflection
        for cu in refl.concern_updates:
            for c in state.active_concerns:
                if cu.concern_text in c.text or c.text in cu.concern_text:
                    c.intensity = max(0, min(10, c.intensity + cu.adjustment))
        state.active_concerns = [c for c in state.active_concerns if c.intensity > 0]

        storage.save_state(state)
        storage.save_relationships(rels)

    # 3. Update event queue (from shared narrative)
    for event_id in narrative.events_discussed:
        event_manager.mark_discussed(event_id, group_agent_ids)

    # 3-layer cite_ticks validation for new_events.
    # Keys are tick+1 to match the 1-indexed [Tick N] labels shown to the LLM
    # in narrative.py. The mid-scene summarized prefix is excluded:
    # narrative.py collapses ticks 0~5 (0-indexed) into one summary line when
    # len(tick_records) > 12, so the LLM never sees those ticks' raw content
    # and any cite into that range cannot be bigram-validated.
    valid_ticks: dict[int, dict] = {}
    if tick_records:
        summarize_cutoff = 6 if len(tick_records) > 12 else 0
        valid_ticks = {
            t["tick"] + 1: t
            for t in tick_records
            if t["tick"] >= summarize_cutoff
        }
    threshold = 0.3

    for new_evt in narrative.new_events:
        # Layer 1: cite_ticks must be non-empty
        if not new_evt.cite_ticks:
            logger.warning(
                f"  [scene_end] drop (no cite_ticks): {new_evt.text[:50]}"
            )
            continue
        # Layer 2: every cited tick must exist in tick_records (1-indexed
        # space) AND not fall inside the summarized prefix.
        if not valid_ticks or not all(t in valid_ticks for t in new_evt.cite_ticks):
            logger.warning(
                f"  [scene_end] drop (invalid cite_ticks {new_evt.cite_ticks}): "
                f"{new_evt.text[:50]}"
            )
            continue
        # Layer 3: bigram overlap between event text and cited tick content
        cited_content = " ".join(
            _extract_tick_content(valid_ticks[t]) for t in new_evt.cite_ticks
        )
        event_ratio, min_ratio, overlap_count = _bigram_ratios(
            new_evt.text, cited_content,
        )
        if event_ratio < threshold:
            logger.warning(
                f"  [scene_end] drop (bigram overlap={overlap_count} "
                f"event_ratio={event_ratio:.1%} min_ratio={min_ratio:.1%} "
                f"< {threshold:.0%}): {new_evt.text[:50]}"
            )
            continue

        witness_ids = [name_to_id.get(w, w) for w in new_evt.witnesses]
        event_manager.add_event(
            text=new_evt.text,
            category=new_evt.category,
            source_scene=scene.name,
            source_day=day,
            witnesses=[w for w in witness_ids if w in profiles],
            spread_probability=new_evt.spread_probability,
            cite_ticks=new_evt.cite_ticks,
            group_index=group_id,
        )

    logger.debug(f"  Applied results for group {group_id}")


def apply_solo_result(
    reflection: SoloReflection,
    storage: AgentStorage,
    profile: AgentProfile,
    scene: Scene,
    day: int,
) -> None:
    state = storage.load_state()
    state.emotion = reflection.emotion

    entry = f"\n## {scene.time} {scene.name} @ {scene.location}\n"
    entry += f"（一个人）{reflection.activity}\n"
    entry += f"内心：{reflection.inner_thought}\n"
    entry += f"当前情绪：{reflection.emotion.value}\n"
    storage.append_today_md(entry)
    storage.save_state(state)

    logger.debug(f"  Applied solo result for {profile.name}")
