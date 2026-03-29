import random

from ..models.agent import AgentProfile, AgentState, Emotion

# Personality-based base speaking desire
EXTROVERT_KEYWORDS = {"外向", "活泼", "话多", "幽默", "热心", "直爽"}
INTROVERT_KEYWORDS = {"内向", "安静", "沉默"}

# Emotions that boost or reduce speaking desire
BOOST_EMOTIONS = {Emotion.ANGRY, Emotion.EXCITED, Emotion.CURIOUS}
SUPPRESS_EMOTIONS = {Emotion.SAD, Emotion.EMBARRASSED, Emotion.GUILTY}


def _base_desire(profile: AgentProfile) -> float:
    personality_set = set(profile.personality)
    if personality_set & EXTROVERT_KEYWORDS:
        return 8.0
    if personality_set & INTROVERT_KEYWORDS:
        return 3.0
    return 5.0


def compute_speaking_desire(
    agent_id: str,
    profile: AgentProfile,
    state: AgentState,
    was_addressed: bool,
    has_pending_intention: bool,
    silent_rounds: int,
    teacher_present: bool,
    rng: random.Random,
) -> float:
    desire = _base_desire(profile)

    # Addressed bonus
    if was_addressed:
        desire += 10.0

    # Pending intention bonus
    if has_pending_intention:
        desire += 3.0

    # Silent rounds bonus (cap at 8)
    desire += min(silent_rounds * 1.5, 8.0)

    # Recent speaker penalty — break ping-pong patterns
    if silent_rounds <= 1:
        desire -= 3.0

    # Emotion modifier
    if state.emotion in BOOST_EMOTIONS:
        desire += 3.0
    elif state.emotion in SUPPRESS_EMOTIONS:
        desire -= 3.0

    # Energy modifier
    desire += (state.energy - 50) / 25.0

    # Teacher suppression
    if teacher_present:
        desire *= 0.6

    # Random noise
    desire += rng.uniform(-2, 2)

    return desire


def pick_first_speaker(
    agent_ids: list[str],
    profiles: dict[str, AgentProfile],
    states: dict[str, AgentState],
    rng: random.Random,
) -> str:
    scores: list[tuple[float, str]] = []
    for aid in agent_ids:
        score = _base_desire(profiles[aid])
        # Intention bonus
        if states[aid].daily_plan.intentions:
            score += 3.0
        score += rng.uniform(-3, 3)
        scores.append((score, aid))
    scores.sort(reverse=True)
    return scores[0][1]


def pick_next_speaker(
    agent_ids: list[str],
    profiles: dict[str, AgentProfile],
    states: dict[str, AgentState],
    last_speaker: str,
    last_directed_to: str | None,
    silent_counts: dict[str, int],
    teacher_present: bool,
    rng: random.Random,
) -> str:
    candidates = [aid for aid in agent_ids if aid != last_speaker]
    if not candidates:
        return last_speaker

    best_score = float("-inf")
    best_agent = candidates[0]

    for aid in candidates:
        was_addressed = (
            last_directed_to is not None
            and profiles[aid].name == last_directed_to
        )
        has_intention = any(
            not i.fulfilled for i in states[aid].daily_plan.intentions
        )
        desire = compute_speaking_desire(
            aid, profiles[aid], states[aid],
            was_addressed, has_intention,
            silent_counts.get(aid, 0),
            teacher_present, rng,
        )
        if desire > best_score:
            best_score = desire
            best_agent = aid

    return best_agent
