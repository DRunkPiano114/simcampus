import random

from loguru import logger

from ..models.agent import AgentProfile
from .event_queue import EventQueueManager


class HomeroomTeacher:
    """Rule-driven homeroom teacher — generates exam-talk and patrol events
    without going through the per-agent PDA loop."""

    def __init__(self, profile: AgentProfile, rng: random.Random | None = None):
        self.profile = profile
        self.rng = rng or random.Random()

    def post_exam_actions(
        self,
        exam_results: dict,
        event_manager: EventQueueManager,
        day: int,
    ) -> list[str]:
        """Generate post-exam teacher actions (talks with struggling students)."""
        actions: list[str] = []

        for aid, result in exam_results.items():
            rank_change = result.get("rank_change", 0)
            if rank_change <= -3 and self.rng.random() < 0.7:
                name = result["name"]
                action = f"何老师找{name}谈话，因为排名下滑了{abs(rank_change)}名"
                actions.append(action)

                # Create event
                event_manager.add_event(
                    text=f"何老师找{name}谈话了（月考退步）",
                    category="teacher_talk",
                    source_scene="办公室",
                    source_day=day,
                    witnesses=[aid, "he_min"],
                    spread_probability=0.7,
                )

                logger.info(f"  Teacher talk: {name} (rank dropped {abs(rank_change)})")

        return actions

    def patrol_event(self, scene_name: str, day: int) -> dict | None:
        """Generate a random classroom intervention event."""
        if scene_name in ("晚自习", "早读"):
            if self.rng.random() < 0.3:
                events = [
                    ("何老师巡视时发现有人在聊天，严厉地看了一眼", "discipline"),
                    ("何老师在教室后面站了一会儿，大家都安静了", "patrol"),
                    ("何老师提醒大家要抓紧时间复习", "reminder"),
                ]
                text, category = self.rng.choice(events)
                return {"text": text, "category": category}

        if scene_name == "上课":
            events = [
                ("何老师突然点名提问", "classroom"),
                ("有人上课传纸条被何老师发现", "discipline"),
                ("何老师批评了一个走神的同学", "discipline"),
                ("何老师讲了个冷笑话，全班都笑了", "humor"),
            ]
            text, category = self.rng.choice(events)
            return {"text": text, "category": category}

        return None
