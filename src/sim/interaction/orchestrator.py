import asyncio
import random
import shutil
import time
from datetime import datetime
from pathlib import Path

from loguru import logger

from ..agent.daily_plan import generate_daily_plan
from ..agent.replan import maybe_replan
from ..agent.self_narrative import generate_self_narrative
from ..agent.state_update import (
    EXTREME_EMOTIONS,
    decay_concerns,
    maybe_decay_emotion,
    regress_relationships,
    reset_energy_for_sleep,
    update_academic_pressure,
    update_energy,
)
from ..agent.storage import WorldStorage
from ..config import settings
from ..memory.compression import nightly_compress
from ..models.agent import AgentProfile, AgentState, Role
from ..models.progress import GroupCompletion, Progress, SceneProgress
from ..models.scene import Scene
from ..models.trajectory import AgentSlot, DayTrajectory
from ..world.event_queue import EventQueueManager
from ..world.grouping import group_agents
from ..world.scene_generator import SceneGenerator
from ..world.schedule import load_schedule
from .apply_results import (
    apply_scene_end_results,
    apply_solo_result,
    apply_trivial_scene_result,
    is_trivial_scene,
    write_scene_file,
)
from .scene_end import run_scene_end_analysis
from .self_reflection import run_all_reflections
from .solo import run_solo_reflection
from .turn import run_group_dialogue
from ..world.exam import (
    apply_exam_effects,
    format_exam_context,
    format_teacher_exam_context,
    generate_exam_results,
    load_previous_exam_results,
    save_exam_results,
)
from ..world.homeroom_teacher import HomeroomTeacher


def serialize_tick_records(
    tick_records: list[dict],
    profiles: dict[str, "AgentProfile"],
) -> list[dict]:
    """Convert in-memory tick_records → frontend-ready ticks array."""
    name_to_id = {p.name: aid for aid, p in profiles.items()}

    def _name_to_id(name: str | None) -> str | None:
        if not name:
            return None
        return name_to_id.get(name, name)

    ticks = []
    for rec in tick_records:
        # public.speech
        speech = None
        if rec["resolved_speech"]:
            aid, out = rec["resolved_speech"]
            speech = {
                "agent": aid,
                "target": _name_to_id(out.action_target),
                "content": out.action_content,
            }

        # public.actions (non_verbal resolved actions)
        actions = []
        for aid, out in rec["resolved_actions"]:
            actions.append({
                "agent": aid,
                "type": out.action_type.value,
                "content": out.action_content,
            })

        # public.exits
        exits = rec.get("exits", [])

        # minds: only agents who had a FRESH perception this tick. Gated
        # agents reused last_perception unchanged (PDA optimization), so
        # their observation/inner_thought are stale copies — serializing
        # them produces the same long line across consecutive ticks in the
        # scene JSON logs, which confuses human review and any downstream
        # analysis. The gated_agents list is preserved separately so the
        # frontend / debug tooling can still show "who was quiet this tick".
        gated_set = set(rec.get("gated_agents", []))
        minds = {}
        for aid, out in rec["agent_outputs"].items():
            if aid in gated_set:
                continue
            dump = out.model_dump()
            # Convert action_target Chinese name → agent_id
            dump["action_target"] = _name_to_id(dump.get("action_target"))
            minds[aid] = dump

        ticks.append({
            "tick": rec["tick"],
            "public": {
                "speech": speech,
                "actions": actions,
                "environmental_event": rec.get("environmental_event"),
                "exits": exits,
            },
            "minds": minds,
            "gated_agents": sorted(gated_set),
        })
    return ticks


