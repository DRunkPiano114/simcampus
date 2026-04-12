import time
from collections import defaultdict
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field

from ..agent.storage import AgentStorage
from ..config import settings
from ..llm.client import structured_call
from ..llm.logger import log_llm_call
from ..llm.prompts import render
from ..agent.qualitative import intensity_label
from ..models.agent import ActiveConcern, AgentProfile, ConcernTopic, Role
from ..models.memory import KeyMemory


class CompressionMemoryCandidate(BaseModel):
    text: str
    emotion: str = ""
    importance: int = Field(default=5, ge=1, le=10)
    people: list[str] = Field(default_factory=list)
    location: str = ""
    topics: list[str] = Field(default_factory=list)


class CompressionConcernCandidate(BaseModel):
    text: str
    source_event: str = ""
    emotion: str = ""
    intensity: int = Field(default=5, ge=1, le=10)
    related_people: list[str] = Field(default_factory=list)
    positive: bool = False
    topic: ConcernTopic = "其他"


class CompressionResult(BaseModel):
    daily_summary: str
    daily_highlight: str = Field(default="", max_length=120)
    permanent_memories: list[CompressionMemoryCandidate] = Field(default_factory=list)
    new_concerns: list[CompressionConcernCandidate] = Field(default_factory=list)


DAILY_HIGHLIGHT_FALLBACK_POOL = [
    "今天没什么戏",
    "日常的一天",
    "该做的事都做了",
    "今天比较平常",
    "没什么值得多写的",
    "日子平静地过去了",
]


def _pick_fallback(day: int) -> str:
    return DAILY_HIGHLIGHT_FALLBACK_POOL[day % len(DAILY_HIGHLIGHT_FALLBACK_POOL)]


def _bigrams(text: str) -> set[str]:
    text = text.replace(" ", "").replace("\n", "")
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _extract_recent_highlights(recent_md: str, last_n: int = 3) -> list[str]:
    lines = [
        ln.strip().removeprefix("高光：").strip()
        for ln in recent_md.splitlines()
        if ln.strip().startswith("高光：")
    ]
    return lines[-last_n:]


def _validate_daily_highlight(
    highlight: str,
    today_md: str,
    recent_md: str,
    day: int,
) -> tuple[str, str]:
    """3-layer validation: length, grounding, cross-day similarity.
    Returns (final_highlight, source_tag)."""
    if not highlight or not highlight.strip():
        return _pick_fallback(day), "fallback:empty"
    if len(highlight) < 10:
        return _pick_fallback(day), "fallback:short"

    h_bg = _bigrams(highlight)
    t_bg = _bigrams(today_md)
    if not h_bg or not t_bg:
        return _pick_fallback(day), "fallback:ungrounded"
    grounding_ratio = len(h_bg & t_bg) / len(h_bg)
    if grounding_ratio < 0.3:
        logger.warning(
            f"  daily_highlight ungrounded (ratio={grounding_ratio:.0%}): "
            f"{highlight[:40]} -> fallback"
        )
        return _pick_fallback(day), "fallback:ungrounded"

    for prev in _extract_recent_highlights(recent_md, last_n=3):
        prev_bg = _bigrams(prev)
        if not prev_bg:
            continue
        sim = len(h_bg & prev_bg) / max(1, min(len(h_bg), len(prev_bg)))
        if sim > 0.5:
            logger.warning(
                f"  daily_highlight too similar to recent (sim={sim:.0%}): "
                f"{highlight[:40]} -> fallback"
            )
            return _pick_fallback(day), "fallback:repetitive"

    return highlight, "llm"


def cap_today_memories(
    storage: AgentStorage,
    day: int,
    profile_name: str = "",
) -> int:
    """Drop the lowest-importance memories from `day` until at most
    `settings.per_day_memory_cap` remain. Returns the number dropped."""
    km_file = storage.load_key_memories()
    today_memories = [m for m in km_file.memories if m.day == day]
    other_memories = [m for m in km_file.memories if m.day != day]
    if len(today_memories) <= settings.per_day_memory_cap:
        return 0
    today_sorted = sorted(today_memories, key=lambda m: -m.importance)
    top_n = today_sorted[:settings.per_day_memory_cap]
    dropped = len(today_memories) - len(top_n)
    km_file.memories = other_memories + top_n
    storage.write_key_memories(km_file)
    if profile_name:
        logger.info(
            f"  {profile_name}: capped today's key_memories "
            f"({len(today_memories)} → {len(top_n)}, dropped {dropped})"
        )
    return dropped


