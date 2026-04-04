from ..models.agent import AgentProfile, AgentState, Emotion, Role
from ..models.event import Event
from ..models.memory import KeyMemory
from ..models.relationship import Relationship, RelationshipFile
from ..models.scene import Scene
from ..memory.retrieval import get_relevant_memories
from .storage import AgentStorage


def _profile_summary(profile: AgentProfile) -> str:
    parts = [
        f"姓名：{profile.name}",
        f"性别：{'男' if profile.gender.value == 'male' else '女'}",
        f"性格：{'、'.join(profile.personality)}",
        f"说话风格：{profile.speaking_style}",
    ]
    if profile.role == Role.STUDENT:
        parts.append(f"成绩：{profile.academics.overall_rank.value}")
        if profile.academics.strengths:
            parts.append(f"擅长科目：{'、'.join(profile.academics.strengths)}")
        if profile.academics.weaknesses:
            parts.append(f"弱势科目：{'、'.join(profile.academics.weaknesses)}")
        parts.append(f"学习态度：{profile.academics.study_attitude}")
        parts.append(f"作业习惯：{profile.academics.homework_habit}")
        parts.append(f"目标：{profile.academics.target.value}")
        if profile.position:
            parts.append(f"职务：{profile.position}")
    parts.append(f"家庭期望：{profile.family_background.expectation}")
    parts.append(f"家庭情况：{profile.family_background.situation}")
    if profile.long_term_goals:
        parts.append(f"长期目标：{'；'.join(profile.long_term_goals)}")
    parts.append(f"背景：{profile.backstory}")
    return "\n".join(parts)


def _filter_relationships(
    rels: RelationshipFile,
    present_ids: list[str],
) -> list[Relationship]:
    return [r for r in rels.relationships.values() if r.target_id in present_ids]


def _scene_info(scene: Scene, profiles: dict[str, AgentProfile]) -> dict:
    present_names = [profiles[aid].name for aid in scene.agent_ids if aid in profiles]
    return {
        "time": scene.time,
        "location": scene.location,
        "name": scene.name,
        "description": scene.description,
        "present_names": present_names,
    }


def prepare_context(
    storage: AgentStorage,
    profile: AgentProfile,
    state: AgentState,
    scene: Scene,
    all_profiles: dict[str, AgentProfile],
    known_events: list[Event],
    next_exam_in_days: int,
    max_key_memories: int = 10,
    exam_context: str = "",
    # PDA tick loop params
    latest_event: str = "",
    scene_transcript: str = "",
    private_history: list[str] | None = None,
    emotion_override: Emotion | None = None,
) -> dict:
    rels = storage.load_relationships()
    today_events = storage.read_today_md()
    recent_summary = storage.read_recent_md_last_n_days(3)
    key_memories = get_relevant_memories(
        storage.load_key_memories(),
        scene,
        all_profiles,
        max_k=max_key_memories,
    )

    pending_intentions = [
        i for i in state.daily_plan.intentions if not i.fulfilled
    ]

    role_desc = "学生" if profile.role == Role.STUDENT else "班主任兼语文老师"

    effective_emotion = emotion_override if emotion_override else state.emotion

    return {
        "role_description": role_desc,
        "profile_summary": _profile_summary(profile),
        "relationships": _filter_relationships(rels, scene.agent_ids),
        "today_events": today_events,
        "recent_summary": recent_summary,
        "key_memories": key_memories,
        "pending_intentions": pending_intentions,
        "scene_info": _scene_info(scene, all_profiles),
        "known_events": known_events,
        "next_exam_in_days": next_exam_in_days,
        "teacher_present": scene.teacher_present,
        "current_state": state,
        "exam_context": exam_context,
        # PDA tick loop
        "latest_event": latest_event,
        "scene_transcript": scene_transcript,
        "private_history": private_history or [],
        "tick_emotion": effective_emotion.value,
        # Concerns + self-narrative
        "active_concerns": [c for c in state.active_concerns],
        "self_narrative": storage.read_self_narrative(),
    }
