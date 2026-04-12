import json
import random
from pathlib import Path

from loguru import logger

from ..agent.storage import WorldStorage, atomic_write_json
from ..config import settings
from ..models.agent import AgentProfile, AgentState, Emotion, OverallRank, PressureLevel

SUBJECTS = ["语文", "数学", "英语", "物理", "化学", "生物"]

RANK_TO_BASE: dict[OverallRank, int] = {
    OverallRank.TOP: 88,
    OverallRank.UPPER: 78,
    OverallRank.UPPER_MIDDLE: 70,
    OverallRank.MIDDLE: 62,
    OverallRank.LOWER_MIDDLE: 54,
    OverallRank.LOWER: 45,
}

RANK_TO_VARIANCE: dict[OverallRank, float] = {
    OverallRank.TOP: 3.0,
    OverallRank.UPPER: 5.0,
    OverallRank.UPPER_MIDDLE: 6.0,
    OverallRank.MIDDLE: 8.0,
    OverallRank.LOWER_MIDDLE: 9.0,
    OverallRank.LOWER: 10.0,
}

ATTITUDE_COEFF = {
    "极其刻苦": 1.2,
    "极度自律": 1.2,
    "很努力": 1.0,
    "认真踏实": 0.9,
    "认真但不拼命": 0.7,
    "上课认真但课后容易分心": 0.5,
    "上课偶尔走神": 0.3,
    "上课经常走神": 0.1,
    "上课听不懂就发呆": 0.0,
}


def _get_attitude_coeff(attitude: str) -> float:
    for key, val in ATTITUDE_COEFF.items():
        if key in attitude:
            return val
    return 0.5


def generate_exam_results(
    profiles: dict[str, AgentProfile],
    states: dict[str, AgentState],
    rng: random.Random,
    previous_results: dict | None = None,
) -> dict:
    results: dict[str, dict] = {}

    for aid, profile in profiles.items():
        if profile.role.value != "student":
            continue

        state = states.get(aid, AgentState())
        base = RANK_TO_BASE.get(profile.academics.overall_rank, 60)
        variance = RANK_TO_VARIANCE.get(profile.academics.overall_rank, 8.0)
        attitude_coeff = _get_attitude_coeff(profile.academics.study_attitude)

        scores: dict[str, int] = {}
        total = 0
        for subject in SUBJECTS:
            subject_mod = 0
            if subject in profile.academics.strengths:
                subject_mod = 5
            elif subject in profile.academics.weaknesses:
                subject_mod = -5

            effort_mod = (state.academic_pressure / 100) * attitude_coeff * 5
            raw = base + subject_mod + effort_mod + rng.gauss(0, variance)
            score = max(0, min(100, round(raw)))
            scores[subject] = score
            total += score

        results[aid] = {
            "name": profile.name,
            "scores": scores,
            "total": total,
        }

    # Rank by total
    sorted_ids = sorted(results.keys(), key=lambda x: results[x]["total"], reverse=True)
    for rank, aid in enumerate(sorted_ids, 1):
        results[aid]["rank"] = rank

    # Compute rank change
    if previous_results:
        for aid in results:
            prev_rank = previous_results.get(aid, {}).get("rank")
            if prev_rank is not None:
                results[aid]["rank_change"] = prev_rank - results[aid]["rank"]
            else:
                results[aid]["rank_change"] = 0
    else:
        for aid in results:
            results[aid]["rank_change"] = 0

    return results


