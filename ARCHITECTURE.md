# Architecture & Technical Reference

Multi-agent simulation of a Chinese high school class set at **上海市建宁中学** (a fictional Shanghai 市重点 high school). Each agent (student/teacher) is an LLM-powered character that interacts through structured daily scenes, generating emergent narratives. Pure observation mode — no user intervention, text output only. The goal is to explore whether multi-agent LLM simulation can produce agents that behave like real people — with authentic personalities, evolving relationships, and believable decision-making across three years of high school life.

**Tech stack**: Python 3.12+, DeepSeek V3.2 via LiteLLM + Instructor (structured JSON output), Pydantic (data models + validation), Jinja2 (prompt templates), Loguru (logging), asyncio (concurrency), FastAPI + uvicorn (interactive chat API), SSE (streaming). All state stored as JSON + Markdown files — no database.

**Scale**: 10 students + 1 teacher (homeroom teacher). All character data, prompts, and narrative output are in Chinese.

---

## Architecture Overview

Five-layer design plus an API layer, all source code in `src/sim/`:

```
┌──────────────────────────────────────────────────────────┐
│  API Layer  (api/)                                        │
│  FastAPI server, God Mode + Role Play chat endpoints,     │
│  time-travel context assembly, SSE streaming              │
├──────────────────────────────────────────────────────────┤
│  Interaction Layer  (interaction/)                        │
│  Orchestrator, dialogue turns, tick resolution,          │
│  scene-end analysis, result application, solo reflection │
├──────────────────────────────────────────────────────────┤
│  Agent Layer  (agent/)                                   │
│  Profile/state storage, context assembly,                │
│  daily plan generation, state update formulas,           │
│  self-narrative generation, location re-planning         │
├──────────────────────────────────────────────────────────┤
│  World Layer  (world/)                                   │
│  Schedule, scene generation (location-split free         │
│  periods), agent grouping, event queue, exam system,     │
│  homeroom teacher                                        │
├──────────────────────────────────────────────────────────┤
│  LLM Layer  (llm/)                                       │
│  Instructor+LiteLLM client, streaming text calls,        │
│  Jinja2 prompt rendering, per-call JSON logging          │
├──────────────────────────────────────────────────────────┤
│  Memory Layer  (memory/)                                 │
│  Nightly compression, relevance-based retrieval,         │
│  memory writer helpers                                   │
├──────────────────────────────────────────────────────────┤
│  Models  (models/)                                       │
│  Pydantic data models for all domain objects             │
└──────────────────────────────────────────────────────────┘
```

---

## Daily Simulation Loop (Orchestrator)

`interaction/orchestrator.py` → `Orchestrator` class. Entry point: `Orchestrator.run(start_day, end_day)`.

Each simulated day runs through four sequential phases (plus an exam trigger before Phase 1):

### Phase 0.5: Exam Trigger (conditional)

Before daily plans, if `progress.next_exam_in_days <= 0`, the exam fires via `Orchestrator._run_exam()`:

1. Load previous exam results (most recent `world/exam_results/day_NNN.json`) for rank comparison
2. Generate exam scores (see Exam Score Generation below)
3. Apply exam effects — emotion changes + energy drain + pressure shock, written directly to disk
4. Reload all agent states from disk (to pick up the effects)
5. Teacher post-exam actions: `HomeroomTeacher.post_exam_actions()` creates gossip events for students who dropped ≥3 ranks (70% per student), injected via `EventQueueManager`
6. Set `progress.last_exam_day = day`, reset `progress.next_exam_in_days = exam_interval_days`
7. Store results in `self._exam_results` — used later to inject per-agent `exam_context` into scenes

**Per-agent exam context**: during scene execution, each student gets their own `format_exam_context()` string (personal scores + rank + rank change). The teacher (`he_min`) gets `format_teacher_exam_context()` — a class-level overview (top 3, struggling students, class average, notable improvers). The `exam_context` is passed as a `dict[str, str]` to `run_group_dialogue()` (keyed by agent_id) and as a plain `str` to `run_solo_reflection()`.

### Phase 0: Self-Narrative Generation (periodic)

On day 1 and every `self_narrative_interval_days` (default 3) days:
- For each agent (concurrently), call LLM with `self_narrative.j2` template
- Input: profile summary (including backstory), recent 3-day summary, active concerns, relationships with qualitative labels, previous `self_concept` and `current_tensions` (for continuity)
- Output: `SelfNarrativeResult` — structured model with three fields:
  - `narrative`: 100-200 word first-person self-reflection
  - `self_concept`: up to 4 bullets ("我是一个 ___ 的人"), slow-changing (prompt instructs: change at most 1 bullet per update unless major event)
  - `current_tensions`: up to 3 bullets, what the agent is struggling with this week (can change fully each update)
- Saved to `agents/<id>/self_narrative.json` (canonical) + `self_narrative.md` (human-readable mirror). Legacy md-only data is auto-migrated on read.
- `self_concept` + `current_tensions` are injected into daily_plan, self_reflection, and solo_reflection templates. `perception_static.j2` only gets `current_tensions` (kept lean since it runs per-tick).
- `inner_conflicts` (from profile, immutable) displayed as "你内心的永恒矛盾" vs `current_tensions` displayed as "你最近在和这些搏斗" — both coexist, representing permanent personality traits vs transient struggles.

### Phase 1: Daily Plan Generation (`day_phase = "daily_plan"`)

For each agent (concurrently, up to `max_concurrent_llm_calls`):
1. Load relationships (with qualitative labels), last 3 days of `recent.md`, yesterday's intentions (full lifecycle state), active concerns (with intensity labels), structured self-narrative (narrative + self_concept + current_tensions), and inner conflicts
2. Call LLM with `daily_plan.j2` template → returns `DailyPlan` (1-3 `Intention` objects + `mood_forecast` + `location_preferences`). The prompt shows yesterday's intentions with fulfillment status and instructs the agent to link each new intention to a concern via `satisfies_concern`. For students, the prompt nudges reflection on unmet needs. For the teacher, it nudges teacher-specific priorities. Qualitative labels replace raw numbers (energy/pressure shown as descriptive text, not "73/100").
3. Validate location preferences against valid lists (invalid → default)
4. **Carry-forward**: after LLM returns, each new intention is fuzzy-matched against yesterday's intentions (same target + goal substring overlap, skipping abandoned). Matched intentions inherit `origin_day` and increment `pursued_days`. Unmatched intentions get `origin_day=today, pursued_days=1`.
5. **Audit log**: warnings for high-intensity (>=6) addressable concerns with no matching intention
6. Save updated state with new plan

`Intention` has: `target` (optional agent name), `goal`, `reason`, `fulfilled` (bool), `abandoned` (bool), `satisfies_concern` (first 15 chars of linked concern text, or null), `origin_day` (first day this intention appeared), `pursued_days` (consecutive days in plan).

`LocationPreference` has: `morning_break` (课间 08:45), `lunch` (午饭 12:00), `afternoon_break` (课间 15:30). Each field's allowed values come from the corresponding free-period entry's `valid_locations` in `schedule.json`. The daily plan template renders the per-slot option list dynamically from the orchestrator's cached schedule, and `daily_plan.py` validates the LLM's output against each slot's `valid_locations` (falling back to the slot's `location` default if invalid).

### Phase 2: Scene Execution (`day_phase = "scenes"`)

For each scene in `data/schedule.json` (sequentially):

**Step 2a — Scene Generation** (`world/scene_generator.py`):

Scene generation is now **lazy per-config**: the orchestrator iterates over `schedule.json` entries and generates scene(s) for each config, reloading agent states between configs (to reflect re-planning changes).

For **normal scenes** (`is_free_period=false`):
- LOW density scenes roll against `trigger_probability` (default 15%). If they don't trigger, they're skipped entirely. If they trigger, density is upgraded to HIGH_LIGHT and a random classroom event is injected (balanced across negative/neutral/positive events).
- Teacher participation: 20% chance during 晚自习 — when the roll succeeds, He Min joins as a full LLM-driven agent participant (not just a `teacher_present` flag). Teacher does not appear in 课间 normal scenes (课间 is a free period, handled separately).
- **Teacher patrol events**: when the teacher is NOT a full participant and the scene is 晚自习/早读/上课, a patrol event may be injected via `HomeroomTeacher.patrol_event()`. 晚自习/早读 have a 30% internal probability gate; 上课 always returns an event so a 30% gate is applied in the scene generator. Patrol events (e.g. "何老师巡视时发现有人在聊天") appear in the scene's `injected_events`.
- Present agents determined by location: 宿舍 → only dorm members; elsewhere → all students.

For **group interaction**, each group gets a scoped scene copy (`group_scene`) with `agent_ids` set to only that group's members. This ensures dorm scenes show correct participant lists (boys-only / girls-only) and the `teacher_present` flag is set correctly per-group (`scene.teacher_present OR "he_min" in group.agent_ids`).

For **free period scenes** (`is_free_period=true` — 课间 08:45, 午饭 12:00, 课间 15:30):
1. Read `pref_field` from the `SceneConfig` (declared in `schedule.json`) — maps the slot to the corresponding `LocationPreference` field (`morning_break`, `lunch`, or `afternoon_break`).
2. Group students by their chosen location from daily plan; if a student's preference falls outside `config.valid_locations`, fall back to `config.location` (the slot's default).
3. Teacher occasionally appears during free periods: 30% at 午饭, 10% at 课间. When she appears, she joins the slot's `default_location` (= `config.location`) group as a full agent participant.
4. Create one Scene per occupied location with location-specific opening events from `data/location_events.json`
5. Scene name becomes `f"{config.name}@{location}"` (e.g. "课间@走廊", "午饭@食堂")
6. Sequential scene indices assigned starting from current index

Available locations come from `schedule.json:valid_locations` per slot — currently 课间 → 教室/走廊/操场/小卖部/图书馆/天台; 午饭 → 食堂/教室/操场/小卖部. Editing the JSON is the only place to change these.

**Step 2a.1 — Re-planning** (between configs):
After all sub-scenes for a config complete, if the next config is a free period, "affected" agents may re-plan their location. An agent is affected if ANY of (checked from their individual `AgentReflection`):
- Their reflection produced any `new_concerns`
- Their reflection emotion is an extreme emotion (ANGRY, EXCITED, SAD, EMBARRASSED, JEALOUS, GUILTY, FRUSTRATED, TOUCHED)
- Any of their `relationship_changes` has |favorability| >= 8 or |trust| >= 8

Re-plan uses `replan.j2` template → `ReplanResult` (changed, new_location, reason). The next slot's `pref_field` and `valid_locations` are read directly from its `SceneConfig`. If changed, updates `location_preferences` for the next slot. Only students are re-planned (teacher is excluded — she has no location preferences).

**Step 2b — Grouping** (`world/grouping.py`):
- First, identify solo agents: non-students (teacher) are never solo. For students: energy < 25, or introvert without close relationships at 50% chance, or sad + low energy at 60% chance.
- For 宿舍 scenes: group by dorm assignment.
- For other scenes: greedy affinity clustering (max group size 5). Affinity = bidirectional favorability + structural label bonus (室友 +20, 同桌 +15, 前后桌 +10) + same-gender bonus (+5, or +100 in dorms) + intention targeting bonus (+25 if either agent has an unfulfilled intention targeting the other by name) + random noise ±10.

**Deterministic scene generation**: Scene generation uses a per-day deterministic RNG seeded with `hash((base_seed, "scenes", day))`, separate from the main simulation RNG. This ensures the same set of LOW density scenes trigger on resume as on the original run, keeping `scene_index` values stable.

