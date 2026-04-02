import random

from ..models.agent import AgentProfile, Role
from ..models.scene import GroupAssignment, Scene, SceneConfig, SceneDensity
from .schedule import load_schedule

# Dorm assignments
DORM_MEMBERS: dict[str, list[str]] = {
    "male_301": ["li_ming", "zhang_qiang", "liu_yang", "wu_lei"],
    "male_303": ["sun_hao"],
    "female_302": ["wang_hong", "chen_xue", "zhao_wei", "zhou_ting"],
}


class SceneGenerator:
    def __init__(self, profiles: dict[str, AgentProfile], rng: random.Random | None = None):
        self.profiles = profiles
        self.rng = rng or random.Random()
        self.schedule = load_schedule()

    def generate_day(self, day: int) -> list[Scene]:
        scenes: list[Scene] = []
        scene_index = 0

        for config in self.schedule:
            # LOW density scenes: only trigger with probability
            if config.density == SceneDensity.LOW:
                if self.rng.random() > config.trigger_probability:
                    continue
                # Triggered LOW becomes HIGH-like with a classroom event
                config = config.model_copy(update={"density": SceneDensity.HIGH_LIGHT})

            # Determine who's present based on location
            agent_ids = self._get_present_agents(config)
            if not agent_ids:
                continue

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

            # Pick a random opening event for PDA tick loop
            opening_event = ""
            if config.opening_events:
                opening_event = self.rng.choice(config.opening_events)

            scene = Scene(
                scene_index=scene_index,
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
            scenes.append(scene)
            scene_index += 1

        return scenes

    def _get_present_agents(self, config: SceneConfig) -> list[str]:
        student_ids = [
            aid for aid, p in self.profiles.items() if p.role == Role.STUDENT
        ]

        if config.location == "宿舍":
            # Only same-dorm members
            result: list[str] = []
            for dorm_id, members in DORM_MEMBERS.items():
                dorm_students = [m for m in members if m in student_ids]
                if len(dorm_students) >= 2:
                    result.extend(dorm_students)
            return result
        else:
            # Classroom/cafeteria: all students
            return student_ids