class Orchestrator:
    def __init__(
        self,
        world: WorldStorage,
        seed: int | None = None,
    ):
        self.world = world
        self._cli_seed = seed
        self.profiles: dict[str, AgentProfile] = {}
        self.states: dict[str, AgentState] = {}
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)
        self._trajectory: DayTrajectory | None = None
        self._scene_files: list[Path] = []  # track scene files written this day
        self._exam_results: dict | None = None
        self._schedule = load_schedule()

    def _scene_file_path(self, day: int, scene: Scene) -> Path:
        time_prefix = scene.time.replace(":", "")  # "08:45" → "0845"
        return settings.logs_dir / f"day_{day:03d}" / f"{time_prefix}_{scene.name}.json"

    def _resolve_seed(self, progress: Progress) -> int:
        """Resolve seed: CLI flag > saved in progress > generate new."""
        if self._cli_seed is not None:
            return self._cli_seed
        if progress.seed is not None:
            return progress.seed
        return random.getrandbits(64)

    def _load_all_data(self) -> None:
        self.world.load_all_agents()
        self.profiles = {
            aid: s.load_profile() for aid, s in self.world.agents.items()
        }
        self.states = {
            aid: s.load_state() for aid, s in self.world.agents.items()
        }

    def _active_agent_ids(self) -> list[str]:
        return list(self.profiles.keys())

    def _run_exam(self, day: int, progress: Progress) -> None:
        logger.info("Running exam...")
        previous = load_previous_exam_results(day)
        results = generate_exam_results(self.profiles, self.states, self.rng, previous)
        apply_exam_effects(results, self.world, self.profiles, today=day)
        save_exam_results(results, day)

        # Reload states after apply_exam_effects wrote to disk
        self.states = {
            aid: self.world.get_agent(aid).load_state()
            for aid in self.profiles
        }

        # Teacher post-exam actions (counseling struggling students)
        if "he_min" in self.profiles:
            eq = self.world.load_event_queue()
            event_manager = EventQueueManager(eq, self.rng)
            ht = HomeroomTeacher(self.profiles["he_min"], self.rng)
            ht.post_exam_actions(results, event_manager, day)
            self.world.save_event_queue(event_manager.eq)

        progress.last_exam_day = day
        progress.next_exam_in_days = settings.exam_interval_days
        self._exam_results = results

    def _get_exam_context_for_agent(self, aid: str) -> str:
        if not self._exam_results:
            return ""
        profile = self.profiles.get(aid)
        if profile and profile.role != Role.STUDENT:
            return format_teacher_exam_context(self._exam_results)
        return format_exam_context(self._exam_results, aid)

    def _build_group_exam_context(self, agent_ids: list[str]) -> dict[str, str] | None:
        if not self._exam_results:
            return None
        return {aid: self._get_exam_context_for_agent(aid) for aid in agent_ids}

    async def run(self, start_day: int, end_day: int) -> None:
        progress = self.world.load_progress()

        # Resolve and persist seed for deterministic scene generation
        self._seed = self._resolve_seed(progress)
        self.rng = random.Random(self._seed)
        if progress.seed != self._seed:
            progress.seed = self._seed
            self._save_progress(progress)
        logger.info(f"Using seed: {self._seed}")

        for day in range(start_day, end_day + 1):
            if day < progress.current_day:
                continue

            logger.info(f"{'='*60}")
            logger.info(f"DAY {day}")
            logger.info(f"{'='*60}")

            progress.current_day = day
            self._load_all_data()
            self._scene_files = []
            self._exam_results = None

            # Run exam if countdown reached zero
            if progress.next_exam_in_days <= 0:
                self._run_exam(day, progress)
                self._save_progress(progress)

            # Only clear snapshots when starting a fresh day, not on resume
            if progress.day_phase == "daily_plan":
                self.world.clear_all_snapshots()

            # Save Day 0 initial state snapshot (idempotent — only if not exists)
            self._save_day0_snapshot_if_needed()

            # 1. Generate daily plans
            if progress.day_phase == "daily_plan":
                await self._run_daily_plans(day, progress)
                progress.day_phase = "scenes"
                self._save_progress(progress)

            # 2. Run scenes
            if progress.day_phase == "scenes":
                await self._run_scenes(day, progress)
                progress.day_phase = "compression"
                self._save_progress(progress)

            # 3. Nightly compression
            if progress.day_phase == "compression":
                await self._run_compression(day, progress)
                self._save_daily_snapshots(day)
                progress.day_phase = "complete"
                self._save_progress(progress)

            # 4. End of day
            self._end_of_day(day, progress)
            progress.current_day = day + 1
            progress.day_phase = "daily_plan"
            progress.total_days_simulated += 1
            progress.current_scene_index = 0
            progress.scenes = []
            self._save_progress(progress)

    async def _generate_self_narratives(self, day: int) -> None:
        logger.info("Generating self-narratives...")
        student_ids = self._active_agent_ids()

        async def _gen_narrative(aid: str) -> None:
            async with self.semaphore:
                storage = self.world.get_agent(aid)
                profile = self.profiles[aid]
                state = self.states[aid]
                # generate_self_narrative now returns SelfNarrativeResult and saves structured JSON
                await generate_self_narrative(storage, profile, state, day)

        await asyncio.gather(*[_gen_narrative(aid) for aid in student_ids])

    async def _run_daily_plans(self, day: int, progress: Progress) -> None:
        # Generate self-narratives periodically
        if day == 1 or day % settings.self_narrative_interval_days == 1:
            await self._generate_self_narratives(day)

        logger.info("Generating daily plans...")
        student_ids = self._active_agent_ids()
        free_period_configs = [c for c in self._schedule if c.is_free_period]

        async def _gen_plan(aid: str) -> None:
            async with self.semaphore:
                storage = self.world.get_agent(aid)
                profile = self.profiles[aid]
                state = self.states[aid]
                plan = await generate_daily_plan(
                    aid, storage, profile, state,
                    progress.next_exam_in_days, day,
                    all_profiles=self.profiles,
                    free_period_configs=free_period_configs,
                )
                state.daily_plan = plan
                state.day = day
                storage.save_state(state)

        await asyncio.gather(*[_gen_plan(aid) for aid in student_ids])

    async def _run_scenes(self, day: int, progress: Progress) -> None:
        # Initialize trajectory for this day
        self._trajectory = DayTrajectory(day=day)

        # Per-day deterministic RNG so scene list is stable across resume
        scene_rng = random.Random(hash((self._seed, "scenes", day)))
        gen = SceneGenerator(self.profiles, self.states, self._schedule, rng=scene_rng)
        scene_index = 0

        for config in self._schedule:
            # Reload states (may have changed from previous scene or re-planning)
            self.states = {
                aid: self.world.get_agent(aid).load_state()
                for aid in self.profiles
            }
            gen.states = self.states

            # Generate scene(s) for this config entry
            scenes = gen.generate_scenes_for_config(config, day, scene_index)
            if not scenes:
                continue

            # Run each sub-scene, collect affected agents for re-planning
            affected_agents: set[str] = set()
            for scene in scenes:
                if scene.scene_index < progress.current_scene_index:
                    scene_index = scene.scene_index + 1
                    continue
                scene_affected = await self._run_single_scene(day, scene, progress)
                affected_agents.update(scene_affected)
                scene_index = scene.scene_index + 1

            # After all sub-scenes for this config, check for re-planning
            if affected_agents:
                await self._maybe_replan_agents(
                    day, config, affected_agents, progress,
                )

    async def _run_single_scene(
        self, day: int, scene: Scene, progress: Progress,
    ) -> set[str]:
        logger.info(f"\n--- {scene.time} {scene.name} @ {scene.location} ---")

        # Get or create scene progress
        if scene.scene_index < len(progress.scenes):
            sp = progress.scenes[scene.scene_index]
        else:
            sp = SceneProgress(
                scene_index=scene.scene_index,
                scene_id=f"{scene.time}_{scene.name}",
            )
            progress.scenes.append(sp)

        # Skip completed scenes
        if sp.phase == "complete":
            return set()

        # Restore snapshot if scene was interrupted mid-interaction
        if sp.phase != "grouping":
            restored = self.world.restore_agents_from_snapshot(scene.scene_index)
            if restored:
                logger.info(f"  Restored snapshot for scene {scene.scene_index}, resetting to grouping")
                sp.phase = "grouping"
                sp.groups = []
                self._save_progress(progress)
            elif not scene.groups:
                logger.warning(f"  Scene {scene.scene_index} has no snapshot and no groups, resetting to grouping")
                sp.phase = "grouping"
                sp.groups = []
                self._save_progress(progress)

        # Reload states (may have changed from previous scene)
        self.states = {
            aid: self.world.get_agent(aid).load_state()
            for aid in self.profiles
        }

        # Update energy for this scene (use base name without @location)
        base_scene_name = scene.name.split("@")[0]
        for aid in scene.agent_ids:
            self.states[aid] = update_energy(self.states[aid], base_scene_name)

        # Record trajectory
        if self._trajectory:
            for aid in scene.agent_ids:
                slot = AgentSlot(
                    time=scene.time,
                    scene_name=scene.name,
                    location=scene.location,
                    emotion=self.states[aid].emotion.value,
                )
                if aid not in self._trajectory.agents:
                    self._trajectory.agents[aid] = []
                self._trajectory.agents[aid].append(slot)

        # a. Grouping
        if sp.phase == "grouping":
            rels = {
                aid: self.world.get_agent(aid).load_relationships()
                for aid in scene.agent_ids
            }
            groups = group_agents(
                scene.agent_ids, self.profiles, self.states,
                rels, scene, self.rng,
            )
            scene.groups = groups
            sp.groups = [
                GroupCompletion(group_index=g.group_id)
                for g in groups
            ]
            sp.phase = "interaction"
            self._save_progress(progress)
            self.world.snapshot_agents_for_scene(scene.scene_index, scene.agent_ids)

            for g in groups:
                names = [self.profiles[a].name for a in g.agent_ids]
                tag = "(solo)" if g.is_solo else ""
                logger.info(f"  Group {g.group_id}: {', '.join(names)} {tag}")

        # b. Interaction + scene-end + apply
        affected: set[str] = set()
        if sp.phase in ("interaction", "scene_end", "applying"):
            affected = await self._run_scene_groups(day, scene, sp, progress)
            sp.phase = "complete"
            progress.current_scene_index = scene.scene_index + 1
            self.world.clear_scene_snapshot(scene.scene_index)
            self._save_progress(progress)
        return affected

    async def _run_scene_groups(
        self, day: int, scene: Scene, sp: SceneProgress, progress: Progress,
    ) -> set[str]:
        eq = self.world.load_event_queue()
        event_manager = EventQueueManager(eq, self.rng)
        storages = {aid: self.world.get_agent(aid) for aid in scene.agent_ids}
        affected_agents: set[str] = set()
        groups_data: list[dict] = []

        for gc in sp.groups:
            if gc.status == "applied":
                continue

            group = scene.groups[gc.group_index] if gc.group_index < len(scene.groups) else None
            if not group:
                continue

            # Scoped scene copy with only this group's participants
            group_scene = scene.model_copy(update={
                "agent_ids": group.agent_ids,
                "teacher_present": scene.teacher_present or ("he_min" in group.agent_ids),
            })

            if group.is_solo:
                # Solo reflection
                aid = group.agent_ids[0]
                solo_exam_ctx = self._get_exam_context_for_agent(aid)
                reflection = await run_solo_reflection(
                    aid, storages[aid], self.profiles[aid], self.states[aid],
                    group_scene, self.profiles,
                    event_manager.get_known_events(aid),
                    progress.next_exam_in_days, day,
                    exam_context=solo_exam_ctx,
                )
                apply_solo_result(reflection, storages[aid], self.profiles[aid], group_scene, day)
                groups_data.append({
                    "group_index": gc.group_index,
                    "participants": group.agent_ids,
                    "is_solo": True,
                    "solo_reflection": {
                        "inner_thought": reflection.inner_thought,
                        "emotion": reflection.emotion.value,
                        "activity": reflection.activity,
                    },
                })
                gc.status = "applied"
                self._save_progress(progress)
                continue

            # Group dialogue
            if gc.status == "pending":
                known_events = {
                    aid: event_manager.get_active_events_for_group(group.agent_ids)
                    for aid in group.agent_ids
                }
                group_exam_ctx = self._build_group_exam_context(group.agent_ids)
                turn_records = await run_group_dialogue(
                    group.agent_ids, group_scene, storages, self.profiles,
                    self.states, known_events, progress.next_exam_in_days,
                    day, self.rng, self.semaphore,
                    exam_context=group_exam_ctx,
                    group_index=gc.group_index,
                )

                # Trivial scene fast path: skip narrative + reflection LLM calls.
                # Status jumps to "applied" (not "llm_done") so resume after a
                # crash never tries to re-run absent LLM outputs.
                if is_trivial_scene(turn_records):
                    apply_trivial_scene_result(
                        group.agent_ids, self.world, group_scene, day, self.profiles,
                    )
                    groups_data.append({
                        "group_index": gc.group_index,
                        "participants": group.agent_ids,
                        "ticks": serialize_tick_records(turn_records, self.profiles),
                        "narrative": None,
                        "reflections": {},
                        "trivial": True,
                    })
                    gc.status = "applied"
                    self._save_progress(progress)
                    continue

                gc.status = "llm_done"
                self._save_progress(progress)

                # Serialize tick records for frontend output
                serialized_ticks = serialize_tick_records(turn_records, self.profiles)

                # Narrative extraction + per-agent reflections (all concurrent)
                narrative_coro = run_scene_end_analysis(
                    turn_records, group.agent_ids, self.profiles,
                    group_scene, day, gc.group_index,
                )
                reflections_coro = run_all_reflections(
                    group.agent_ids, turn_records, storages,
                    self.profiles, self.states, group_scene,
                    day, gc.group_index, self.semaphore,
                )
                narrative, reflections = await asyncio.gather(
                    narrative_coro, reflections_coro,
                )

                # Apply results (serial to avoid concurrent writes)
                apply_scene_end_results(
                    narrative, reflections, self.world, group_scene,
                    group.agent_ids, day, gc.group_index,
                    self.profiles, event_manager,
                    tick_records=turn_records,
                )

                groups_data.append({
                    "group_index": gc.group_index,
                    "participants": group.agent_ids,
                    "ticks": serialized_ticks,
                    "narrative": narrative.model_dump(),
                    "reflections": {aid: refl.model_dump() for aid, refl in reflections.items()},
                })
                gc.status = "applied"
                self._save_progress(progress)

                # Detect affected agents for re-planning
                for aid, refl in reflections.items():
                    if refl.new_concerns:
                        affected_agents.add(aid)
                    if refl.emotion in EXTREME_EMOTIONS:
                        affected_agents.add(aid)
                    if any(abs(rc.favorability) >= 8 or abs(rc.trust) >= 8
                           for rc in refl.relationship_changes):
                        affected_agents.add(aid)

            elif gc.status == "llm_done":
                # Recovery: result file exists, just apply
                # For simplicity, re-run scene-end (idempotent apply)
                logger.warning(f"  Recovering group {gc.group_index} from llm_done state")
                gc.status = "applied"
                self._save_progress(progress)

        # Write complete scene file after all groups done
        if groups_data:
            participant_names = {aid: self.profiles[aid].name for aid in scene.agent_ids}
            scene_path = self._scene_file_path(day, scene)
            write_scene_file(scene_path, scene, participant_names, groups_data)
            self._scene_files.append(scene_path)

        # Save updated event queue
        self.world.save_event_queue(event_manager.eq)
        return affected_agents

    async def _maybe_replan_agents(
        self, day: int, current_config, affected_agents: set[str],
        progress: Progress,
    ) -> None:
        """Re-plan affected agents if next config is a free period."""
        # Find next config in schedule
        config_idx = self._schedule.index(current_config)
        if config_idx + 1 >= len(self._schedule):
            return
        next_config = self._schedule[config_idx + 1]
        if not next_config.is_free_period:
            return

        # Free period invariants enforced by SceneConfig validator
        next_pref_field = next_config.pref_field
        assert next_pref_field is not None
        available_locations = next_config.valid_locations

        # Build a brief scene summary from the current config
        scene_summary = f"{current_config.time} {current_config.name}刚结束"

        # Reload states
        self.states = {
            aid: self.world.get_agent(aid).load_state()
            for aid in self.profiles
        }

        async def _replan_one(aid: str) -> None:
            async with self.semaphore:
                storage = self.world.get_agent(aid)
                state = self.states[aid]
                await maybe_replan(
                    aid, storage, self.profiles[aid], state,
                    scene_summary, next_pref_field, available_locations, day,
                )

        student_affected = {
            aid for aid in affected_agents
            if aid in self.profiles and self.profiles[aid].role == Role.STUDENT
        }
        replan_tasks = [_replan_one(aid) for aid in student_affected]
        if replan_tasks:
            logger.info(f"  Re-planning {len(replan_tasks)} affected agents...")
            await asyncio.gather(*replan_tasks)

    async def _run_compression(self, day: int, progress: Progress) -> None:
        logger.info("\nRunning nightly compression...")
        student_ids = self._active_agent_ids()

        async def _compress(aid: str) -> None:
            async with self.semaphore:
                storage = self.world.get_agent(aid)
                profile = self.profiles[aid]
                await nightly_compress(storage, profile, day)

        await asyncio.gather(*[_compress(aid) for aid in student_ids])

    DAILY_SNAPSHOT_FILES = ("state.json", "relationships.json", "self_narrative.json")

    def _save_daily_snapshots(self, day: int) -> None:
        """Save per-agent state snapshots to logs/day_{N}/agent_snapshots/."""
        day_dir = settings.logs_dir / f"day_{day:03d}" / "agent_snapshots"
        for aid in self._active_agent_ids():
            agent_dir = self.world.agents_dir / aid
            dest = day_dir / aid
            dest.mkdir(parents=True, exist_ok=True)
            for fname in self.DAILY_SNAPSHOT_FILES:
                src = agent_dir / fname
                if src.exists():
                    shutil.copy2(src, dest / fname)
        logger.info(f"  Saved daily snapshots → logs/day_{day:03d}/agent_snapshots/")

    def _save_day0_snapshot_if_needed(self) -> None:
        """Save Day 0 initial state snapshot (pristine state before any simulation).
        Idempotent: only creates if day_000 doesn't exist yet."""
        day0_dir = settings.logs_dir / "day_000" / "agent_snapshots"
        if day0_dir.exists():
            return
        for aid in self._active_agent_ids():
            agent_dir = self.world.agents_dir / aid
            dest = day0_dir / aid
            dest.mkdir(parents=True, exist_ok=True)
            for fname in self.DAILY_SNAPSHOT_FILES:
                src = agent_dir / fname
                if src.exists():
                    shutil.copy2(src, dest / fname)
        logger.info("  Saved Day 0 initial state snapshot → logs/day_000/agent_snapshots/")

    def _end_of_day(self, day: int, progress: Progress) -> None:
        self.world.clear_all_snapshots()
        # Reset energy for sleep + decay concerns
        for aid in self._active_agent_ids():
            storage = self.world.get_agent(aid)
            state = storage.load_state()
            state = reset_energy_for_sleep(state)
            state = decay_concerns(state, day)
            state = maybe_decay_emotion(state, scenes_since_extreme=2, rng=self.rng)
            profile = self.profiles[aid]
            if profile.role == Role.STUDENT:
                days_since = (day - progress.last_exam_day) if progress.last_exam_day is not None else None
                state = update_academic_pressure(
                    state, profile.family_background.pressure_level,
                    progress.next_exam_in_days, days_since_exam=days_since,
                )
            storage.save_state(state)
            # Relationship regression (same loop, one load+save)
            rels = storage.load_relationships()
            rels = regress_relationships(rels)
            storage.save_relationships(rels)

        # Save trajectory + scenes index
        from ..agent.storage import atomic_write_json
        day_dir = settings.logs_dir / f"day_{day:03d}"
        day_dir.mkdir(parents=True, exist_ok=True)

        if self._trajectory:
            atomic_write_json(
                day_dir / "trajectory.json",
                self._trajectory.model_dump(),
            )
            self._trajectory = None

        # Build scenes.json from scene files written this day
        import json
        scenes_index = []
        for scene_path in sorted(self._scene_files):
            scene_data = json.loads(scene_path.read_text(encoding="utf-8"))
            s = scene_data["scene"]
            groups_summary = []
            for g in scene_data["groups"]:
                groups_summary.append({
                    "group_index": g["group_index"],
                    "participants": g["participants"],
                    "is_solo": g.get("is_solo", False),
                })
            scenes_index.append({
                "scene_index": s["scene_index"],
                "time": s["time"],
                "name": s["name"],
                "location": s["location"],
                "file": scene_path.name,
                "groups": groups_summary,
            })
        if scenes_index:
            atomic_write_json(day_dir / "scenes.json", scenes_index)

        # Expire old events
        eq = self.world.load_event_queue()
        event_manager = EventQueueManager(eq, self.rng)
        event_manager.expire_old_events(day, settings.event_expire_days)
        self.world.save_event_queue(event_manager.eq)

        # Exam countdown
        progress.next_exam_in_days -= 1
        progress.last_updated = datetime.now().isoformat()

        logger.info(f"\nDay {day} complete. Next exam in {progress.next_exam_in_days} days.")

    def _save_progress(self, progress: Progress) -> None:
        progress.last_updated = datetime.now().isoformat()
        self.world.save_progress(progress)