**Snapshot**: After grouping completes, mutable agent files (`state.json`, `relationships.json`, `key_memories.json`, `today.md`) are snapshotted to `world/snapshots/scene_N/<agent_id>/`. If the simulation is interrupted during the interaction phase and later resumed, the orchestrator detects the incomplete scene, restores agent files from the snapshot (reverting any partially-applied changes), resets the scene to the grouping phase, and re-runs it from scratch. A `.complete` marker ensures partially-written snapshots are discarded. Snapshots are cleared after each scene completes and at day boundaries (only when starting a fresh day, not on resume).

**Step 2c — Group Interaction: PDA Tick Loop** (`interaction/turn.py`):

Each tick, ALL agents in the group perceive the latest event, decide what to do, and a resolution step handles simultaneous actions. This replaces the old turn-based speaker selection system.

Tick loop (`run_group_dialogue`):
```
for tick in range(scene.max_rounds):  # per-scene cap from schedule.json
    1. GATE: for each non-queued active agent, decide if fresh perception is needed
       Trigger rules (any one → perceive):
       a. Tick 0 (no previous output to reuse)
       b. Agent was directly targeted by last resolved speech
       c. Agent's name appears in latest_event text
       d. Environmental event occurred this tick (disruptive action)
       e. A concern-related person is mentioned in latest_event
       f. 4-tick cadence: agent hasn't perceived in 4+ ticks
       If no trigger: reuse last PerceptionOutput with action_type=OBSERVE,
       urgency decremented by 1, no emotion_history append (prevents fake drift).
       These agents are tracked as "gated" this tick so their stale reused
       observation/inner_thought can be filtered out of downstream artefacts
       (see RECORD step 4 + `gated_agents` handling below).
    2. PERCEIVE: gated-in agents concurrently (semaphore-throttled)
       - Build per-agent context via prepare_context() with PDA params
       - LLM returns PerceptionOutput
    3. RESOLVE: resolve_tick() determines what happens (see PDA Tick Resolution)
    4. RECORD: store tick_record with all agent outputs + resolved actions +
       `gated_agents: list[str]` listing agents that reused last perception
       this tick (used by narrative/serialize layers to suppress stale copies)
    5. UPDATE: latest_event for next tick from resolved actions
    6. CHECK: scene ends if consecutive_quiet >= 4 and tick_count >= 3
```

