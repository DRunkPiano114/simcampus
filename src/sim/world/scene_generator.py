import json
import random
from collections import defaultdict

from ..config import settings
from ..models.agent import AgentProfile, AgentState, Role
from ..models.scene import GroupAssignment, Scene, SceneConfig, SceneDensity
from .schedule import load_schedule

# Dorm assignments
DORM_MEMBERS: dict[str, list[str]] = {
    "male_301": ["lin_zhaoyu", "jiang_haotian", "lu_siyuan", "shen_yifan"],
    "male_303": ["he_jiajun"],
    "female_302": ["tang_shihan", "cheng_yutong", "su_nianyao", "fang_yuchen"],
}

# Map config time -> LocationPreference field name
_TIME_TO_PREF_FIELD = {
    "08:45": "morning_break",
    "12:00": "lunch",
    "15:30": "afternoon_break",
}


class SceneGenerator:
    def __init__(
        self,
        profiles: dict[str, AgentProfile],
        states: dict[str, AgentState],
        rng: random.Random | None = None,
    ):
        self.profiles = profiles
        self.states = states
        self.rng = rng or random.Random()
        self.schedule = load_schedule()
        self._location_events = self._load_location_events()

    def _load_location_events(self) -> dict:
        path = settings.data_dir / "location_events.json"
        if path.exists():
            return json.loads(path.read_text("utf-8"))
        return {}

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

        # Teacher presence probability
        teacher_present = False
        teacher_action = None
        if config.name == "晚自习":
            teacher_present = self.rng.random() < 0.20
        elif config.name == "课间":
            teacher_present = self.rng.random() < 0.05

        if teacher_present:
            teacher_action = self.rng.choice([
                "在教室后面巡视",
                "在讲台上批改作业",
                "和某个同学谈话",
            ])

        # Inject random events for triggered LOW scenes
        injected_events: list[str] = []
        if config.density == SceneDensity.HIGH_LIGHT:
            event = self.rng.choice([
                "老师突然点名回答问题",
                "有人传纸条被发现",
                "后排有人睡着了被叫醒",
                "窗外突然下大雨",
                "隔壁班传来吵闹声",
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
        return [scene]

    def _generate_free_period_scenes(
        self, config: SceneConfig, day: int, start_index: int,
    ) -> list[Scene]:
        student_ids = [
            aid for aid, p in self.profiles.items() if p.role == Role.STUDENT
        ]

        # Determine which pref field to use
        pref_field = _TIME_TO_PREF_FIELD.get(config.time)
        if not pref_field:
            # Fallback: treat as normal scene
            return self._generate_normal_scene(config, day, start_index)

        # Determine valid locations for this slot
        if config.name == "午饭":
            valid_locations = set(settings.lunch_locations)
            default_location = "食堂"
        else:
            valid_locations = set(settings.free_period_locations)
            default_location = "教室"

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
