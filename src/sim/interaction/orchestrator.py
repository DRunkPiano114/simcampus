import asyncio
import random
import time
from datetime import datetime

from loguru import logger

from ..agent.daily_plan import generate_daily_plan
from ..agent.replan import maybe_replan
from ..agent.self_narrative import generate_self_narrative
from ..agent.state_update import (
    EXTREME_EMOTIONS,
    decay_concerns,
    reset_energy_for_sleep,
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
from .apply_results import apply_scene_end_results, apply_solo_result
from .scene_end import run_scene_end_analysis
from .solo import run_solo_reflection
from .turn import run_group_dialogue


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

    def _student_ids(self) -> list[str]:
        return [
            aid for aid, p in self.profiles.items()
            if p.role == Role.STUDENT
        ]

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

            # Only clear snapshots when starting a fresh day, not on resume
            if progress.day_phase == "daily_plan":
                self.world.clear_all_snapshots()

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
        student_ids = self._student_ids()

        async def _gen_narrative(aid: str) -> None:
            async with self.semaphore:
                storage = self.world.get_agent(aid)
                profile = self.profiles[aid]
                state = self.states[aid]
                await generate_self_narrative(storage, profile, state, day)

        await asyncio.gather(*[_gen_narrative(aid) for aid in student_ids])

    async def _run_daily_plans(self, day: int, progress: Progress) -> None:
        # Generate self-narratives periodically
        if day == 1 or day % settings.self_narrative_interval_days == 1:
            await self._generate_self_narratives(day)

        logger.info("Generating daily plans...")
        student_ids = self._student_ids()

        async def _gen_plan(aid: str) -> None:
            async with self.semaphore:
                storage = self.world.get_agent(aid)
                profile = self.profiles[aid]
                state = self.states[aid]
                plan = await generate_daily_plan(
                    aid, storage, profile, state,
                    progress.next_exam_in_days, day,
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
        gen = SceneGenerator(self.profiles, self.states, scene_rng)
        schedule = gen.schedule
        scene_index = 0

        for config in schedule:
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
                    day, config, schedule, affected_agents, progress,
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

        for gc in sp.groups:
            if gc.status == "applied":
                continue

            group = scene.groups[gc.group_index] if gc.group_index < len(scene.groups) else None
            if not group:
                continue

            if group.is_solo:
                # Solo reflection
                aid = group.agent_ids[0]
                reflection = await run_solo_reflection(
                    aid, storages[aid], self.profiles[aid], self.states[aid],
                    scene, self.profiles,
                    event_manager.get_known_events(aid),
                    progress.next_exam_in_days, day,
                )
                apply_solo_result(reflection, storages[aid], self.profiles[aid], scene, day)
                gc.status = "applied"
                self._save_progress(progress)
                continue

            # Group dialogue
            if gc.status == "pending":
                known_events = {
                    aid: event_manager.get_active_events_for_group(group.agent_ids)
                    for aid in group.agent_ids
                }
                turn_records = await run_group_dialogue(
                    group.agent_ids, scene, storages, self.profiles,
                    self.states, known_events, progress.next_exam_in_days,
                    day, self.rng, self.semaphore,
                )
                gc.status = "llm_done"
                self._save_progress(progress)

                # Scene-end analysis
                agent_concerns = {
                    self.profiles[aid].name: [c for c in self.states[aid].active_concerns]
                    for aid in group.agent_ids
                }
                analysis = await run_scene_end_analysis(
                    turn_records, group.agent_ids, self.profiles,
                    scene, day, gc.group_index,
                    agent_concerns=agent_concerns,
                )

                # Apply results (serial to avoid concurrent writes)
                apply_scene_end_results(
                    analysis, self.world, scene, group.agent_ids,
                    day, gc.group_index, self.profiles, event_manager,
                )
                gc.status = "applied"
                self._save_progress(progress)

                # Detect affected agents for re-planning
                name_to_id = {self.profiles[a].name: a for a in group.agent_ids}
                # New concerns generated
                for cc in analysis.new_concerns:
                    aid = name_to_id.get(cc.agent)
                    if aid:
                        affected_agents.add(aid)
                # Extreme emotion changes
                for agent_name, emo_str in analysis.final_emotions.items():
                    aid = name_to_id.get(agent_name)
                    if aid:
                        try:
                            from ..models.agent import Emotion
                            emo = Emotion(emo_str)
                            if emo in EXTREME_EMOTIONS:
                                affected_agents.add(aid)
                        except ValueError:
                            pass
                # Large relationship changes (|delta| >= 8)
                for rc in analysis.relationship_changes:
                    aid = name_to_id.get(rc.from_agent)
                    if aid and (abs(rc.favorability) >= 8 or abs(rc.trust) >= 8):
                        affected_agents.add(aid)

            elif gc.status == "llm_done":
                # Recovery: result file exists, just apply
                # For simplicity, re-run scene-end (idempotent apply)
                logger.warning(f"  Recovering group {gc.group_index} from llm_done state")
                gc.status = "applied"
                self._save_progress(progress)

        # Save updated event queue
        self.world.save_event_queue(event_manager.eq)
        return affected_agents

    async def _maybe_replan_agents(
        self, day: int, current_config, schedule: list, affected_agents: set[str],
        progress: Progress,
    ) -> None:
        """Re-plan affected agents if next config is a free period."""
        # Find next config in schedule
        config_idx = schedule.index(current_config)
        if config_idx + 1 >= len(schedule):
            return
        next_config = schedule[config_idx + 1]
        if not next_config.is_free_period:
            return

        # Determine which pref field and available locations for next slot
        from ..world.scene_generator import _TIME_TO_PREF_FIELD
        next_pref_field = _TIME_TO_PREF_FIELD.get(next_config.time)
        if not next_pref_field:
            return

        if next_config.name == "午饭":
            available_locations = settings.lunch_locations
        else:
            available_locations = settings.free_period_locations

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

        replan_tasks = [_replan_one(aid) for aid in affected_agents if aid in self.profiles]
        if replan_tasks:
            logger.info(f"  Re-planning {len(replan_tasks)} affected agents...")
            await asyncio.gather(*replan_tasks)

    async def _run_compression(self, day: int, progress: Progress) -> None:
        logger.info("\nRunning nightly compression...")
        student_ids = self._student_ids()

        async def _compress(aid: str) -> None:
            async with self.semaphore:
                storage = self.world.get_agent(aid)
                profile = self.profiles[aid]
                await nightly_compress(storage, profile, day)

        await asyncio.gather(*[_compress(aid) for aid in student_ids])

    def _end_of_day(self, day: int, progress: Progress) -> None:
        self.world.clear_all_snapshots()
        # Reset energy for sleep + decay concerns
        for aid in self._student_ids():
            storage = self.world.get_agent(aid)
            state = storage.load_state()
            state = reset_energy_for_sleep(state)
            state = decay_concerns(state)
            storage.save_state(state)

        # Save trajectory
        if self._trajectory:
            from ..agent.storage import atomic_write_json
            traj_dir = settings.logs_dir / f"day_{day:03d}"
            traj_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                traj_dir / "trajectory.json",
                self._trajectory.model_dump(),
            )
            self._trajectory = None

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