- Tick 0 starts with `scene.opening_event` as the latest event (randomly selected from `schedule.json:opening_events` per scene config)
- **Scene `max_rounds` selection** (Fix 8A): long-form scenes are deliberately bounded to prevent open-ended drift into "literary cliché" emotional spirals. Current values: 课间 = 12 (was 20), 午饭 = 20 (was 25), 宿舍夜聊 = 22 (was 35); 早读/上课/晚自习 stay at 8. The remaining ceiling beyond what the scene actually consumes is absorbed by the natural-end check (`consecutive_quiet >= 4 AND tick_count >= 3`). `tests/test_schedule.py:test_schedule_max_rounds_sane` enforces upper-bound caps so future edits cannot regress.
- Queued agents (losers from previous tick's speaker resolution) skip the PERCEIVE step and reuse their previous PerceptionOutput with +3 urgency per tick queued
- **Perception gating** reduces LLM calls by 30-60% for silent background agents. Gating state (`last_perception`, `last_perceive_tick`) is local to `run_group_dialogue` scope — rebuilt from scratch on crash recovery (deterministic with same seed). Solo groups (`_run_single_scene` → `run_solo_reflection`) are not affected by gating.
- Narrative formatting (`interaction/narrative.py`):
  - `format_public_transcript()`: public events visible to all (speech, actions, exits). Mid-scene summarization after 12 ticks: ticks 1-6 are collapsed into a one-line summary
  - `format_agent_transcript()`: public view + agent's own prior observations and inner thoughts as private history. **Gated-tick suppression**: when the focal agent appears in `tick_record["gated_agents"]`, that tick contributes NOTHING to their private history — the observation/inner_thought there is a verbatim reuse of an earlier fresh perception and re-rendering it produces duplicate lines that pollute downstream reflection prompts. Other agents' perspective on the same tick is unaffected.
  - `format_latest_event()`: one-line summary of what just happened, used as the "latest event" for next tick's perception prompt

**Step 2c (solo)** — `interaction/solo.py`: If a group has `is_solo=true`, run `solo_reflection.j2` instead → returns `SoloReflection` with `inner_thought`, `emotion`, `activity`.

**Trivial scene fast path** (Fix 3): immediately after `run_group_dialogue` returns, the orchestrator calls `is_trivial_scene(turn_records)` to detect "nothing happened" scenes (empty turn_records, no speech AND no environmental_event in any tick, or ≤2 ticks of pure observe / non-disruptive non_verbal). When true, `apply_trivial_scene_result` writes a placeholder `（场景没有特别发生什么）` line to each agent's `today.md` and the orchestrator skips both narrative extraction and per-agent self-reflection LLM calls. The group is marked `gc.status = "applied"` directly (skipping the `llm_done` intermediate state) so a crash recovery never tries to re-run absent LLM outputs. The trivial fast path does NOT touch `state.emotion`, `active_concerns`, `key_memories`, or relationships — emotion decay is independently driven by `_end_of_day` (overnight semantics), so trivial scenes do not need to advance any per-scene counter.

**Step 2d — Narrative Extraction + Per-Agent Self-Reflection** (two-phase post-dialogue):

After the dialogue ends, two types of LLM calls run **concurrently**:

**Phase 1: Narrative Extraction** (`interaction/scene_end.py`) — 1 LLM call:
- Build conversation log from tick_records using `format_public_transcript()` (includes speech, non-verbal actions, exits). Inner thoughts and observations are NOT included — extraction only sees externally observable behavior.
- `long_conversation` threshold: 12 ticks
- Feed the conversation log to LLM with `scene_end_analysis.j2` (analytical temperature 0.3) as a purely objective recorder
- Returns `NarrativeExtraction`:
  - `key_moments`: list of significant events as one-line summaries (objectivity constraint: no 刻意 / 似乎 / 暗中 推测词)
  - `fulfilled_intentions`: list of "name:intention" strings
  - `events_discussed`: event IDs that were actually mentioned (updates `known_by`)
  - `new_events`: gossip/conflicts/decisions that may spread to other scenes — each carries a `cite_ticks: list[int]` (1-indexed `[Tick N]` numbers from the conversation log) used by Fix 13's grounding validation in `apply_scene_end_results`

**Phase 2: Per-Agent Self-Reflection** (`interaction/self_reflection.py`) — N concurrent LLM calls:
- For each agent in the group, build an agent-specific prompt with:
  - Full agent context (profile, relationships, memories, concerns, self-narrative) via `prepare_context()`
  - Agent-specific conversation log via `format_agent_transcript()`
- Render `self_reflection.j2` template (reflection temperature 0.7)
- Each agent independently evaluates the conversation from their own perspective
- Returns `AgentReflection` per agent:
  - `emotion`: Emotion enum — agent's post-dialogue emotional state
  - `relationship_changes`: list of `AgentRelChange` (to_agent, favorability/trust/understanding deltas) — no from_agent needed since the reflection belongs to the focal agent
  - `memories`: list of `AgentMemoryCandidate` (text, emotion, importance, people, location, topics) — no agent field needed
  - `new_concerns`: list of `AgentConcernCandidate` — persistent emotional preoccupations from the agent's perspective (can be positive or negative, flagged via `positive` field)
  - `concern_updates`: list of `AgentConcernUpdate` — intensity adjustments to the agent's existing concerns
  - `intention_outcomes`: list of `IntentionOutcome` — agent self-evaluates each pending intention from the dialogue (status: fulfilled/attempted/frustrated/abandoned/pending, brief_reason). This replaces the old `narrative.fulfilled_intentions` substring matching which had 0% hit rate.
- Error handling: if an individual agent's reflection fails (LLM error, timeout), a default `AgentReflection()` is used (NEUTRAL emotion, no changes) so one failure doesn't block the group

This two-phase design enables **asymmetric perception**: the same conversation can produce different emotions, relationship changes, and memories for each participant, based on their personality, history, and existing concerns.

**Step 2e — Apply Results** (`interaction/apply_results.py`):
- For each agent in the group (using their individual `AgentReflection`):
  - Update emotion directly from reflection (Emotion enum, no try/except needed)
  - Append key moments from shared `NarrativeExtraction` to `today.md` (formatted as `## time scene @ location`)
  - Save key memories with importance >= `settings.key_memory_write_threshold` (=3, Fix 14: lowered from 7) from agent's own reflection to `key_memories.json`
  - Apply relationship deltas from agent's own reflection using baseline snapshot (for idempotency): `new_value = baseline + delta`, clamped to valid range. **Auto-insertion** (Fix 4): if the change targets an in-profiles agent that has no entry in this agent's `relationships.json` yet, a zero-state `Relationship` is created on the fly and the delta is applied on top. The `label` is picked from **both** source and target roles: HOMEROOM_TEACHER → student auto-inserts as `"学生"`, any agent → HOMEROOM_TEACHER as `"老师"`, otherwise `"同学"`. (Prior bug: label was picked from target role only, so a teacher auto-inserting a student fell through to `"同学"`.) Hallucinated names that don't resolve to any profile are dropped with a warning. Previously, missing targets were silently dropped — leading to permanently empty relationship maps for low-interaction agents.
  - **recent_interactions log**: whenever any relationship_change has a non-zero delta, append the tag `"Day {day} {mark}{scene.name}"` to `rel.recent_interactions`, where `mark` is a one-character valence prefix derived from the signed `favorability + trust` delta of that row: `+` for net-positive (warm interaction), `−` (U+2212) for net-negative (friction), `·` (U+00B7) for net-zero but still interacting (e.g. understanding-only change where fav/trust cancel). Understanding is excluded from the valence sum because it measures "how well I know them", not affect. Dedup is keyed on the full tag (day + mark + scene name), so two rows with the same sign in the same scene collapse but a mixed scene where one row is `+` and another is `−` legitimately records both events — rare but possible across multi-target or multi-tick reflections. The list is capped at `settings.max_recent_interactions` (default 10, FIFO eviction). Downstream prompts (`perception_static.j2`, `self_reflection.j2`, etc.) render the log as an interaction timeline so the LLM can distinguish "Day 3 +课间@走廊" (warm) from "Day 4 −宿舍夜聊" (friction) at a glance without having to re-infer valence from the current absolute relationship scores. Lays the groundwork for Phase 2+ relationship-strength signals.
  - **Mark intention outcomes** from agent's own `intention_outcomes` (replaces old `narrative.fulfilled_intentions` substring matching):
    - `fulfilled` → mark intent as fulfilled; if `satisfies_concern` is set, decay linked concern intensity by 2
    - `frustrated` → if `satisfies_concern` is set, intensify linked concern by 1
    - `abandoned` → mark intent as abandoned (excluded from carry-forward)
    - Matching uses bidirectional substring (`concern_match` helper)
  - Apply new concerns from agent's own reflection via `add_concern` (Fix 2 — topic-based dedup). Propagates `positive` flag and the chosen `topic` from `AgentConcernCandidate`. See **Concern Topic Bucketing & Dedup**.
  - Apply concern intensity adjustments from agent's own reflection (substring matching on concern text). Remove concerns that reach intensity <= 0.
- Update event queue from shared `NarrativeExtraction`: mark discussed events as known by all group members; **for new events, run Fix 13's 3-layer cite_ticks grounding** before saving.

**Fix 13 — `new_events` grounding** (`apply_results.py`): each `NewEventCandidate` carries `cite_ticks: list[int]` (1-indexed `[Tick N]` numbers as the LLM saw them). Before adding to the event queue, three layers run:

1. **Layer 1 (non-empty)**: drop if `cite_ticks` is empty.
2. **Layer 2 (existence + summarized exclusion)**: build `valid_ticks = {tick + 1: tick_record}` to align with the `[Tick N]` 1-indexed display in `narrative.py:54/:104`. When `len(tick_records) > 12`, exclude ticks 0–5 (0-indexed) since `format_public_transcript` collapses them into one summary line and the LLM cannot have legitimately quoted their content. Drop if any cited tick is outside `valid_ticks`.
3. **Layer 3 (bigram overlap)**: compute Chinese-character bigrams of `event.text` and the concatenated raw content of all cited ticks (`_extract_tick_content` pulls speech / actions / environmental_event). The primary signal is `event_ratio = |overlap| / |event_bigrams|`; the threshold is 0.3. Using the event side as denominator means longer / more elaborated event text must overlap more — catching the "expansion" failure mode where the LLM cites one short tick but writes a long elaborated description. The log also reports `min_ratio = |overlap| / min(|event|, |cited|)` for tuning.

Events that pass all three layers are persisted via `event_manager.add_event(...)` with `cite_ticks` and `group_index` carried through onto the `Event` model itself (Fix 13 follow-up). Persisting both fields means M1 sanity check can validate ground-truth against `event_queue.json` without re-running the LLM; the `group_index` is essential because cite_ticks are group-local — different groups in the same scene have independent tick numbering, and earlier audits that unioned visible ticks across groups would false-pass cross-group cites. System-generated events (e.g. `HomeroomTeacher.post_exam_actions`) leave `group_index=None` and are excluded from the M1 audit.

The orchestrator now passes `tick_records=turn_records` into `apply_scene_end_results` so the validator has access to the raw conversation. Drops are logged with the prefix `[scene_end] drop` so post-rerun analysis can count rejections.
- (File output moved to orchestrator — see "Scene File Output" below)

### Phase 3: Nightly Compression (`day_phase = "compression"`)

For each agent (concurrently):
1. Read `today.md` content, active concerns, and unfulfilled intentions from daily plan
2. Call LLM with `nightly_compress.j2` → returns `CompressionResult`:
   - `daily_summary`: 1-2 sentence summary of the day. The prompt requires neutral 中性记录式 phrasing (no 似乎/仿佛/暗流涌动 — see Fix 1). If there are unfulfilled intentions, the prompt asks the LLM to briefly note why (no opportunity? changed mind? interrupted?) — reflections enter `recent.md` with natural ~3 day half-life
   - `permanent_memories`: candidates with importance scores (subject to the same intensity scale anchor from Fix 1)
   - `new_concerns`: concerns surfaced by reviewing the whole day (safety net for scene-end misses). Can be positive (positive=true) — e.g. anticipation, warmth
3. Append daily summary to `recent.md` as `# Day N` section
4. Save memories with importance ≥ `settings.key_memory_write_threshold` (=3, Fix 14) to `key_memories.json`
5. Apply new concerns via `add_concern` (Fix 2 — topic-based dedup), with `source_scene=""`
6. **Fix 14 per-day cap post-pass**: `cap_today_memories(storage, day, profile_name)` keeps at most `settings.per_day_memory_cap` (=2) of today's memories, dropping the lowest-importance excess. Both scene-end reflections and the compression call feed into the same key_memories file at threshold ≥3, so a single busy day could otherwise blow out an agent's memory list. Older days are untouched.
7. Clear `today.md`

### Phase 3.5: Daily Snapshots (after compression)

After compression completes, `_save_daily_snapshots(day)` copies each agent's current `state.json`, `relationships.json`, and `self_narrative.json` to `logs/day_{N:03d}/agent_snapshots/{agent_id}/`. These snapshots represent agent state at **end of Day N** = **start of Day N+1**.

**Day 0 initial snapshot**: `_save_day0_snapshot_if_needed()` runs at the start of each day loop, idempotently creating `logs/day_000/agent_snapshots/` from the pristine agent files if it doesn't already exist. This is the baseline for Day 1 morning state.

**Snapshot semantics**: `day_N` snapshot = agent state at end of Day N. Exception: `day_000` = initial state before any simulation = start of Day 1.

**Retroactive backfill**: `scripts/export_frontend_data.py` includes `backfill_snapshots()` which creates `day_000` and fills any missing `day_NNN` snapshots for already-simulated days using current agent files.

**Purpose**: Snapshots enable the interactive chat API to reconstruct agent state at any historical timepoint (used by God Mode and Role Play chat).

```
logs/day_001/agent_snapshots/
  lin_zhaoyu/
    state.json
    relationships.json
    self_narrative.json
  fang_yuchen/
    ...
```

### End of Day

For all agents (students + teacher):
- Reset energy to 85 (sleep)
- Decay all active concern intensities by `settings.concern_decay_per_day` (=2); evict any concern with intensity <= 0 OR `last_reinforced_day` more than `settings.concern_stale_days` (=5) behind today. See **Concern Decay** below for the rationale.
- **Emotion decay**: extreme emotions (angry, excited, sad, embarrassed, jealous, guilty, frustrated, touched) have 50% chance of resetting to neutral overnight
- **Relationship regression**: favorability and trust each nudge 1 point toward zero daily. Understanding does not regress (it represents cognitive knowledge that doesn't fade overnight)
- **Academic pressure update** (students only): calls `update_academic_pressure()` with current countdown and days since last exam. This activates countdown pressure escalation (≤14 days: +3, ≤7 days: +8, ≤3 days: +15) and post-exam recovery (day 0 resets to base, then -2/day decay). `days_since_exam` is computed from `progress.last_exam_day`.

Global end-of-day:
- Save trajectory data to `logs/day_NNN/trajectory.json`
- Write `logs/day_NNN/scenes.json` — scene index for frontend navigation (built from scene files written during the day)
- Expire events older than `event_expire_days` (default 3)
- Decrement `next_exam_in_days`
- Advance progress to next day

### Scene File Output

After all groups in a scene complete, the orchestrator writes a single frontend-ready scene file: `logs/day_NNN/HHMM_scenename.json` (e.g. `0845_课间@教室.json`). `scene.name` already includes `@location` for free periods.

**Format:**
```json
{
  "scene": { "scene_index", "time", "name", "location", "description", "day" },
  "participant_names": { "agent_id": "中文名" },
  "groups": [
    {
      "group_index": 0, "participants": ["agent_id", ...],
      "ticks": [
        {
          "tick": 0,
          "public": { "speech", "actions", "environmental_event", "exits" },
          "minds": { "agent_id": { PerceptionOutput fields } }
        }
      ],
      "narrative": { NarrativeExtraction fields },
      "reflections": { "agent_id": { AgentReflection fields } }
    },
    {
      "group_index": 1, "participants": ["agent_id"],
      "is_solo": true,
      "solo_reflection": { "inner_thought", "emotion", "activity" }
    }
  ]
}
```

Key details:
- `serialize_tick_records()` in `orchestrator.py` converts in-memory tick records to the `ticks` array; Chinese names in `action_target` are converted to `agent_id`
- `write_scene_file()` in `apply_results.py` atomically writes the assembled data
- `minds` **excludes gated agents** — agents listed in `tick_record["gated_agents"]` reused `last_perception` verbatim (PDA optimization) and their observation/inner_thought are stale copies. Serializing them would produce the same long line across consecutive ticks in the scene JSON log, which confuses human review and downstream analysis. The serialized tick still carries a `gated_agents: list[str]` field alongside `minds` so frontend / debug tooling can render "who was quiet this tick" without relying on absence.
- Solo groups use `is_solo: true` + `solo_reflection` (no fake ticks/narrative)
- No `baselines` in scene file — frontend uses `reflections.relationship_changes` (delta values)

---

## Data Models (`models/`)

### AgentProfile (`models/agent.py`) — Immutable

```
agent_id: str                    # e.g. "lin_zhaoyu"
name: str                        # e.g. "林昭宇"
gender: Gender                   # male | female
role: Role                       # student | homeroom_teacher
seat_number: int | None
dorm_id: str | None              # e.g. "male_301"
position: str | None             # e.g. "班长", "学习委员"
personality: list[str]           # e.g. ["内向", "认真", "敏感"] (林昭宇)
speaking_style: str              # natural language description
academics: Academics
  overall_rank: OverallRank      # top | 上游 | 中上 | 中游 | 中下 | 下游
  strengths: list[str]           # e.g. ["数学", "物理"]
  weaknesses: list[str]          # e.g. ["英语"]
  study_attitude: str            # e.g. "极其刻苦，课间也在刷题"
  target: AcademicTarget         # 985 | 211 | 一本 | 二本 | 没想过
  homework_habit: str
family_background: FamilyBackground
  pressure_level: PressureLevel  # 高 | 中 | 低
  expectation: str
  situation: str
long_term_goals: list[str]
backstory: str
inner_conflicts: list[str]       # e.g. ["渴望友情但社交笨拙", "用AI查题后的负罪感和对成绩的执念在拉扯"]
```

### AgentState (`models/agent.py`) — Mutable, updated every scene

```
emotion: Emotion                 # 15 values: happy, sad, anxious, angry, excited, calm,
                                 #   embarrassed, bored, neutral, jealous, proud, guilty,
                                 #   frustrated, touched, curious
energy: int (0-100)              # Default 85, sleep resets to 85
academic_pressure: int (0-100)   # Based on family + exam proximity + rank changes
location: str                    # e.g. "教室"
daily_plan: DailyPlan
  intentions: list[Intention]    # max 3, each has target/goal/reason/fulfilled/abandoned/satisfies_concern/origin_day/pursued_days
  mood_forecast: Emotion
  location_preferences: LocationPreference
    morning_break: str           # 课间 08:45 destination (default "教室")
    lunch: str                   # 午饭 12:00 destination (default "食堂")
    afternoon_break: str         # 课间 15:30 destination (default "教室")
day: int
active_concerns: list[ActiveConcern]  # max 4 persistent emotional preoccupations
```

### ActiveConcern (`models/agent.py`)

```
text: str                        # "被江浩天当众嘲笑数学成绩"
source_event: str                # Brief trigger description
source_scene: str                # e.g. "课间" — legacy structural-dedup field
source_day: int
emotion: str                     # "羞耻"
intensity: int (1-10)            # Decays by `concern_decay_per_day` (=2) at end of day; 0 → removed
related_people: list[str]
positive: bool                   # False=negative (worry/hurt), True=positive (warmth/excitement/anticipation)
topic: ConcernTopic              # Fix 2: 10-value Literal enum used for dedup bucket
last_reinforced_day: int         # Fix 2: stale-eviction timestamp; updated by `add_concern`
```

Concerns are generated at two points: per-agent self-reflection (post-scene) and nightly compression. Both go through `add_concern` which performs **topic-based dedup** (Fix 2 — see Concern Topic Bucketing & Dedup section): same topic + overlapping `related_people` merges and bumps intensity, with a Frankenstein guard for the `其他` bucket that refuses to merge empty-people pairs. Max 4 per agent; lowest intensity evicted when full (positive and negative concerns compete equally on intensity). Self-reflection `concern_updates` can adjust intensity up or down based on events (e.g. being comforted → -2, being mocked again → +3). Templates display positive concerns separately under "你最近心里期待的事" and negative concerns under "你最近心里挥之不去的事".

`ConcernTopic` is a `Literal[10]` enum (`models/agent.py`): `学业焦虑 / 家庭压力 / 人际矛盾 / 恋爱 / 自我认同 / 未来规划 / 健康 / 兴趣爱好 / 期待的事 / 其他`. Both positive buckets (`兴趣爱好`, `期待的事`) ensure positive concerns aren't pushed into `其他` and outcompeted by negative ones.

### Relationship (`models/relationship.py`)

```
target_name: str
target_id: str
favorability: int (-100 to 100)  # How much you like them
trust: int (-100 to 100)         # How much you trust them
understanding: int (0 to 100)    # How well you know them
label: str                       # 学生 | 老师 | 同学 | 室友 | 同桌 | 前后桌
                                 # Auto-insert picks from source+target role (see Apply Results)
recent_interactions: list[str]   # "Day N {+|−|·}scene_name" tags with valence
                                 # prefix from signed fav+trust delta; capped at
                                 # settings.max_recent_interactions (=10, FIFO)
```

`RelationshipChange`: `from_agent`, `to_agent`, `favorability`/`trust`/`understanding` (delta values).

### Scene (`models/scene.py`)

```
scene_index: int
day: int
time: str                        # e.g. "08:45"
name: str                        # e.g. "课间"
location: str                    # 教室 | 食堂 | 宿舍 | 走廊 | 操场 | 小卖部 | 图书馆 | 天台
density: SceneDensity            # high | high_light | low
max_rounds: int                  # Default 12
description: str
agent_ids: list[str]
groups: list[GroupAssignment]    # group_id, agent_ids, is_solo
injected_events: list[str]      # Random events injected into LOW→HIGH_LIGHT scenes
teacher_present: bool
teacher_action: str | None
opening_event: str               # Randomly selected from schedule.json opening_events, used as tick 0 event
```

`SceneConfig` (loaded from `schedule.json`) has these additional fields:
- `opening_events: list[str]` — pool of environment descriptions for the PDA loop's initial tick
- `is_free_period: bool` — marks 课间/午饭 for location-split scene generation
- `valid_locations: list[str]` — allowed locations for free periods (only used when `is_free_period=true`)
- `pref_field: Literal["morning_break", "lunch", "afternoon_break"] | None` — which `LocationPreference` field this slot maps to (only used when `is_free_period=true`)

A `model_validator` enforces that any `is_free_period=true` entry has a non-empty `pref_field` and `valid_locations`, and that `location` (the slot's default) is itself in `valid_locations`. This makes typos and missing fields fail immediately at `load_schedule()` time. Schedule data is the single source of truth — `scene_generator.py`, `daily_plan.py`, and `replan` all read directly from `SceneConfig`.

### Event (`models/event.py`)

```
id: str                          # e.g. "evt_1"
source_scene: str
source_day: int
text: str                        # Natural language description
category: str                    # gossip, conflict, achievement, teacher_talk, discipline, etc.
witnesses: list[str]             # Agent IDs who saw it happen
known_by: list[str]              # Agent IDs who know about it (starts = witnesses, grows via gossip)
spread_probability: float (0-1)  # Chance of being shared when a knower meets a non-knower
active: bool                     # False after event_expire_days
cite_ticks: list[int]            # Fix 13: 1-indexed [Tick N] grounding the event in the source conversation. Empty for system-generated events
group_index: int | None          # Fix 13: which scene group the event came out of. None for system-generated events. Used by M1 sanity check for per-group cite validation
```

### Dialogue Models (`models/dialogue.py`)

```
ActionType: speak | non_verbal | observe | exit

PerceptionOutput:                  # PDA tick loop output per agent per tick
  observation: str                 # What the agent noticed (1 sentence)
  inner_thought: str               # What they're thinking (1-2 sentences)
  emotion: Emotion                 # Updated emotion after perceiving
  action_type: ActionType          # What they decide to do
  action_content: str | None       # Speech/action text (null if observe)
  action_target: str | None        # Who it's directed at (null if general)
  urgency: int (1-10)             # How strongly they want to act
  is_disruptive: bool             # For non_verbal: would this get everyone's attention?

TurnOutput:                        # Legacy model (kept for reference, no longer used in PDA loop)
  speech: str
  directed_to: str | None
  inner_thought: str
  action: str | None
  emotion: Emotion
  want_to_continue: bool

SceneEndAnalysis:                            # Legacy model (kept for reference)
  key_moments: list[str]
  relationship_changes: list[RelationshipChange]
  fulfilled_intentions: list[str]
  events_discussed: list[str]
  memories: list[MemoryCandidate]
  new_events: list[NewEventCandidate]
  final_emotions: dict[str, str]
  new_concerns: list[ConcernCandidate]
  concern_updates: list[ConcernUpdate]

NarrativeExtraction:                         # Objective facts from dialogue (1 per group)
  key_moments: list[str]                     # Significant events as one-line summaries (Fix 13: no 推测词)
  fulfilled_intentions: list[str]            # "name:intention" format
  events_discussed: list[str]                # Event IDs
  new_events: list[NewEventCandidate]        # Gossip/conflicts that may spread

NewEventCandidate:                           # Fix 13: each new event must cite source ticks
  text: str
  category: str
  witnesses: list[str]
  spread_probability: float
  cite_ticks: list[int]                      # 1-indexed [Tick N] from the conversation log

IntentionOutcome:                            # Agent self-eval of one intention
  goal: str                                  # LLM's restatement of the intention goal
  status: Literal["fulfilled","attempted","frustrated","abandoned","pending"]
  brief_reason: str                          # One-sentence explanation

AgentReflection:                             # Per-agent subjective reflection (1 per agent per group)
  emotion: Emotion                           # Post-dialogue emotional state
  relationship_changes: list[AgentRelChange] # to_agent, favorability/trust/understanding deltas
  memories: list[AgentMemoryCandidate]       # text, emotion, importance, people, location, topics
  new_concerns: list[AgentConcernCandidate]  # text, source_event, emotion, intensity, related_people
  concern_updates: list[AgentConcernUpdate]  # concern_text, adjustment (±int)
  intention_outcomes: list[IntentionOutcome]  # Self-eval of pending intentions from the dialogue

AgentRelChange:                              # Single-direction, no from_agent (belongs to focal agent)
  to_agent: str
  favorability: int                          # Delta
  trust: int                                 # Delta
  understanding: int                         # Delta

AgentMemoryCandidate:                        # No agent field (belongs to focal agent)
  text: str
  emotion: str
  importance: int (1-10)
  people: list[str]
  location: str
  topics: list[str]

AgentConcernCandidate:                       # No agent field (belongs to focal agent)
  text: str
  source_event: str
  emotion: str
  intensity: int (1-10)
  related_people: list[str]
  positive: bool                             # True for positive concerns (warmth, anticipation)

AgentConcernUpdate:                          # No agent field (belongs to focal agent)
  concern_text: str
  adjustment: int                            # Positive=worsened, negative=soothed

SoloReflection:
  inner_thought: str
  emotion: Emotion
  activity: str
```

### Progress (`models/progress.py`) — Checkpoint for crash recovery

```
current_day: int
current_date: str
day_phase: "daily_plan" | "scenes" | "compression" | "complete"
current_scene_index: int
scenes: list[SceneProgress]
  scene_index: int
  scene_id: str
  phase: "grouping" | "interaction" | "scene_end" | "applying" | "complete"
  groups: list[GroupCompletion]
    group_index: int
    status: "pending" | "llm_done" | "applied"
next_exam_in_days: int           # Default 29 (first exam on day 30), reset to exam_interval_days after each exam
last_exam_day: int | None        # Day number of most recent exam (None if no exam yet)
total_days_simulated: int
last_updated: str                # ISO timestamp
seed: int | None                 # Persisted RNG seed for deterministic scene generation on resume
```

### Memory (`models/memory.py`)

```
KeyMemory:
  date: str                      # e.g. "Day 3"
  day: int
  people: list[str]
  location: str
  emotion: str
  importance: int (1-10)         # Only >= 7 gets persisted
  topics: list[str]
  text: str
```

---

## Key Algorithms

### Energy System (`agent/state_update.py`)

Energy changes per scene type:
| Scene | Delta |
|-------|-------|
| 上课 | -5 |
| 早读 | -3 |
| 晚自习 | -5 |
| 课间 | +5 |
| 午饭 | +15 |
| 宿舍夜聊 | -5 |

Sleep resets to 85. Clamped to 0-100.

### Academic Pressure Formula (`agent/state_update.py`)

On exam day (days_since_exam=0): pressure resets directly to base. Otherwise:
```
pressure = base + countdown_delta + recovery
```
- `base`: HIGH family → 50, MEDIUM → 30, LOW → 15
- `countdown_delta`: exam in ≤3 days → +15, ≤7 → +8, ≤14 → +3, else 0
- `recovery` (days 1+ after exam): -2 × days_since_exam

Note: exam shock (rank_drop × 2) is applied separately in `apply_exam_effects()`, not through this function.

### Emotion Decay (`agent/state_update.py`)

Extreme emotions (angry, excited, sad, embarrassed, jealous, guilty, frustrated, touched) decay to neutral with 50% probability overnight (called in `_end_of_day`). The `scenes_since_extreme=2` parameter is hardcoded since `_end_of_day` models overnight sleep — a natural emotional reset regardless of when the emotion arose.

### Relationship Regression (`agent/state_update.py`)

Daily regression: `favorability` and `trust` each nudge 1 point toward zero at end of day. `understanding` does not regress — it represents cognitive knowledge ("I know this person is competitive") which doesn't fade overnight. This prevents indefinite negative spirals and ensures relationships require ongoing interaction to maintain.

### Concern Decay (`agent/state_update.py`)

`decay_concerns(state, today)` runs at end of day. Active concerns lose `settings.concern_decay_per_day` (=2) intensity per day; reaching 0 removes them. **Stale eviction (Fix 2)**: any concern whose `last_reinforced_day` is `>= settings.concern_stale_days` (=5) days behind `today` is removed entirely, regardless of remaining intensity. Per-agent self-reflection `concern_updates` provide event-driven adjustments on top (concerns can be soothed faster by comforting interactions or intensified by triggering events). The accelerated decay + stale eviction prevents concern lists from monotonically growing into a depressive backdrop.

### Concern Topic Bucketing & Dedup (Fix 2)

`ActiveConcern.topic` is a `Literal[10]` enum (`ConcernTopic` in `models/agent.py`): `学业焦虑 / 家庭压力 / 人际矛盾 / 恋爱 / 自我认同 / 未来规划 / 健康 / 兴趣爱好 / 期待的事 / 其他`. The two positive buckets (`兴趣爱好`, `期待的事`) give positive concerns a habitat so they don't get pushed into `其他` and evicted by negative ones. The Pydantic `Literal` is enforced by Instructor on every LLM call so drift like `英语焦虑` vs `学业焦虑` cannot create parallel buckets.

`add_concern(state, new, today, skip_cap=False)` (in `interaction/apply_results.py`) is the single entry point for new concerns from both `apply_scene_end_results` and `nightly_compress`. Logic:

1. **Find existing match** via `_find_existing_concern`:
   - For categorized topics (everything except `其他`): same topic + any non-empty `related_people` overlap → merge.
   - For `其他`: same topic + EXACT `related_people` set match → merge. If either side has empty people, NEVER merge (Frankenstein guard — empty-people `其他` buckets are almost always unrelated and merging produces a useless meta-concern).
2. **Merge**: bump intensity by 1 (clamped to 10), refresh text, append the new `source_event` to the existing one with `；` as a delimiter, update `last_reinforced_day` to `today`. The merged `source_event` is capped at 500 chars by slicing `[-500:]` (keep tail, drop the oldest prefix) — intent is that readers care about "what set this concern off lately", so when many reinforcements fill the buffer the oldest triggers are evicted first while the most recent are fully preserved. Chronological order (oldest → newest, left → right) is maintained; `[:500]` (keep head) would silently discard every reinforcement after the buffer first filled.
3. **No match**: cap intensity at `settings.concern_autogen_max_intensity` (=6) unless `skip_cap=True` (reserved for high-priority sources like exam shock that should land at full intensity), set `last_reinforced_day=today`, then either append or evict the lowest-intensity concern when at `max_active_concerns` (=4).

The only production caller of `skip_cap=True` today is `apply_exam_effects` (`world/exam.py`): when a student's `rank_change <= -3` after an exam, an `ActiveConcern(topic="学业焦虑", intensity=min(10, 5 + magnitude))` is constructed (8/9/10 ladder for -3/-4/-5+) and pushed through `add_concern(skip_cap=True, today=day)`. Without `skip_cap` the cap of 6 would erase the difference between a routine worry and a real shock.

### Exam Score Generation (`world/exam.py`)

**Trigger**: when `progress.next_exam_in_days` reaches 0, the orchestrator calls `_run_exam()` at the start of the day, before daily plans. Full chain: `load_previous_exam_results()` → `generate_exam_results()` → `apply_exam_effects(today=day)` → `save_exam_results()` → reload states → `HomeroomTeacher.post_exam_actions()` → set `progress.last_exam_day` and reset countdown.

`apply_exam_effects` mutates `academic_pressure` (+`abs(rank_change)*2`), `emotion`, `energy` (-15), AND now writes a high-intensity `学业焦虑` `ActiveConcern` for `rank_change <= -3` via `add_concern(skip_cap=True)` so the shock survives the autogen cap. The `today` parameter (required) sets `last_reinforced_day` so the new concern doesn't immediately look stale to `decay_concerns`.

**Teacher exam context**: `format_teacher_exam_context()` produces a class-level overview (total students, class average, top 3, struggling/improved students) instead of the per-student view.

Not LLM-driven — pure formula:
```
score = base(overall_rank) + subject_mod(±5 for strengths/weaknesses)
      + effort_mod(pressure/100 × attitude_coeff × 5) + gaussian_noise(0, variance)
```
- Base scores: top=88, 上游=78, 中上=70, 中游=62, 中下=54, 下游=45
- Variance inversely correlated with rank: top=3.0, 下游=10.0 (stronger students more consistent)
- Attitude coefficient maps `study_attitude` text → 0.0-1.2 multiplier
- Post-exam effects: rank drop ≥5 → SAD, rank rise ≥5 → EXCITED, high-pressure family + rank>5 → ANXIOUS, energy -15
- Results saved to `world/exam_results/day_NNN.json`

### PDA Tick Resolution (`interaction/resolution.py`)

Pure Python, no LLM calls. Resolves one tick of the Perception-Decision-Action loop.

**State** (`ResolutionState`): tracks queued speakers (agent_id → PerceptionOutput + ticks_queued), consecutive all-observe count, tick count, and active agent set.

**Speaker arbitration**: when multiple agents want to SPEAK in the same tick, a resolution score determines who speaks:
```
resolution_score = urgency + bonuses
```
Bonuses:
- +5 if agent was addressed in the previous resolved speech (action_target matches agent name)
- +3 to +6 if agent has an unfulfilled intention targeting someone present (base +3, scaled up to +6 by linked concern intensity: `3 * max(1.0, concern.intensity / 5.0)`)
- +3 per tick queued (from previous ticks)

**Urgency clustering fallback**: if variance of urgency values among this tick's speakers is ≤ 2 (everyone equally urgent), bonuses become the primary signal and urgency is demoted to a 0.1× tiebreaker. This prevents urgency from dominating when LLM outputs cluster.

Ties broken randomly via the provided `rng`.

**Queue management**: losers are queued with their PerceptionOutput. Queued agents whose action_target has exited are discarded. Queued outputs expire after 3 ticks.

**Action resolution by type**:
| ActionType | Resolution |
|------------|-----------|
| SPEAK | Competes for single speaker slot via scoring |
| NON_VERBAL | All resolve simultaneously into resolved_actions. If is_disruptive=True, generates environmental_event string: `【動作】{name}: {content}` |
| OBSERVE | No action. Non-disruptive, counts toward quiet tick |
| EXIT | Agent removed from active set |

**Scene termination** (`quiet_tick`): scene ends when `consecutive_quiet >= settings.consecutive_quiet_to_end` (default 4) AND `tick_count >= settings.min_ticks_before_termination` (default 3). A "quiet tick" means no speech resolved, no queued speakers waiting, and no environmental event (disruptive action). Non-disruptive NON_VERBAL actions do not block termination.

**Embodied pacing label** (Fix 8B): `_compute_pacing_label(tick, max_rounds)` in `interaction/turn.py` translates `tick / max_rounds` into one of three short Chinese strings (`刚开始` / `在聊` / `差不多该散了`). Labels are deliberately deflationary — "差不多该散了" rather than "高潮即将到来" — to discourage the LLM from staging dramatic climaxes near scene boundaries. The label is only injected into `perception_dynamic.j2` (under `## 场景节奏`) when it crosses a threshold from the previous tick: tick 0 (`刚开始`) is silently consumed by the loop's init value, the transition to `在聊` fires once, and the transition to `差不多该散了` fires once. Every other tick passes an empty `scene_pacing_label` so the template's `{% if %}` block renders nothing — preventing the same string from polluting 12-22 consecutive perception prompts.

### Gossip Propagation (`world/event_queue.py`)

Before each group interaction:
1. Find active events where at least one group member knows it and at least one doesn't
2. Roll `spread_probability` — if success, inject event into knower's context
3. LLM decides naturally whether to mention it
4. Only events listed in `events_discussed` output actually update `known_by` (avoids false positives)

### Memory Retrieval (`memory/retrieval.py`)

Tag-overlap based (not embedding-based):
1. Extract trigger tags from current scene: present agent names/IDs, location, scene name
2. For each key memory, compute overlap = |memory_tags ∩ triggers| where memory_tags = people + topics + location
3. Filter to memories with overlap > 0
4. Sort by (importance DESC, overlap DESC), return top K (default 10)

### Homeroom Teacher (He Min)

He Min is a full LLM-driven agent, participating in scenes like any student. She goes through daily plan generation, perception, dialogue, self-reflection, and nightly compression — using the same pipeline but with role-aware prompts.

**Scene participation** (probabilistic — she doesn't attend every scene):
| Scene type | Probability | Notes |
|-----------|-------------|-------|
| 晚自习 | 20% | Joins as full participant |
| 课间 (free period) | 10% | Appears in 教室 |
| 午饭 (free period) | 30% | Appears in 食堂 |
| 宿舍夜聊 | Never | Not in dorm |

**Role-aware prompt adaptations**:
- `system_base.j2`: "上海高中老师" instead of "上海高中生" language guidance
- `daily_plan.j2`: teacher-specific need prompts (student attention, parent calls, lesson prep). No location preferences section (teacher doesn't choose free-period locations). Academic fields (成绩/目标/学习态度) skipped.
- `self_narrative.j2`: conditional identity ("班主任兼语文老师" vs "高中生"), narrative/self_concept instructions adapted for teacher role
- `nightly_compress.j2`: uses `role_description` variable for opening line identity
- `perception_dynamic.j2` + `dialogue_turn.j2`: "班主任正在附近，说话注意点！" warning only shown to students (`teacher_present and not is_teacher`)
- `self_reflection.j2`: teacher's intention evaluation acknowledges observing/guiding students as part of her role
- `perception_static.j2`: dorm scene examples show NON_VERBAL + SPEAK patterns
- Re-planning skipped for teacher (no location preferences)
- **Suppression effect**: When `teacher_present=true`, the perception template warning naturally suppresses student speech urgency. The teacher herself does NOT see this warning (guarded by `is_teacher`).
- `prepare_context()` provides `is_student`/`is_teacher` booleans to all templates via the context dict

**Grouping**: teacher never goes solo — `_should_be_solo()` returns `False` early for non-students, regardless of energy/emotion state.

**Cold start**: He Min starts with empty relationships (`{}`). Her backstory names specific students she monitors, and the "班主任" position gives LLM enough context. Relationships populate naturally after scene interactions.

**Rule-driven behaviors** (`world/homeroom_teacher.py`):
- **Post-exam talks**: `post_exam_actions()` — for each student whose rank dropped ≥3 places, 70% chance of a teacher-student talk. Creates gossip events via `EventQueueManager` that spread through the student network.
- **Patrol events**: `patrol_event()` — injected into 晚自习/早读 (with internal 30% probability gate) and 上课 (30% gate applied in `scene_generator.py`) when the teacher is NOT a full scene participant. Events like "何老师巡视时发现有人在聊天" appear in `injected_events`.

---

## LLM Calls

All LLM calls go through `llm/client.py:structured_call()` which uses Instructor + LiteLLM to guarantee Pydantic model output. `structured_call()` returns an `LLMResult` dataclass containing the parsed Pydantic model (`.data`), token counts (`.tokens_prompt`, `.tokens_completion`), and cost (`.cost_usd`). Token usage is extracted from the raw completion response via `create_with_completion()`, and cost is calculated using `litellm.completion_cost()`. Each call has a dedicated Jinja2 template in `src/sim/templates/`.

| Call Type | Template | Response Model | Temperature | Max Tokens | Per Scene |
|-----------|----------|---------------|-------------|------------|-----------|
| Perception (PDA) | `perception_static.j2` (system) + `perception_dynamic.j2` (user) | `PerceptionOutput` | 0.9 | 32000 | N × ticks |
| Daily plan | `daily_plan.j2` | `DailyPlan` | 0.7 | 32000 | — |
| Solo reflection | `solo_reflection.j2` | `SoloReflection` | 0.9 | 32000 | 1 per solo |
| Narrative extraction | `scene_end_analysis.j2` | `NarrativeExtraction` | 0.3 | 32000 | 1 per group |
| Self-reflection | `self_reflection.j2` | `AgentReflection` | 0.7 | 32000 | N per group |
| Nightly compression | `nightly_compress.j2` | `CompressionResult` | 0.5 | 32000 | — |

**Reflection intensity calibration** (Fix 1) — `self_reflection.j2`, `nightly_compress.j2`, and `solo_reflection.j2` share a Jinja partial `partials/_intensity_scale.j2` that defines a 1-10 importance/intensity scale ("1-2 = 路过的小情绪 / 9-10 = 创伤级"), default-empty `new_concerns`, and explicit "trivial scene → empty memories" / "solo scene → close to baseline" rules. The partial is included once at the top of `nightly_compress.j2` so it covers both 任务2 (memories) and 任务3 (new concerns); `solo_reflection.j2` carries an inline 独处场景 anchor (≤25 字 inner_thought, banned 小说化 phrases) since it doesn't emit memory/concern lists; `nightly_compress.j2` 任务1 also gets a 中性记录式 style requirement to avoid 叙述者口吻.
| Self-narrative | `self_narrative.j2` | `SelfNarrativeResult` | 0.7 | 32000 | — |
| Re-plan | `replan.j2` | `ReplanResult` | 0.7 | 32000 | — |

Narrative extraction + N self-reflections run concurrently after each group dialogue (replacing the single `SceneEndAnalysis` call). Effective latency ≈ 1 LLM call despite N+1 total calls.

All templates include `system_base.j2` (shared system prompt establishing the Shanghai 建宁中学 setting as a 市重点 high school, role-aware language guidance — "上海高中生" for students vs "上海高中老师" for teacher — natural dialogue requirements, role consistency rules, few-shot examples of natural Chinese teen speech patterns, and inner_thought voice guidelines with bad/good examples to prevent self-analysis-report style thinking).

Context assembly (`agent/context.py:prepare_context()`):
- Profile summary (name, gender, personality, speaking style, academic rank/strengths/weaknesses/study attitude/homework habit/target, position, family expectation/situation, long-term goals, backstory, inner_conflicts)
- Relationships filtered to agents present in the scene, with qualitative `label_text` (亲近/还行/一般/有点疏远/不对付) computed from `(favorability+trust)/2`
- Today's events so far (`today.md`)
- Recent memory (last 3 days from `recent.md`)
- Relevant key memories (tag-overlap retrieval, max 10)
- Pending unfulfilled intentions (with `satisfies_concern` and `pursued_days` for display)
- **Active concerns** — persistent emotional preoccupations with qualitative `intensity_label` (轻微/中等/较强/强烈) replacing raw "强度 X/10"
- **Qualitative state labels** — `energy_label` (精疲力尽→精神充沛), `pressure_label` (轻松→几乎扛不住), `exam_label` (月考还远→月考近在眼前) via `agent/qualitative.py`
- **Self-narrative** — narrative text + `self_concept` (up to 4 identity bullets) + `current_tensions` (up to 3 struggle bullets) from `self_narrative.json`
- **Role booleans** — `is_student` and `is_teacher` (derived from `profile.role`) used by templates for role-conditional rendering
- Scene info (time, location, who's present)
- Known events (gossip the agent knows about)
- Exam countdown context
- **Inner conflicts** — character's permanent internal contradictions. Displayed as "你内心的永恒矛盾" to distinguish from `current_tensions` ("你最近在和这些搏斗")
- PDA tick loop params (used by `perception_static.j2` + `perception_dynamic.j2`):
  - `latest_event`: what just happened (string)
  - `scene_transcript`: formatted public events so far
  - `private_history`: agent's own prior observations + inner thoughts
  - `tick_emotion`: in-memory emotion override (updated each tick without persisting to state)
  - `emotion_trace`: last 5 emotion values from the current scene's tick history (displayed as "你的情绪变化" chain when >1 entry)

Every LLM call is logged to `logs/day_NNN/debug/scene_name/group_id/calltype_timestamp.json` with full input/output, latency, and token counts. Costs are appended to `logs/costs.jsonl`.

---

## File Layout

```
data/
  characters/                    # 10 student + 1 teacher JSON profiles (immutable source of truth)
    lin_zhaoyu.json, tang_shihan.json, jiang_haotian.json, lu_siyuan.json,
    he_jiajun.json, shen_yifan.json, cheng_yutong.json, su_nianyao.json,
    fang_yuchen.json, he_min.json
  schedule.json                  # 8 daily scenes: 07:00 早读 → 22:00 宿舍夜聊 (3 with is_free_period=true)
  location_events.json           # Location-specific opening events for free period scenes

agents/                          # Runtime state (gitignored, created by init_world.py)
  <agent_id>/
    profile.json                 # Copy of character profile
    state.json                   # Current emotion, energy, pressure, plan, day, active_concerns
    relationships.json           # Sparse relationship map {target_id: Relationship}
    self_narrative.json          # Structured self-narrative (narrative + self_concept + current_tensions)
    self_narrative.md            # Human-readable mirror of narrative text (not read as source)
    key_memories.json            # Permanent memories (importance ≥ key_memory_write_threshold, Fix 14: =3)
    today.md                     # Raw events from current day (cleared nightly)
    recent.md                    # Compressed daily summaries (rolling window)

world/                           # Global state (gitignored, created by init_world.py)
  progress.json                  # Simulation checkpoint
  event_queue.json               # Active + expired events
  exam_results/                  # Per-exam result files (day_NNN.json)
  snapshots/                     # Pre-scene agent snapshots for crash recovery (transient)
    scene_N/
      .complete                  # Marker: snapshot fully written
      <agent_id>/
        state.json, relationships.json, key_memories.json, today.md

logs/                            # Simulation logs (gitignored)
  sim.log                        # Main log (10MB rotation)
  costs.jsonl                    # Per-call cost tracking
  day_NNN/                       # Per-day detailed logs
    HHMM_scenename.json          # One file per scene, all groups inside (frontend-ready)
    scenes.json                  # Scene index for frontend navigation
    trajectory.json              # Per-agent location/emotion trajectory for frontend
    debug/                       # Raw LLM call logs
      scene_name/
        group_id/
          calltype_timestamp.json

tests/                           # Unit tests (pytest)
  test_resolution.py             # PDA tick resolution logic (31 tests)
  test_narrative.py              # Transcript formatting and summarization
  test_models.py                 # Pydantic model validation (PerceptionOutput, ActionType)

scripts/
  init_world.py                  # Initialize agents/ and world/ from data/characters/
  inspect_state.py               # Debug tool to view current simulation state
  export_frontend_data.py        # Copy simulation output → web/public/data/
  sanity_check/                  # Phase 1+1.5 milestone scripts (M1-M6)
    m1_ungrounded_events.py      # Fix 13: count events with missing or invalid cite_ticks
    m2_per_day_memory_cap.py     # Fix 14: assert per-day key_memories ≤ per_day_memory_cap
    m3_concern_topic_dedup.py    # Fix 2: assert each (agent, topic) bucket has ≤1 entry (其他 informational)
    m4_empty_relationships.py    # Fix 4: assert no agent has an empty relationships map
    m5_positive_emotion_ratio.py # Fix 1+3: positive emotion share across reflections ≥ 25%
    m6_per_agent_memory_count.py # Fix 1+14: per-agent memory count + importance histogram (OBSERVE only)
    run_all.py                   # Aggregate runner — emits a Markdown report

src/sim/
  main.py                        # CLI entry point (argparse → Orchestrator.run)
  config.py                      # Settings via pydantic-settings (SIM_ env prefix)
  models/                        # Pydantic models (agent, dialogue, event, memory, progress, relationship, scene, trajectory)
  agent/                         # Agent-level logic
    storage.py                   # AgentStorage + WorldStorage (file I/O, atomic writes, structured self_narrative load/save)
    context.py                   # prepare_context() — assembles full LLM context with qualitative labels
    daily_plan.py                # generate_daily_plan() — intention generation with concern linkage + carry-forward
    self_narrative.py            # generate_self_narrative() — periodic identity reflection (structured: narrative + self_concept + current_tensions)
    qualitative.py               # Numeric → qualitative label helpers (energy, pressure, intensity, relationship, exam)
    replan.py                    # maybe_replan() — reactive location changes between scenes
    state_update.py              # Energy, pressure, emotion, concern decay formulas
  world/                         # World-level logic
    schedule.py                  # load_schedule() from data/schedule.json
    scene_generator.py           # SceneGenerator — lazy per-config scene generation, free period location splitting
    grouping.py                  # group_agents() — solo detection + affinity-based clustering
    event_queue.py               # EventQueueManager — add, spread, expire events
    exam.py                      # generate_exam_results(), apply_exam_effects(), format_exam_context()
    homeroom_teacher.py          # HomeroomTeacher — rule-driven post-exam talks + patrol events
  interaction/                   # Scene execution logic
    orchestrator.py              # Orchestrator — main loop, serialize_tick_records(), scene file + scenes.json output
    turn.py                      # run_perception() + run_group_dialogue(group_index=) — PDA tick loop with perception gating
    resolution.py                # resolve_tick() — PDA tick resolution (speaker arbitration, queue, scene end)
    narrative.py                 # format_public_transcript(), format_agent_transcript(), format_latest_event()
    scene_end.py                 # run_scene_end_analysis() — objective narrative extraction (post-dialogue)
    self_reflection.py           # run_agent_reflection() + run_all_reflections() — per-agent subjective reflection
    apply_results.py             # apply_scene_end_results() + apply_solo_result() + write_scene_file() + concern_match()
    solo.py                      # run_solo_reflection() — solo agent inner monologue
  llm/                           # LLM infrastructure
    client.py                    # structured_call() via Instructor + LiteLLM; auto-fallback to llm_fallback_model on failure
    prompts.py                   # render() — Jinja2 template rendering
    logger.py                    # log_llm_call() — per-call JSON logging + cost tracking
  memory/                        # Memory management
    compression.py               # nightly_compress() — summarize today → recent, extract key memories
    retrieval.py                 # get_relevant_memories() — tag-overlap retrieval
    writer.py                    # Helper wrappers for today.md and key_memory writes
  templates/                     # Jinja2 prompt templates (all in Chinese)
    partials/
      _intensity_scale.j2        # Shared intensity / importance 1-10 scale + default-empty new_concerns + trivial-scene rules (Fix 1)
    system_base.j2               # Shared system prompt (high school setting + dialogue rules + few-shot teen speech examples)
    perception_static.j2         # PDA perception system message — agent identity, relationships, memories, scene info (stable within a scene; enables DeepSeek prefix caching)
    perception_dynamic.j2        # PDA perception user message — transcript, latest_event, emotion trace, output format instructions (changes per tick)
    dialogue_turn.j2             # Legacy per-turn dialogue (kept for A/B comparison reference)
    daily_plan.j2                # Morning plan with concern linkage (satisfies_concern), yesterday intentions display, self_concept + current_tensions
    solo_reflection.j2           # Solo inner monologue (qualitative labels, self_concept + current_tensions)
    scene_end_analysis.j2        # Post-dialogue objective narrative extraction
    self_reflection.j2           # Per-agent reflection (qualitative labels, intention_outcomes self-eval, self_concept + current_tensions)
    nightly_compress.j2          # Daily summary + permanent memory + concern extraction (qualitative intensity labels)
    self_narrative.j2            # Periodic structured self-reflection (narrative + self_concept + current_tensions)
    replan.j2                    # Reactive location re-planning (qualitative concern labels)
```

---

## Configuration (`config.py`)

All settings via `pydantic-settings` `BaseSettings`, loaded from `.env` file, overridable with `SIM_` env prefix:

| Setting | Default | Description |
|---------|---------|-------------|
| `llm_model` | `deepseek/deepseek-chat` | LiteLLM model identifier |
| `llm_fallback_model` | `openrouter/google/gemini-3-flash-preview` | Fallback model for structured calls when primary fails validation |
| `creative_temperature` | 0.9 | Dialogue turns, solo reflection |
| `analytical_temperature` | 0.3 | Scene-end analysis |
| `plan_temperature` | 0.7 | Daily plan generation |
| `compression_temperature` | 0.5 | Nightly compression |
| `max_tokens_per_turn` | 32000 | Dialogue turn max tokens |
| `max_tokens_scene_end` | 32000 | Scene-end analysis max tokens |
| `max_tokens_daily_plan` | 32000 | Daily plan max tokens |
| `max_tokens_compression` | 32000 | Nightly compression max tokens |
| `max_tokens_solo` | 32000 | Solo reflection max tokens |
| `max_retries` | 3 | LLM call retries |
| `min_ticks_before_termination` | 3 | Minimum ticks before scene can end |
| `consecutive_quiet_to_end` | 4 | Consecutive quiet ticks to trigger scene end |
| `perception_temperature` | 0.9 | PDA perception LLM call temperature |
| `max_tokens_perception` | 32000 | PDA perception max tokens |
| `max_concurrent_llm_calls` | 5 | Async semaphore limit |
| `exam_interval_days` | 30 | Days between exams |
| `event_expire_days` | 3 | Days before events become inactive |
| `recent_md_max_weeks` | 4 | Rolling window for recent.md |
| `max_key_memories` | 10 | Max key memories in context |
| `key_memory_write_threshold` | 3 | Fix 14: minimum importance to write a memory (lowered from hardcoded 7) |
| `per_day_memory_cap` | 2 | Fix 14: post-compression cap on today's memory count per agent |
| `solo_energy_threshold` | 25 | Energy below this → solo |
| `self_narrative_interval_days` | 3 | Days between self-narrative regeneration |
| `self_narrative_temperature` | 0.7 | Self-narrative LLM temperature |
| `max_tokens_self_narrative` | 32000 | Self-narrative max tokens |
| `replan_temperature` | 0.7 | Re-plan LLM temperature |
| `max_tokens_replan` | 32000 | Re-plan max tokens |
| `max_active_concerns` | 4 | Max concerns per agent |
| `concern_decay_per_day` | 2 | Fix 2: end-of-day intensity decay (was effectively 1) |
| `concern_stale_days` | 5 | Fix 2: days without reinforcement → evict regardless of intensity |
| `concern_autogen_max_intensity` | 6 | Fix 2: cap for reflection/compression-generated concerns; bypassed via `skip_cap=True` |
| `max_recent_interactions` | 10 | Per-relationship FIFO cap on `recent_interactions` tag log (populated on any non-zero relationship_change) |

---

## Initialization (`scripts/init_world.py`)

1. Wipes `agents/`, `world/`, and `logs/` directories
2. For each character in `data/characters/*.json`:
   - Copies profile to `agents/<id>/profile.json`
   - Creates initial state (energy=85, pressure based on family: 高→60, 中→35, 低→15, emotion=neutral, active_concerns=[])
   - Creates relationships from preset pairs (defined in `PRESET_RELATIONSHIPS` — roommates, seatmates, desk neighbors with initial favorability/trust values)
   - Creates empty `key_memories.json`, `today.md`, `recent.md`, `self_narrative.md`
3. Creates `world/progress.json` (day 1, daily_plan phase, next_exam_in_days=29)
4. Creates empty `world/event_queue.json`
5. Creates `world/exam_results/` directory

### Dorm Assignments (hardcoded in `world/scene_generator.py`)

```
male_301:   lin_zhaoyu, jiang_haotian, lu_siyuan, shen_yifan
male_303:   he_jiajun
female_302: tang_shihan, cheng_yutong, su_nianyao, fang_yuchen
```

### Preset Relationships (from `scripts/init_world.py`)

```
lin_zhaoyu ↔ tang_shihan    同桌    fav: 10/5   trust: 5/5
lin_zhaoyu ↔ jiang_haotian  前后桌  fav: 5/10   trust: 0/5
lin_zhaoyu ↔ lu_siyuan      室友    fav: 15/15  trust: 10/10
lin_zhaoyu ↔ shen_yifan     室友    fav: 10/10  trust: 5/5
jiang_haotian ↔ lu_siyuan   室友    fav: 5/5    trust: 5/5
jiang_haotian ↔ shen_yifan  室友    fav: -5/0   trust: 0/0
cheng_yutong ↔ su_nianyao   同桌    fav: 5/10   trust: 5/5
su_nianyao ↔ fang_yuchen    前后桌  fav: 20/20  trust: 15/15
tang_shihan ↔ fang_yuchen   室友    fav: 15/15  trust: 10/10
tang_shihan ↔ cheng_yutong  室友    fav: 5/5    trust: 5/5
tang_shihan ↔ su_nianyao    室友    fav: 10/10  trust: 5/5
```

---

## Trajectory Output (`models/trajectory.py`)

Per-day trajectory data saved to `logs/day_NNN/trajectory.json` for frontend visualization:

```
DayTrajectory:
  day: int
  agents: dict[str, list[AgentSlot]]   # agent_id → time slots

AgentSlot:
  time: str                             # e.g. "08:45"
  scene_name: str                       # e.g. "课间@走廊"
  location: str                         # e.g. "走廊"
  emotion: str                          # emotion at scene start
```

Collected during scene execution; each agent gets one slot per scene they participate in.

---

## Key Engineering Patterns

- **Atomic writes** (`agent/storage.py:atomic_write_json(path, data: dict | list)`): All JSON writes use temp file + `os.fsync` + `os.replace` to prevent corruption on crash.
- **Checkpoint-based recovery**: Every phase transition saves progress. On restart, the orchestrator skips completed phases/scenes/groups. Group status tracks: `pending` → `llm_done` → `applied`.
- **Pre-scene snapshot/restore**: Before interaction begins, agent files are snapshotted. If the scene is interrupted and resumed, the snapshot is restored, the scene resets to grouping, and re-runs from scratch. This prevents silent scene skips caused by lost in-memory group assignments and avoids double-applying partially-written state changes.
- **Per-day deterministic scene generation**: Scene generation uses a separate RNG seeded with `hash((base_seed, "scenes", day))`, ensuring the scene list (which LOW density scenes triggered) is identical across resume. The base seed is persisted in `progress.json` on first run; resume always reloads it. CLI `--seed` overrides the saved seed. Without this, the main RNG's consumption history would differ on resume, causing scene indices to shift.
- **Idempotent result application**: Scene-end results are saved with baseline relationship snapshots. Deltas are applied to baselines, not current values, so re-applying the same result is safe.
- **Structured LLM output**: All LLM calls use Instructor's `response_model` parameter to guarantee Pydantic model parsing. No free-form text parsing anywhere.
- **Async concurrency**: Daily plans and nightly compression run all agents concurrently, throttled by `asyncio.Semaphore(max_concurrent_llm_calls)`. Scene execution is sequential (each scene depends on the previous scene's state changes).
- **Name ↔ ID mapping**: LLM prompts use Chinese names (林昭宇). Code uses snake_case IDs (lin_zhaoyu). `name_to_id` mapping is built from profiles during result application.

---

## Frontend — SimClass Pixel World

Pixel-art school world viewer (Stardew Valley aesthetic, top-down). Two modes: **Explore** (click around, scrub ticks) and **Broadcast** (auto-camera follows drama, danmu overlays). Core mechanic: mind-reading toggle reveals inner thoughts vs spoken words.

**Tech stack**: Vite + React 19 + TypeScript, PixiJS 8 + @pixi/react 8 (canvas rendering), Tailwind CSS 3, Framer Motion (panel animations), Zustand 5 (state), React Router 7, D3.js (Phase 2 graphs). Fonts: LXGW WenKai (thoughts), Noto Sans SC (body).

**Architecture**: PixiJS owns the game canvas (rooms, sprites, camera). React owns UI chrome (TopBar, BottomBar, SidePanel, RoomNav) as absolute-positioned overlays. BubbleOverlay and DanmuLayer are imperative DOM layers synced to the PixiJS Ticker (same rAF frame). Camera state lives on the PixiJS Container transform, not in Zustand.

### Data Pipeline

`scripts/export_frontend_data.py` copies simulation output → `web/public/data/` (unchanged). Drama scores and character positions are computed in the frontend, not the export script.

```
web/public/data/
  meta.json                     # days, agent map, schedule, date, exam countdown
  agents/{agent_id}.json        # profile + state + relationships + self_narrative + key_memories
  days/day_001/
    scenes.json                 # scene index
    0845_课间@教室.json          # scene files with tick data
    trajectory.json             # per-agent per-scene emotions/activities
  events.json                   # event queue
```

### File Structure

```
web/src/
  main.tsx                      # Entry, BrowserRouter
  App.tsx                       # Routes: / (PixiCanvas), /relationships, /timeline
  index.css                     # Tailwind directives + custom styles
  stores/
    useWorldStore.ts            # Zustand: day, scene, tick, group, room, mode, mindReading, focusedAgent, playback
    useAppStore.ts              # Legacy store (used by Phase 2 views only)
  lib/
    types.ts                    # Data interfaces + RoomId, RoomZone, RoomLayout, ViewMode, PlaybackSpeed
    data.ts                     # fetch+cache + prefetchDay() for current day (~650KB)
    constants.ts                # SEAT_LAYOUT, EMOTION_COLORS, EMOTION_LABELS, EMOTION_EMOJIS, LOCATION_ICONS
    roomConfig.ts               # Room zone definitions (7 rooms), derivePositions() for character placement
    drama.ts                    # scoreTick(), scoreGroup(), dramaThreshold(), isDramaPeak(), pickDanmu()
    PlaybackController.ts       # Singleton. Two strategies: MANUAL (arrow keys / scrubber) + BROADCAST (auto-advance, drama-sorted groups). 3s/tick at 1x.
  components/
    world/                      # PixiJS rendering
      PixiCanvas.tsx            # Main mount: Application, data loading, sprite management, camera, keyboard shortcuts. Composes Room + TopBar + BottomBar + SidePanel + RoomNav.
      Room.tsx                  # Programmatic tilemap for each of 7 rooms. Draw functions: drawClassroom, drawHallway, drawCafeteria, drawDorm, drawPlayground, drawLibrary, drawConvenienceStore.
      CharacterSprite.ts        # Colored circle + head + name label. Per-agent colors. updateSpriteState() for talking/dimming.
      Camera.ts                 # Free-scroll (drag + wheel zoom) + auto-pan (lerp). State on PixiJS Container transform, updated via Ticker.
      BubbleOverlay.ts          # Imperative DOM overlay. 4 bubble types: speech (cream bg, optional inline inner_thought in mind-reading), thought (rose dashed, solo only), emoji (emotion indicator for observers in mind-reading, title tooltip shows inner_thought), action (small italic for non_verbal). Viewport-clamped positioning via sprite.toGlobal() each frame with overlap push-apart. Pointer triangle on speech/thought. Click forwarding via onBubbleClick callback → setFocusedAgent. Fade-in via opacity transition (no transform transition to avoid fly-in). Recreates DOM element on type change.
      ErrorBoundary.tsx         # Minimal React Error Boundary. Catches render errors, logs to console, renders nothing on crash (prevents blank page).
      DanmuLayer.ts             # Floating text scrolling right-to-left. Fires from inner_thought of observers. CSS animation, 8s duration.
    ui/                         # React overlays
      TopBar.tsx                # Day nav, title, mode toggle (探索/放映), mind-reading button
      BottomBar.tsx             # Scene info, group tabs, tick scrubber (bars colored by drama intensity), play/pause, speed (1x/2x/4x)
      SidePanel.tsx             # Slide-out character detail: emotion, personality, academics, concerns, relationships, recent thoughts. Framer Motion animated.
      RoomNav.tsx               # Timeline nav (left edge). Groups scenes by time slot via groupScenesByTimeSlot(). Multi-scene slots: non-clickable header (time + name) with indented location children. Single-scene slots: one clickable line. Active scene bg-white/20, active slot header amber. Auto-scrolls into view on change. max-h-[70vh] with overflow scroll.
    layout/                     # Legacy (Phase 2 analytical views)
      Header.tsx                # Nav bar for /relationships, /timeline
      PageShell.tsx             # Wrapper for legacy views
    relationships/
      ForceGraph.tsx            # D3 force graph (Phase 2)
      RelationshipCard.tsx      # Relationship detail
    timeline/
      EmotionTimeline.tsx       # SVG emotion waveform (Phase 2)
```

### Room System

7 rooms, each with a programmatic tilemap and named zones for character positioning:

| Room | Dimensions | Zones | Visual features |
|------|-----------|-------|-----------------|
| 教室 | 24×18 | 20 seat zones + teacher | Blackboard, 5×4 desks, windows |
| 走廊 | 28×10 | left, center, right | Lockers, notice board, windows |
| 食堂 | 28×20 | 6 table zones | Food counter, 6 dining tables |
| 宿舍 | 24×16 | 3 beds + desk area | Bunk beds, shared desk, window |
| 操场 | 30×20 | court, 2 benches, track | Basketball court, running track |
| 图书馆 | 24×18 | 4 tables + shelves | Bookshelves (colored spines), reading tables |
| 小卖部 | 16×14 | counter, 2 aisles | Counter with register, product shelves |

Classroom uses seat-based positioning from agent metadata. Other rooms spread participants in circular patterns within assigned zones.

### Playback Model

```
PlaybackController (singleton)
├── Mode: MANUAL (explore)
│   ├── Scrubber click → setTick(n)
│   ├── Arrow keys → advance/retreat tick
│   └── Play button → auto-advance at speed, pause on interaction
├── Mode: BROADCAST
│   ├── Auto-advance ticks at 3s/tick × (1/speed)
│   ├── End of group → cut to next group (sorted by drama)
│   ├── End of scene → next scene in time slot
│   ├── Skip solo scenes by default
│   └── End of day → stop
└── Shared: speed 1x|2x|4x, tick duration 3s base
```

Drama score per tick: `speak×1 + disruptive×5 + max_urgency×0.5 + exit×2`. Top 20% are peaks that trigger camera zooms and danmu.

### Key Interactions

- **Mind-reading toggle** (M key or TopBar button): thought bubbles appear for all characters. Speech = cream solid bubble, thought = rose dashed italic bubble.
- **Click character**: SidePanel slides open with full profile. Other characters dim to 40%.
- **Tick scrubber**: visual drama intensity bars. Click to jump, arrow keys to step.
- **Room nav**: click room tab to jump to first scene in that location.
- **Camera**: drag to pan, scroll to zoom (explore mode). Auto-follows speaker in broadcast mode.
- **Danmu**: inner thoughts of observers float across the top in broadcast mode.
- **Keyboard**: Space = play/pause, ←→ = tick step, M = mind-reading.

### Running

```bash
uv run python scripts/export_frontend_data.py   # Generate frontend data
cd web && pnpm dev                               # Dev server
cd web && pnpm build                             # Production build → web/dist/
uv run api                                       # Start API server (port 8000)
```

---

## Interactive Chat API (`api/`)

FastAPI server providing two interactive chat modes. Both are **read-only** (don't affect simulation state) and **time-aware** (context matches the selected point in the timeline).

**Module structure:**
- `api/server.py` — FastAPI app with CORS, endpoints, SSE streaming
- `api/models.py` — Pydantic request/response models (`ChatRequest`, `RolePlayRequest`, `AgentReaction`, `AgentReactionLLM`)
- `api/context.py` — Time-travel context assembly (`build_context_at_timepoint()`)

**Dependencies:** `fastapi`, `uvicorn`, `sse-starlette` (added to `pyproject.toml`)

### Time-Travel Context Assembly

`build_context_at_timepoint(agent_id, day, time_period, world)` reconstructs full agent context at a specific (day, time_period):

1. **Baseline state**: Load from `logs/day_{N-1}/agent_snapshots/` (previous day's end-of-day = this day's start). For Day 1, uses `day_000` (initial state).
2. **Key memories**: Filter `key_memories.json` to `day <= N`, sorted by importance.
3. **Recent summary**: Last 3 days from `recent.md`, filtered to `day <= N` via `max_day` parameter to prevent time-travel (viewing Day 1 won't leak Day 5 content).
4. **"Today so far"**: Reconstruct from scene files — loads `scenes.json`, filters scenes before the given time period, extracts `narrative.key_moments` and `reflections[agent_id].emotion` from scene JSONs.
5. **Emotion**: Scene emotion > baseline state emotion.
6. **Qualitative labels**: Reuses `energy_label()`, `pressure_label()`, `intensity_label()`, `relationship_label()` from `agent/qualitative.py`.

Returns a dict with all template variables needed for `god_mode.j2` or `role_play.j2`.

### God Mode

User clicks an agent and chats with their inner self. The agent responds with full honesty (no social mask).

- **Endpoint**: `POST /api/god-mode/chat` → `EventSourceResponse` (SSE)
- **Template**: `templates/god_mode.j2` (includes `chat_base.j2`)
- **Streaming**: Raw `litellm.acompletion(stream=True)` via `streaming_text_call()` — character-by-character
- **SSE events**: `{"token": "..."}` per chunk, `{"done": true}` at end
- **Prompt**: Agent identity + state + relationships + memories, ending with "respond as if writing in your diary — completely honest, no social mask"
- **Error handling**: Catches `ContextWindowExceededError` specifically and returns a user-friendly message ("对话太长了，请关闭后重新开始对话") instead of a raw error.

### Role Play

User becomes an agent, picks 1-4 other agents, and has a freeform group chat. All agents respond in character with social dynamics.

- **Endpoint**: `POST /api/role-play/chat` → `EventSourceResponse` (SSE)
- **Template**: `templates/role_play.j2` — system prompt contains stable agent context only (identity, relationships, state). Conversation history and latest message are sent as a separate user message for prefix caching.
- **Streaming**: Not token-level. Each agent gets a parallel `structured_call()` → `AgentReactionLLM` model (excludes `agent_id`/`agent_name` — these are filled from profile data). Results stream as SSE events as they complete.
- **Relationship filtering**: Each agent's context is filtered to only include relationships with scene participants (user agent + target agents), matching the template header "你和在场人物的关系".
- **SSE events**: `{"thinking": true, "agent_ids": [...]}` first, then `{"agent_id": "...", "content": "...", ...}` per agent reaction, `{"done": true}` at end
- **Actions**: Typed as `Literal["speak", "action", "silence"]` — Instructor enforces valid values and retries on hallucinated action types. Silent agents are filtered out.
- **Error handling**: Same `ContextWindowExceededError` handling as God Mode.

### Chat Templates

- `chat_base.j2` — Shared base for both modes. Same school setting as `system_base.j2` but without simulation-specific instructions (no tick system, no speaker selection rules, no structured output format).
- `god_mode.j2` — Full agent context (profile, relationships, memories, concerns, tensions, conflicts) + inner monologue instructions.
- `role_play.j2` — Stable agent context + social mask instructions. Conversation history and latest message are excluded from the template (sent as a separate user message by `server.py`) so the system prompt stays constant across turns for prefix caching.

### LLM Streaming

`llm/client.py` now has two functions:
- `structured_call()` — Existing function for structured output via Instructor. Role Play uses it with `AgentReactionLLM` as `response_model`.
- `streaming_text_call()` — New function for raw text streaming via `litellm.acompletion(stream=True)`. Used by God Mode. Returns `AsyncGenerator[str, None]`.

Both functions use `if value is not None else default` for `temperature` and `max_tokens` parameters to correctly handle explicit `0` / `0.0` values.

### Prefix Caching Strategy

Multi-turn chat benefits from LLM prefix caching when the message prefix stays identical across requests:

- **God Mode**: System prompt (agent context) is fully stable across turns. Chat history is sent as separate `user`/`assistant` messages that only append — each request is a prefix extension of the previous one. Optimal by default.
- **Role Play**: System prompt contains only stable agent context (identity, personality, state, relationships). Conversation history and latest message are sent as a separate `user` message, so the system prompt is identical across all turns within a session. Previously, history was embedded in the system prompt via the template, breaking caching on every turn.

---

## Visual Foundation

### Character Sprites (`spriteConfig.ts`, `CharacterSprite.ts`)

Characters are rendered as animated sprites from the LimeZu Modern Interiors premade character sheets (16×32 frame grid, 2× scale = 32px rendered). Each agent maps to a specific premade character PNG via `AGENT_SPRITE_MAP`.

**Frame map**: `ANIMATIONS` defines grid positions for `idle_down`, `idle_right`, `idle_up`, `idle_left` (4 frames each at different grid rows). The `AnimatedSprite` from PixiJS plays the idle animation at 4 FPS.

**Fallback**: Agents without sprite sheets render as the original colored circles with head + name label.

### Tileset Rendering (`tilesetConfig.ts`, `TilesetRenderer.ts`, `Room.tsx`)

Room floors use tileset textures via `TilingSprite` for repeating fills. Each room type maps to a floor tile reference in `ROOM_FLOOR`. Furniture and walls are still rendered procedurally via PixiJS `Graphics` (hybrid approach — tileset floors + procedural furniture details).

**Tilesets used**: `room_builder_16x16.png` (floors/walls), `classroom_library.png`, `bedroom.png`, `kitchen.png`, `grocery_store.png`, `gym_sport.png`, `exteriors_16x16.png`.

### Emote Bubbles (`BubbleOverlay.ts`)

Emotion indicator icons from the 32×32 emote balloon spritesheet appear above character sprites when agents have non-neutral emotions. Each SimClass emotion maps to a (col, row) position in the spritesheet via `EMOTION_EMOTE`. Emotes auto-fade after 2.5 seconds.

### Asset Pipeline

Purchased pixel art assets are copied from `assets/` (gitignored) into `web/public/assets/` (also gitignored — not committed). Directory structure:
```
web/public/assets/
  tilesets/       ← Room tile textures (16×16 tiles)
  sprites/        ← Character sprite sheets (premade_NN.png)
  emotes/         ← Emote balloon spritesheets (32×32)
  ui/paper_theme/ ← UI panel assets
```

---

## Frontend Chat UI

### God Mode Chat (`GodModeChat.tsx`)

Slide-in panel from right (same position as SidePanel, using Framer Motion). Entry: click "内心" button in SidePanel header. Shows agent sprite portrait, streaming text with diary-style font (`LXGW WenKai`), user messages right-aligned, agent responses left-aligned with italic handwritten style.

### Role Play Chat (`RolePlaySetup.tsx`, `RolePlayChat.tsx`)

- **Setup**: Modal with agent portrait grid. Step 1: pick your character. Step 2: pick 1-4 conversation partners.
- **Chat view**: Full-screen replacement of the PixiCanvas. Participant portraits in header, messages from all participants with sprite avatars, "正在思考..." indicator while agents process. Entry: "角色扮演" button in TopBar.

### Store Extensions (`useWorldStore.ts`)

Chat state added to Zustand store:
- `chatMode`: `'off' | 'god' | 'roleplay'`
- `chatMessages`, `chatStreaming`, `chatStreamBuffer` — message history + streaming state
- `rolePlayUserAgent`, `rolePlayTargetAgents`, `rolePlayReactions` — role play session state
- Actions: `openGodModeChat()`, `openRolePlayChat()`, `closeChat()`, `appendStreamToken()`, `flushStreamBuffer()`, `appendAgentReaction()`

### SSE Client (`chat.ts`)

Frontend SSE streaming client using `fetch()` + `ReadableStream` reader. Two async generators:
- `streamGodModeChat()` — yields text tokens
- `streamRolePlayChat()` — yields `AgentReaction` objects or `{thinking: true}` events

### Vite Proxy

`vite.config.ts` proxies `/api` requests to `http://localhost:8000` for development.