def apply_exam_effects(
    results: dict,
    world: WorldStorage,
    profiles: dict[str, AgentProfile],
    today: int,
) -> None:
    """Apply post-exam effects: academic_pressure, emotion, energy, and a
    high-intensity 学业焦虑 concern when rank_change <= -3.

    `today` is used as the new concern's last_reinforced_day so it doesn't
    immediately look stale to decay_concerns.
    """
    # Deferred import — apply_results lives in the interaction layer and
    # importing it at module load would create a world ↔ interaction cycle.
    from ..interaction.apply_results import add_concern
    from ..models.agent import ActiveConcern

    for aid, result in results.items():
        if aid not in profiles:
            continue

        storage = world.get_agent(aid)
        state = storage.load_state()
        profile = profiles[aid]

        rank_change = result.get("rank_change", 0)

        if rank_change < 0:
            exam_shock = abs(rank_change) * 2
            state.academic_pressure = min(100, state.academic_pressure + exam_shock)

        # Significant rank drop → high-intensity concern, bypassing the
        # reflection-originated cap so the shock lands at 8-10.
        if rank_change <= -3:
            magnitude = abs(rank_change)
            intensity = min(10, 5 + magnitude)  # 8 / 9 / 10 ladder
            shock = ActiveConcern(
                text=f"月考退步{magnitude}名，担心被甩开",
                source_event=f"月考排名下滑{magnitude}名",
                source_scene="月考",
                source_day=today,
                emotion="sad",
                intensity=intensity,
                related_people=[],
                positive=False,
                topic="学业焦虑",
            )
            add_concern(state, shock, today=today, skip_cap=True)

        # Emotion effects
        if rank_change >= 5:
            state.emotion = Emotion.EXCITED
        elif rank_change <= -5:
            state.emotion = Emotion.SAD
        elif (
            profile.family_background.pressure_level == PressureLevel.HIGH
            and result["rank"] > 5
        ):
            state.emotion = Emotion.ANXIOUS

        # Energy drain from exam
        state.energy = max(0, state.energy - 15)

        storage.save_state(state)

    logger.info(f"Applied exam effects for {len(results)} students")


def save_exam_results(results: dict, day: int) -> None:
    exam_dir = settings.world_dir / "exam_results"
    exam_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(exam_dir / f"day_{day:03d}.json", results)
    logger.info(f"Saved exam results for day {day}")


def load_previous_exam_results(day: int) -> dict | None:
    exam_dir = settings.world_dir / "exam_results"
    # Find most recent exam before this day
    results_files = sorted(exam_dir.glob("day_*.json"))
    for f in reversed(results_files):
        f_day = int(f.stem.split("_")[1])
        if f_day < day:
            return json.loads(f.read_text("utf-8"))
    return None


def format_teacher_exam_context(results: dict) -> str:
    if not results:
        return ""

    sorted_students = sorted(results.values(), key=lambda r: r["rank"])
    total_students = len(sorted_students)
    class_avg = sum(r["total"] for r in sorted_students) / total_students

    lines = [f"本次月考全班概况（共{total_students}人）："]
    lines.append(f"班级平均总分：{class_avg:.0f}")

    # Top 3
    lines.append("前三名：" + "、".join(
        f"{r['name']}（{r['total']}分）" for r in sorted_students[:3]
    ))

    # Struggling students (rank drop >= 3)
    struggling = [r for r in sorted_students if r.get("rank_change", 0) <= -3]
    if struggling:
        lines.append("退步明显的学生：" + "、".join(
            f"{r['name']}（退{abs(r['rank_change'])}名）" for r in struggling
        ))

    # Big improvers
    improved = [r for r in sorted_students if r.get("rank_change", 0) >= 3]
    if improved:
        lines.append("进步明显的学生：" + "、".join(
            f"{r['name']}（进{r['rank_change']}名）" for r in improved
        ))

    return "\n".join(lines)


def format_exam_context(results: dict, agent_id: str) -> str:
    if agent_id not in results:
        return ""

    r = results[agent_id]
    lines = [f"你的月考成绩：总分 {r['total']}，排名 第{r['rank']}名"]
    if r["rank_change"] > 0:
        lines.append(f"（进步了{r['rank_change']}名！）")
    elif r["rank_change"] < 0:
        lines.append(f"（退步了{abs(r['rank_change'])}名...）")

    scores = r["scores"]
    lines.append("各科成绩：" + "、".join(f"{s}{v}分" for s, v in scores.items()))
    return "\n".join(lines)
