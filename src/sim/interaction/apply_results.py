import json
from pathlib import Path

from loguru import logger

from ..agent.storage import AgentStorage, WorldStorage, atomic_write_json
from ..config import settings
from ..models.agent import ActiveConcern, AgentProfile, Emotion
from ..models.dialogue import SceneEndAnalysis, SoloReflection
from ..models.scene import Scene
from ..world.event_queue import EventQueueManager


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _is_duplicate_concern(new_concern, existing_concerns):
    """Structural dedup: same day + same scene + overlapping people = same event."""
    for c in existing_concerns:
        if (c.source_day == new_concern.source_day
            and c.source_scene == new_concern.source_scene
            and set(c.related_people) & set(new_concern.related_people)):
            return True
    return False


def apply_scene_end_results(
    analysis: SceneEndAnalysis,
    world: WorldStorage,
    scene: Scene,
    group_agent_ids: list[str],
    day: int,
    group_id: int,
    profiles: dict[str, AgentProfile],
    event_manager: EventQueueManager,
) -> None:
    # 1. Save result file with baseline snapshot (for idempotency)
    result_dir = settings.logs_dir / f"day_{day:03d}" / scene.name
    result_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot baselines
    baselines: dict[str, dict] = {}
    for aid in group_agent_ids:
        storage = world.get_agent(aid)
        rels = storage.load_relationships()
        baselines[aid] = {
            target_id: rel.model_dump()
            for target_id, rel in rels.relationships.items()
        }

    result_data = {
        "analysis": analysis.model_dump(),
        "baselines": baselines,
    }
    result_file = result_dir / f"group_{group_id}_result.json"
    atomic_write_json(result_file, result_data)

    # Name → agent_id mapping
    name_to_id = {p.name: aid for aid, p in profiles.items()}

    # 2. Update each agent
    for aid in group_agent_ids:
        storage = world.get_agent(aid)
        state = storage.load_state()
        rels = storage.load_relationships()

        # Update emotion from final_emotions
        agent_name = profiles[aid].name
        if agent_name in analysis.final_emotions:
            emotion_str = analysis.final_emotions[agent_name]
            try:
                state.emotion = Emotion(emotion_str)
            except ValueError:
                pass

        # Update today.md with key moments
        agent_moments = [m for m in analysis.key_moments]
        if agent_moments:
            entry = f"\n## {scene.time} {scene.name} @ {scene.location}\n"
            entry += "\n".join(f"- {m}" for m in agent_moments)
            entry += f"\n当前情绪：{state.emotion.value}\n"
            storage.append_today_md(entry)

        # Update key_memories (importance >= 7)
        for mem in analysis.memories:
            if mem.importance >= 7:
                mem_agent_id = name_to_id.get(mem.agent)
                if mem_agent_id == aid:
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

        # Update relationships (baseline + delta → absolute)
        for change in analysis.relationship_changes:
            from_id = name_to_id.get(change.from_agent)
            to_id = name_to_id.get(change.to_agent)
            if from_id != aid:
                continue
            if to_id and to_id in rels.relationships:
                rel = rels.relationships[to_id]
                # Use baseline if available, otherwise current
                base = baselines.get(aid, {}).get(to_id)
                if base:
                    rel.favorability = _clamp(base["favorability"] + change.favorability, -100, 100)
                    rel.trust = _clamp(base["trust"] + change.trust, -100, 100)
                    rel.understanding = _clamp(base["understanding"] + change.understanding, 0, 100)
                else:
                    rel.favorability = _clamp(rel.favorability + change.favorability, -100, 100)
                    rel.trust = _clamp(rel.trust + change.trust, -100, 100)
                    rel.understanding = _clamp(rel.understanding + change.understanding, 0, 100)

        # Mark fulfilled intentions
        for fi in analysis.fulfilled_intentions:
            parts = fi.split(":", 1)
            if len(parts) == 2 and parts[0].strip() == agent_name:
                for intent in state.daily_plan.intentions:
                    if not intent.fulfilled and parts[1].strip() in intent.goal:
                        intent.fulfilled = True

        storage.save_state(state)
        storage.save_relationships(rels)

    # 3. Update event queue
    for event_id in analysis.events_discussed:
        event_manager.mark_discussed(event_id, group_agent_ids)

    for new_evt in analysis.new_events:
        witness_ids = [name_to_id.get(w, w) for w in new_evt.witnesses]
        event_manager.add_event(
            text=new_evt.text,
            category=new_evt.category,
            source_scene=scene.name,
            source_day=day,
            witnesses=[w for w in witness_ids if w in profiles],
            spread_probability=new_evt.spread_probability,
        )

    # 4. Apply new concerns (structural dedup)
    for cc in analysis.new_concerns:
        target_id = name_to_id.get(cc.agent)
        if not target_id or target_id not in group_agent_ids:
            continue
        storage = world.get_agent(target_id)
        state = storage.load_state()

        new_concern = ActiveConcern(
            text=cc.text, source_event=cc.source_event,
            source_scene=scene.name, source_day=day, emotion=cc.emotion,
            intensity=cc.intensity, related_people=cc.related_people,
        )

        if _is_duplicate_concern(new_concern, state.active_concerns):
            continue

        # Enforce max: evict lowest intensity if full
        if len(state.active_concerns) >= settings.max_active_concerns:
            state.active_concerns.sort(key=lambda c: c.intensity)
            if new_concern.intensity > state.active_concerns[0].intensity:
                state.active_concerns.pop(0)
            else:
                continue
        state.active_concerns.append(new_concern)
        storage.save_state(state)

    # 5. Apply concern intensity adjustments
    for cu in analysis.concern_updates:
        target_id = name_to_id.get(cu.agent)
        if not target_id or target_id not in group_agent_ids:
            continue
        storage = world.get_agent(target_id)
        state = storage.load_state()
        for c in state.active_concerns:
            if cu.concern_text in c.text or c.text in cu.concern_text:
                c.intensity = max(0, min(10, c.intensity + cu.adjustment))
        # Remove concerns with intensity <= 0
        state.active_concerns = [c for c in state.active_concerns if c.intensity > 0]
        storage.save_state(state)

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