async def nightly_compress(
    storage: AgentStorage,
    profile: AgentProfile,
    day: int,
) -> None:
    today_content = storage.read_today_md()
    if not today_content.strip():
        logger.debug(f"  {profile.name}: nothing to compress")
        return

    # Build profile summary
    role_desc = "学生" if profile.role == Role.STUDENT else "班主任兼语文老师"
    parts = [
        f"姓名：{profile.name}",
        f"性格：{'、'.join(profile.personality)}",
    ]
    if profile.role == Role.STUDENT:
        parts.append(f"成绩：{profile.academics.overall_rank.value}")
        parts.append(f"目标：{profile.academics.target.value}")
    parts.append(f"家庭情况：{profile.family_background.situation}")
    if profile.backstory:
        parts.append(f"背景：{profile.backstory}")
    if profile.long_term_goals:
        parts.append(f"长期目标：{'；'.join(profile.long_term_goals)}")
    if profile.inner_conflicts:
        parts.append(f"内心矛盾：{'；'.join(profile.inner_conflicts)}")
    profile_summary = "\n".join(parts)

    # Load active concerns for context
    state = storage.load_state()
    active_concerns = [
        {**c.model_dump(), "intensity_label": intensity_label(c.intensity)}
        for c in state.active_concerns
    ]

    unfulfilled_intentions = [
        f"{i.goal}（{i.reason}）"
        for i in state.daily_plan.intentions
        if not i.fulfilled
    ]

    prompt = render(
        "nightly_compress.j2",
        role_description=role_desc,
        profile_summary=profile_summary,
        today_md_content=today_content,
        active_concerns=active_concerns,
        unfulfilled_intentions=unfulfilled_intentions,
    )

    messages = [{"role": "user", "content": prompt}]

    start = time.time()
    llm_result = await structured_call(
        CompressionResult,
        messages,
        temperature=settings.compression_temperature,
        max_tokens=settings.max_tokens_compression,
    )
    latency = (time.time() - start) * 1000
    result = llm_result.data

    log_llm_call(
        day=day,
        scene_name="compression",
        group_id=storage.agent_id,
        call_type="nightly_compress",
        input_messages=messages,
        output=result,
        tokens_prompt=llm_result.tokens_prompt,
        tokens_completion=llm_result.tokens_completion,
        cost_usd=llm_result.cost_usd,
        latency_ms=latency,
        temperature=settings.compression_temperature,
    )

    # Validate daily_highlight
    today_content_for_check = storage.read_today_md()
    recent_for_check = storage.read_recent_md()
    highlight, source_tag = _validate_daily_highlight(
        result.daily_highlight, today_content_for_check, recent_for_check, day,
    )
    logger.info(f"  {profile.name}: daily_highlight source={source_tag}")

    # Append daily summary + highlight to recent.md
    recent = storage.read_recent_md()
    day_entry = f"\n# Day {day}\n{result.daily_summary}\n高光：{highlight}\n"
    storage.write_recent_md(recent + day_entry)

    # Save permanent memories above the configured importance threshold.
    for mem in result.permanent_memories:
        if mem.importance >= settings.key_memory_write_threshold:
            km = KeyMemory(
                date=f"Day {day}",
                day=day,
                people=mem.people,
                location=mem.location,
                emotion=mem.emotion,
                importance=mem.importance,
                topics=mem.topics,
                text=mem.text,
            )
            storage.append_key_memory(km)

    # Deferred import — apply_results lives in the interaction layer.
    from ..interaction.apply_results import add_concern
    for cc in result.new_concerns:
        new_concern = ActiveConcern(
            text=cc.text, source_event=cc.source_event,
            source_scene="", source_day=day, emotion=cc.emotion,
            intensity=cc.intensity, related_people=cc.related_people,
            positive=cc.positive, topic=cc.topic,
        )
        add_concern(state, new_concern, today=day)
    storage.save_state(state)

    # Per-day top-N cap on key_memories. Both apply_scene_end_results and
    # nightly_compress feed key_memories above the importance threshold,
    # so a single busy day could otherwise blow out an agent's memory list.
    cap_today_memories(storage, day, profile_name=profile.name)

    # Consolidation pass (Fix 15): runs every N days, merges duplicate
    # memories and concerns. Wired here (not orchestrator level) to reuse
    # the same storage handle and ensure today's new memories are included.
    await maybe_run_consolidation(storage, profile, day)

    # Clear today.md
    storage.clear_today_md()

    logger.info(
        f"  {profile.name}: compressed → \"{result.daily_summary}\" "
        f"({len(result.permanent_memories)} permanent memories)"
    )


