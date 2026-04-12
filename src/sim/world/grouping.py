import random

from ..models.agent import AgentProfile, AgentState, Emotion, Role
from ..models.relationship import RelationshipFile
from ..models.scene import GroupAssignment, Scene

# Structural bonuses
LABEL_BONUS = {"室友": 20, "同桌": 15, "前后桌": 10, "同学": 0}


def _compute_affinity(
    a_id: str,
    b_id: str,
    profiles: dict[str, AgentProfile],
    relationships: dict[str, RelationshipFile],
    scene: Scene,
    rng: random.Random,
    states: dict[str, AgentState] | None = None,
) -> float:
    a_rels = relationships.get(a_id, RelationshipFile()).relationships
    b_rels = relationships.get(b_id, RelationshipFile()).relationships

    # Bidirectional favorability
    a_to_b = a_rels[b_id].favorability if b_id in a_rels else 0
    b_to_a = b_rels[a_id].favorability if a_id in b_rels else 0
    score = float(a_to_b + b_to_a)

    # Structural bonus from label
    label = a_rels[b_id].label if b_id in a_rels else "同学"
    score += LABEL_BONUS.get(label, 0)

    # Gender factor
    a_gender = profiles[a_id].gender
    b_gender = profiles[b_id].gender
    if scene.location == "宿舍":
        if a_gender == b_gender:
            score += 100
    else:
        if a_gender == b_gender:
            score += 5

    # Intention targeting bonus
    if states:
        for src_id, tgt_id in [(a_id, b_id), (b_id, a_id)]:
            st = states.get(src_id)
            if st:
                target_name = profiles[tgt_id].name
                for intent in st.daily_plan.intentions:
                    if not intent.fulfilled and intent.target == target_name:
                        score += 25
                        break

    # Random noise
    score += rng.uniform(-10, 10)
    return score


def _should_be_solo(
    agent_id: str,
    profile: AgentProfile,
    state: AgentState,
    relationships: dict[str, RelationshipFile],
    rng: random.Random,
) -> bool:
    if profile.role != Role.STUDENT:
        return False

    # Low energy → solo (Fix 18: threshold lowered from 25 to settings)
    from ..config import settings
    if state.energy < settings.solo_energy_threshold:
        return True

    # Introvert with no close relationships → 20% solo (Fix 18: from 50%)
    is_introvert = "内向" in profile.personality
    rels = relationships.get(agent_id, RelationshipFile()).relationships
    has_close = any(r.favorability >= 15 for r in rels.values())
    if is_introvert and not has_close:
        return rng.random() < 0.2

    # Sad + low energy → 30% solo (Fix 18: from 60%)
    if state.emotion == Emotion.SAD and state.energy < 50:
        return rng.random() < 0.3

    return False


def group_agents(
    agent_ids: list[str],
    profiles: dict[str, AgentProfile],
    states: dict[str, AgentState],
    relationships: dict[str, RelationshipFile],
    scene: Scene,
    rng: random.Random | None = None,
) -> list[GroupAssignment]:
    rng = rng or random.Random()

    # Separate solo agents
    social_ids: list[str] = []
    solo_ids: list[str] = []
    for aid in agent_ids:
        if _should_be_solo(aid, profiles[aid], states[aid], relationships, rng):
            solo_ids.append(aid)
        else:
            social_ids.append(aid)

    # Handle dorm scenes: group by dorm
    if scene.location == "宿舍":
        groups = _group_by_dorm(social_ids, profiles, scene, rng)
    else:
        groups = _greedy_cluster(social_ids, profiles, states, relationships, scene, rng)

    # Assign group IDs
    result: list[GroupAssignment] = []
    for i, group_members in enumerate(groups):
        result.append(GroupAssignment(group_id=i, agent_ids=group_members))

    # Add solo agents
    for aid in solo_ids:
        result.append(GroupAssignment(
            group_id=len(result), agent_ids=[aid], is_solo=True,
        ))

    return result


def _group_by_dorm(
    agent_ids: list[str],
    profiles: dict[str, AgentProfile],
    scene: Scene,
    rng: random.Random,
) -> list[list[str]]:
    from .scene_generator import DORM_MEMBERS

    groups: list[list[str]] = []
    for dorm_id, members in DORM_MEMBERS.items():
        dorm_group = [aid for aid in agent_ids if aid in members]
        if len(dorm_group) >= 2:
            groups.append(dorm_group)
        elif len(dorm_group) == 1:
            # Single person in dorm → solo (handled separately)
            pass
    return groups


def _greedy_cluster(
    agent_ids: list[str],
    profiles: dict[str, AgentProfile],
    states: dict[str, AgentState],
    relationships: dict[str, RelationshipFile],
    scene: Scene,
    rng: random.Random,
    max_group_size: int = 5,
) -> list[list[str]]:
    if len(agent_ids) <= 1:
        return [agent_ids] if agent_ids else []

    # Compute affinity pairs
    pairs: list[tuple[float, str, str]] = []
    for i, a in enumerate(agent_ids):
        for b in agent_ids[i + 1:]:
            aff = _compute_affinity(a, b, profiles, relationships, scene, rng, states=states)
            pairs.append((aff, a, b))
    pairs.sort(reverse=True)

    # Greedy clustering
    assigned: dict[str, int] = {}
    groups: list[list[str]] = []

    for _, a, b in pairs:
        a_group = assigned.get(a)
        b_group = assigned.get(b)

        if a_group is None and b_group is None:
            # New group
            gid = len(groups)
            groups.append([a, b])
            assigned[a] = gid
            assigned[b] = gid
        elif a_group is not None and b_group is None:
            if len(groups[a_group]) < max_group_size:
                groups[a_group].append(b)
                assigned[b] = a_group
        elif a_group is None and b_group is not None:
            if len(groups[b_group]) < max_group_size:
                groups[b_group].append(a)
                assigned[a] = b_group
        # Both assigned → skip (don't merge groups)

    # Assign remaining unassigned agents to closest group
    for aid in agent_ids:
        if aid not in assigned:
            if not groups:
                groups.append([aid])
                assigned[aid] = 0
            else:
                # Find best group
                best_group = 0
                best_aff = float("-inf")
                for gid, members in enumerate(groups):
                    if len(members) >= max_group_size:
                        continue
                    avg_aff = sum(
                        _compute_affinity(aid, m, profiles, relationships, scene, rng, states=states)
                        for m in members
                    ) / len(members)
                    if avg_aff > best_aff:
                        best_aff = avg_aff
                        best_group = gid
                groups[best_group].append(aid)
                assigned[aid] = best_group

    return groups
