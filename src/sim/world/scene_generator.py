import json
import random
from collections import defaultdict, deque

from loguru import logger

from ..config import settings
from ..models.agent import AgentProfile, AgentState, Role
from ..models.scene import GroupAssignment, Scene, SceneConfig, SceneDensity

# Dorm assignments
DORM_MEMBERS: dict[str, list[str]] = {
    "male_301": ["lin_zhaoyu", "jiang_haotian", "lu_siyuan", "shen_yifan"],
    "male_303": ["he_jiajun"],
    "female_302": ["tang_shihan", "cheng_yutong", "su_nianyao", "fang_yuchen"],
}


class SceneGenerator:
    def __init__(
        self,
        profiles: dict[str, AgentProfile],
        states: dict[str, AgentState],
        schedule: list[SceneConfig],
        rng: random.Random | None = None,
    ):
        self.profiles = profiles
        self.states = states
        self.rng = rng or random.Random()
        self.schedule = schedule
        self._location_events = self._load_location_events()
        self._ambient_events = self._load_ambient_events()
        self._recent_ambient_events: dict[str, deque] = {}

    def _load_location_events(self) -> dict:
        path = settings.data_dir / "location_events.json"
        if path.exists():
            return json.loads(path.read_text("utf-8"))
        return {}

    def _load_ambient_events(self) -> dict[str, list[str]]:
        path = settings.ambient_events_file
        if path.exists():
            raw = json.loads(path.read_text("utf-8"))
            return {loc: data["events"] for loc, data in raw.items()}
        return {}

    def _maybe_inject_ambient_event(self, scene: Scene) -> None:
        """Inject a positive ambient event into scenes without an opening_event."""
        if scene.opening_event:
            return
        if self.rng.random() >= settings.ambient_event_probability:
            return
        full_pool = self._ambient_events.get(scene.location, [])
        if not full_pool:
            return
        maxlen = max(1, len(full_pool) - 2)
        if scene.location not in self._recent_ambient_events:
            self._recent_ambient_events[scene.location] = deque(maxlen=maxlen)
        recently_used = self._recent_ambient_events[scene.location]
        available = [e for e in full_pool if e not in recently_used]
        if not available:
            return
        chosen = self.rng.choice(available)
        scene.opening_event = chosen
        recently_used.append(chosen)
        logger.info(
            f"  Injected ambient event for {scene.name}@{scene.location}: "
            f"{chosen[:40]}"
        )

    def generate_scenes_for_config(
        self, config: SceneConfig, day: int, start_index: int,
    ) -> list[Scene]:
        if config.is_free_period:
            return self._generate_free_period_scenes(config, day, start_index)
        return self._generate_normal_scene(config, day, start_index)

    def _generate_normal_scene(
        self, config: SceneConfig, day: int, start_index: int,
    ) -> list[Scene]:
        # LOW density scenes: only trigger with probability
        if config.density == SceneDensity.LOW:
            if self.rng.random() > config.trigger_probability:
                return []
            config = config.model_copy(update={"density": SceneDensity.HIGH_LIGHT})

        agent_ids = self._get_present_agents(config)
        if not agent_ids:
            return []

        # Teacher joins probabilistically as a full agent
        teacher_present = False
        teacher_action = None
        if config.name == "晚自习":
            teacher_present = self.rng.random() < 0.20

        if teacher_present and "he_min" in self.profiles:
            agent_ids.append("he_min")
            teacher_action = None  # she's a real participant now

        # Teacher patrol events for non-participant teacher
        injected_events: list[str] = []
        if not teacher_present and config.name in ("晚自习", "早读", "上课"):
            if "he_min" in self.profiles:
                from .homeroom_teacher import HomeroomTeacher
                ht = HomeroomTeacher(self.profiles["he_min"], self.rng)
                # 晚自习/早读 have internal 30% gates; 上课 always returns so gate here
                if config.name == "上课":
                    if self.rng.random() < 0.3:
                        patrol = ht.patrol_event(config.name, day)
                    else:
                        patrol = None
                else:
                    patrol = ht.patrol_event(config.name, day)
                if patrol:
                    injected_events.append(patrol["text"])

        # Inject random events for triggered LOW scenes
        if config.density == SceneDensity.HIGH_LIGHT:
            event = self.rng.choice([
                # 负面/冲突
                "老师突然点名回答问题",
                "有人传纸条被发现",
                "后排有人睡着了被叫醒",
                # 中性
                "窗外突然下大雨",
                "隔壁班传来吵闹声",
                "广播站放了一首很好听的歌",
                # 正面
                "老师表扬了上次作业写得好的同学",
                "有人带了零食偷偷分给周围的人",
                "课代表发了新的练习卷，大家一边抱怨一边翻看",
                "窗外出了太阳，教室里一下子亮堂起来",
            ])
            injected_events.append(event)

        opening_event = ""
        if config.opening_events:
            opening_event = self.rng.choice(config.opening_events)

        scene = Scene(
            scene_index=start_index,
            day=day,
            time=config.time,
            name=config.name,
            location=config.location,
            density=config.density,
            max_rounds=config.max_rounds,
            description=config.description,
            agent_ids=agent_ids,
            groups=[],
            injected_events=injected_events,
            teacher_present=teacher_present,
            teacher_action=teacher_action,
            opening_event=opening_event,
        )
        self._maybe_inject_ambient_event(scene)
        return [scene]

    def _generate_free_period_scenes(
        self, config: SceneConfig, day: int, start_index: int,
    ) -> list[Scene]:
        student_ids = [
            aid for aid, p in self.profiles.items() if p.role == Role.STUDENT
        ]

        # Invariants enforced by SceneConfig validator: pref_field, valid_locations,
        # and a default `location` that lives inside valid_locations are all guaranteed.
        pref_field = config.pref_field
        assert pref_field is not None
        valid_locations = set(config.valid_locations)
        default_location = config.location

        # Group students by their chosen location
        location_groups: dict[str, list[str]] = defaultdict(list)
        for aid in student_ids:
            state = self.states.get(aid)
            if state and state.daily_plan:
                prefs = state.daily_plan.location_preferences
                loc = getattr(prefs, pref_field, default_location)
                if loc not in valid_locations:
                    loc = default_location
            else:
                loc = default_location
            location_groups[loc].append(aid)

        # Teacher occasionally appears during free periods. Probability is keyed
        # on scene name (not data-driven via SceneConfig like valid_locations)
        # because this is narrator-side behavior, not agent-facing slot data —
        # students can't see or influence it, so it stays in code.
        if "he_min" in self.profiles:
            teacher_prob = 0.30 if config.name == "午饭" else 0.10
            if self.rng.random() < teacher_prob:
                location_groups[default_location].append("he_min")

        # Create one Scene per occupied location
        scenes: list[Scene] = []
        scene_idx = start_index
        for location, aids in sorted(location_groups.items()):
            if not aids:
                continue

            # Pick opening event from location_events.json
            opening_event = ""
            loc_events = self._location_events.get(location, {})
            scene_name_key = config.name  # "课间" or "午饭"
            if scene_name_key in loc_events:
                opening_event = self.rng.choice(loc_events[scene_name_key])

            scene = Scene(
                scene_index=scene_idx,
                day=day,
                time=config.time,
                name=f"{config.name}@{location}",
                location=location,
                density=config.density,
                max_rounds=config.max_rounds,
                description=config.description,
                agent_ids=aids,
                groups=[],
                injected_events=[],
                teacher_present=False,
                teacher_action=None,
                opening_event=opening_event,
            )
            self._maybe_inject_ambient_event(scene)
            scenes.append(scene)
            scene_idx += 1

        return scenes

    def _get_present_agents(self, config: SceneConfig) -> list[str]:
        student_ids = [
            aid for aid, p in self.profiles.items() if p.role == Role.STUDENT
        ]

        if config.location == "宿舍":
            result: list[str] = []
            for dorm_id, members in DORM_MEMBERS.items():
                dorm_students = [m for m in members if m in student_ids]
                if len(dorm_students) >= 2:
                    result.extend(dorm_students)
            return result
        else:
            return student_ids

    # Legacy method for compatibility
    def generate_day(self, day: int) -> list[Scene]:
        scenes: list[Scene] = []
        scene_index = 0
        for config in self.schedule:
            new_scenes = self.generate_scenes_for_config(config, day, scene_index)
            scenes.extend(new_scenes)
            scene_index += len(new_scenes) if new_scenes else 0
        return scenes