# --- Fix 15: Nightly state consolidation ---


class MergeGroup(BaseModel):
    cluster_kind: Literal["memory", "concern"]
    cluster_id: int
    source_indices: list[int]
    source_text_prefixes: list[str] = Field(default_factory=list)
    final_intensity_or_importance: int


class ConsolidationResult(BaseModel):
    merge_groups: list[MergeGroup] = Field(default_factory=list)


class _ClusterCandidate(BaseModel):
    topic: str
    people: list[str]
    entries: list[dict]  # raw dicts for template rendering


def _cluster_memories_by_people_and_topic(
    memories: list[KeyMemory],
) -> list[_ClusterCandidate]:
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for m in memories:
        people_key = tuple(sorted(m.people))
        topic_key = m.topics[0] if m.topics else "其他"
        buckets[(people_key, topic_key)].append(m.model_dump())
    return [
        _ClusterCandidate(topic=tk, people=list(pk), entries=ms)
        for (pk, tk), ms in buckets.items()
    ]


def _cluster_concerns_by_topic_and_people(
    concerns: list[ActiveConcern],
) -> list[_ClusterCandidate]:
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for c in concerns:
        people_key = tuple(sorted(c.related_people))
        buckets[(c.topic, people_key)].append(c.model_dump())
    return [
        _ClusterCandidate(topic=tk, people=list(pk), entries=cs)
        for (tk, pk), cs in buckets.items()
    ]


def _apply_consolidation(
    storage: AgentStorage,
    km_file,
    state,
    result: ConsolidationResult,
    today: int,
    memory_clusters: list[_ClusterCandidate],
    concern_clusters: list[_ClusterCandidate],
) -> None:
    memory_indices_to_remove: set[int] = set()
    concern_indices_to_remove: set[int] = set()

    for mg in result.merge_groups:
        if mg.cluster_kind == "memory":
            clusters = memory_clusters
        else:
            clusters = concern_clusters

        if mg.cluster_id < 1 or mg.cluster_id > len(clusters):
            logger.warning(f"  consolidation: invalid cluster_id {mg.cluster_id}, skipping")
            continue

        cluster = clusters[mg.cluster_id - 1]
        items = cluster.entries

        # Anchor validation: check source_text_prefixes match
        valid = True
        for i, idx in enumerate(mg.source_indices):
            if idx < 1 or idx > len(items):
                valid = False
                break
            if i < len(mg.source_text_prefixes):
                actual_prefix = items[idx - 1]["text"][:15]
                if mg.source_text_prefixes[i] != actual_prefix:
                    logger.warning(
                        f"  consolidation: prefix mismatch at idx {idx}: "
                        f"'{mg.source_text_prefixes[i]}' vs '{actual_prefix}', "
                        f"dropping merge group"
                    )
                    valid = False
                    break
        if not valid:
            continue

        if len(mg.source_indices) < 2:
            continue

        # Keep the earliest item, merge others into it
        sorted_indices = sorted(mg.source_indices)
        kept_idx = sorted_indices[0] - 1
        merged_indices = sorted_indices[1:]

        if mg.cluster_kind == "memory":
            # Find actual memory objects by matching text
            kept_text = items[kept_idx]["text"]
            kept_mem = None
            for mem in km_file.memories:
                if mem.text == kept_text:
                    kept_mem = mem
                    break
            if not kept_mem:
                continue

            for mi in merged_indices:
                merged_item = items[mi - 1]
                # Add to text_history
                if merged_item["text"] not in kept_mem.text_history:
                    kept_mem.text_history.append(merged_item["text"])
                    kept_mem.text_history = kept_mem.text_history[-3:]
                # Add source_days
                if merged_item.get("day") and merged_item["day"] not in kept_mem.source_days:
                    kept_mem.source_days.append(merged_item["day"])

            kept_mem.importance = mg.final_intensity_or_importance

            # Remove merged memories
            merged_texts = {items[mi - 1]["text"] for mi in merged_indices}
            km_file.memories = [
                m for m in km_file.memories if m.text not in merged_texts
            ]
        else:
            # Concerns
            kept_text = items[kept_idx]["text"]
            kept_concern = None
            for c in state.active_concerns:
                if c.text == kept_text:
                    kept_concern = c
                    break
            if not kept_concern:
                continue

            for mi in merged_indices:
                merged_item = items[mi - 1]
                if merged_item["text"] not in kept_concern.text_history:
                    kept_concern.text_history.append(merged_item["text"])
                    kept_concern.text_history = kept_concern.text_history[-3:]
                # Merge source_event
                if merged_item.get("source_event"):
                    if kept_concern.source_event:
                        merged_se = kept_concern.source_event + "；" + merged_item["source_event"]
                    else:
                        merged_se = merged_item["source_event"]
                    kept_concern.source_event = merged_se[-500:]

            kept_concern.intensity = mg.final_intensity_or_importance

            # Remove merged concerns
            merged_texts = {items[mi - 1]["text"] for mi in merged_indices}
            state.active_concerns = [
                c for c in state.active_concerns if c.text not in merged_texts
            ]

    storage.write_key_memories(km_file)
    storage.save_state(state)


async def maybe_run_consolidation(
    storage: AgentStorage,
    profile: AgentProfile,
    day: int,
) -> None:
    """Run every settings.consolidation_interval_days."""
    if day % settings.consolidation_interval_days != 0:
        return

    km_file = storage.load_key_memories()
    state = storage.load_state()
    recent_memories = [
        m for m in km_file.memories
        if day - m.day <= settings.consolidation_lookback_days
    ]

    memory_clusters = _cluster_memories_by_people_and_topic(recent_memories)
    concern_clusters = _cluster_concerns_by_topic_and_people(state.active_concerns)

    eligible = (
        any(len(c.entries) >= 2 for c in memory_clusters)
        or any(len(c.entries) >= 2 for c in concern_clusters)
    )
    if not eligible:
        return

    # Only send clusters with >= 2 items to LLM
    mc_for_llm = [c for c in memory_clusters if len(c.entries) >= 2]
    cc_for_llm = [c for c in concern_clusters if len(c.entries) >= 2]

    prompt = render(
        "state_consolidation.j2",
        profile_name=profile.name,
        lookback_days=settings.consolidation_lookback_days,
        memory_clusters=[c.model_dump() for c in mc_for_llm],
        concern_clusters=[c.model_dump() for c in cc_for_llm],
    )

    messages = [{"role": "user", "content": prompt}]
    start = time.time()
    llm_result = await structured_call(
        ConsolidationResult,
        messages,
        temperature=settings.consolidation_temperature,
        max_tokens=settings.max_tokens_consolidation,
    )
    latency = (time.time() - start) * 1000
    result = llm_result.data

    log_llm_call(
        day=day,
        scene_name="consolidation",
        group_id=storage.agent_id,
        call_type="state_consolidation",
        input_messages=messages,
        output=result,
        tokens_prompt=llm_result.tokens_prompt,
        tokens_completion=llm_result.tokens_completion,
        cost_usd=llm_result.cost_usd,
        latency_ms=latency,
        temperature=settings.consolidation_temperature,
    )

    _apply_consolidation(
        storage, km_file, state, result, today=day,
        memory_clusters=mc_for_llm,
        concern_clusters=cc_for_llm,
    )
    logger.info(
        f"  {profile.name}: consolidated "
        f"({len(result.merge_groups)} merges applied)"
    )
