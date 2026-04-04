# Architecture & Technical Reference

Multi-agent simulation of a Chinese high school class (中国高中班级模拟). Each agent (student/teacher) is an LLM-powered character that interacts through structured daily scenes, generating emergent narratives. Pure observation mode — no user intervention, text output only. The goal is to simulate a full three years of high school life and produce narrative content that could be edited into video.

**Tech stack**: Python 3.12+, DeepSeek V3.2 via LiteLLM + Instructor (structured JSON output), Pydantic (data models + validation), Jinja2 (prompt templates), Loguru (logging), asyncio (concurrency). All state stored as JSON + Markdown files — no database.

**Scale**: 10 students + 1 teacher (homeroom teacher). All character data, prompts, and narrative output are in Chinese.

---

## Architecture Overview

Four-layer design, all source code in `src/sim/`:

```
┌──────────────────────────────────────────────────────────┐
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
│  Instructor+LiteLLM client, Jinja2 prompt rendering,     │
│  per-call JSON logging with cost tracking                │
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

Each simulated day runs through three sequential phases:

### Phase 0: Self-Narrative Generation (periodic)

On day 1 and every `self_narrative_interval_days` (default 3) days:
- For each student (concurrently), call LLM with `self_narrative.j2` template
- Input: profile summary, recent 3-day summary, active concerns, relationships
- Output: `SelfNarrativeResult.narrative` — 100-200 word first-person self-reflection
- Saved to `agents/<id>/self_narrative.md`
- Used as context in all agent-facing prompts (perception, daily plan, solo reflection)

### Phase 1: Daily Plan Generation (`day_phase = "daily_plan"`)

For each student (concurrently, up to `max_concurrent_llm_calls`):
1. Load relationships, last 3 days of `recent.md`, yesterday's unfulfilled intentions, active concerns, self-narrative, and inner conflicts
2. Call LLM with `daily_plan.j2` template → returns `DailyPlan` (1-3 `Intention` objects + `mood_forecast` + `location_preferences`). The prompt first nudges the agent to reflect on unmet needs ("先想想你最近缺什么——朋友的陪伴？学业上的成就感？…") before generating intentions
3. Validate location preferences against valid lists (invalid → default)
4. Save updated state with new plan

`Intention` has: `target` (optional agent name), `goal`, `reason`, `fulfilled` (bool, starts false).

`LocationPreference` has: `morning_break` (课间 08:45), `lunch` (午饭 12:00), `afternoon_break` (课间 15:30). Agents choose from configured location lists.

### Phase 2: Scene Execution (`day_phase = "scenes"`)

For each scene in `data/schedule.json` (sequentially):

**Step 2a — Scene Generation** (`world/scene_generator.py`):

Scene generation is now **lazy per-config**: the orchestrator iterates over `schedule.json` entries and generates scene(s) for each config, reloading agent states between configs (to reflect re-planning changes).

For **normal scenes** (`is_free_period=false`):
- LOW density scenes roll against `trigger_probability` (default 15%). If they don't trigger, they're skipped entirely. If they trigger, density is upgraded to HIGH_LIGHT and a random classroom event is injected.
- Teacher presence is probabilistic: 20% during 晚自习, 5% during 课间.
- Present agents determined by location: 宿舍 → only dorm members; elsewhere → all students.

For **free period scenes** (`is_free_period=true` — 课间 08:45, 午饭 12:00, 课间 15:30):
1. Map config time to `LocationPreference` field (`"08:45"→morning_break`, `"12:00"→lunch`, `"15:30"→afternoon_break`)
2. Group students by their chosen location from daily plan
3. Create one Scene per occupied location with location-specific opening events from `data/location_events.json`
4. Scene name becomes `f"{config.name}@{location}"` (e.g. "课间@走廊", "午饭@食堂")
5. Sequential scene indices assigned starting from current index

Available locations: 课间 → 教室/走廊/操场/小卖部/图书馆/天台; 午饭 → 食堂/教室/操场/小卖部.

**Step 2a.1 — Re-planning** (between configs):
After all sub-scenes for a config complete, if the next config is a free period, "affected" agents may re-plan their location. An agent is affected if ANY of (checked from their individual `AgentReflection`):
- Their reflection produced any `new_concerns`
- Their reflection emotion is an extreme emotion (ANGRY, EXCITED, SAD, EMBARRASSED, JEALOUS, GUILTY, FRUSTRATED, TOUCHED)
- Any of their `relationship_changes` has |favorability| >= 8 or |trust| >= 8

Re-plan uses `replan.j2` template → `ReplanResult` (changed, new_location, reason). If changed, updates `location_preferences` for the next slot.

**Step 2b — Grouping** (`world/grouping.py`):
- First, identify solo agents (energy < 25, or introvert without close relationships at 50% chance, or sad + low energy at 60% chance).
- For 宿舍 scenes: group by dorm assignment.
- For other scenes: greedy affinity clustering (max group size 5). Affinity = bidirectional favorability + structural label bonus (室友 +20, 同桌 +15, 前后桌 +10) + same-gender bonus (+5, or +100 in dorms) + intention targeting bonus (+25 if either agent has an unfulfilled intention targeting the other by name) + random noise ±10.

**Deterministic scene generation**: Scene generation uses a per-day deterministic RNG seeded with `hash((base_seed, "scenes", day))`, separate from the main simulation RNG. This ensures the same set of LOW density scenes trigger on resume as on the original run, keeping `scene_index` values stable.

**Snapshot**: After grouping completes, mutable agent files (`state.json`, `relationships.json`, `key_memories.json`, `today.md`) are snapshotted to `world/snapshots/scene_N/<agent_id>/`. If the simulation is interrupted during the interaction phase and later resumed, the orchestrator detects the incomplete scene, restores agent files from the snapshot (reverting any partially-applied changes), resets the scene to the grouping phase, and re-runs it from scratch. A `.complete` marker ensures partially-written snapshots are discarded. Snapshots are cleared after each scene completes and at day boundaries (only when starting a fresh day, not on resume).

**Step 2c — Group Interaction: PDA Tick Loop** (`interaction/turn.py`):

Each tick, ALL agents in the group perceive the latest event, decide what to do, and a resolution step handles simultaneous actions. This replaces the old turn-based speaker selection system.

Tick loop (`run_group_dialogue`):
```
for tick in range(max_ticks_per_scene):
    1. PERCEIVE: all non-queued active agents concurrently (semaphore-throttled)
       - Build per-agent context via prepare_context() with PDA params:
         latest_event, scene_transcript, private_history, emotion_override, emotion_trace
       - emotion_trace: last 5 entries from per-agent emotion_history (tracked across ticks)
       - Render perception_decision.j2 template (shows emotion chain as "好奇 → 惊讶 → ..." when trace has >1 entry)
       - LLM returns PerceptionOutput: observation, inner_thought, emotion,
         action_type (speak/whisper/non_verbal/observe/exit),
         action_content, action_target, urgency (1-10), is_disruptive
    2. RESOLVE: resolve_tick() determines what happens (see PDA Tick Resolution)
    3. RECORD: store tick_record with all agent outputs + resolved actions
    4. UPDATE: latest_event for next tick from resolved actions
    5. CHECK: scene ends if consecutive_all_observe >= 3 and tick_count >= 3
```

- Tick 0 starts with `scene.opening_event` as the latest event (randomly selected from `schedule.json:opening_events` per scene config)
- Queued agents (losers from previous tick's speaker resolution) skip the PERCEIVE step and reuse their previous PerceptionOutput with +3 urgency per tick queued
- Narrative formatting (`interaction/narrative.py`):
  - `format_public_transcript()`: public events visible to all (speech, whisper notices, actions, exits). Mid-scene summarization after 12 ticks: ticks 1-6 are collapsed into a one-line summary
  - `format_agent_transcript()`: public view + agent's own prior observations and inner thoughts as private history
  - `format_latest_event()`: one-line summary of what just happened, used as the "latest event" for next tick's perception prompt

**Step 2c (solo)** — `interaction/solo.py`: If a group has `is_solo=true`, run `solo_reflection.j2` instead → returns `SoloReflection` with `inner_thought`, `emotion`, `activity`.

**Step 2d — Narrative Extraction + Per-Agent Self-Reflection** (two-phase post-dialogue):

After the dialogue ends, two types of LLM calls run **concurrently**:

**Phase 1: Narrative Extraction** (`interaction/scene_end.py`) — 1 LLM call:
- Build conversation log from tick_records using `format_public_transcript()` (includes speech, whisper notices, non-verbal actions, exits). Inner thoughts and observations are NOT included — extraction only sees externally observable behavior.
- `long_conversation` threshold: 12 ticks
- Feed the conversation log to LLM with `scene_end_analysis.j2` (analytical temperature 0.3) as a purely objective recorder
- Returns `NarrativeExtraction`:
  - `key_moments`: list of significant events as one-line summaries
  - `fulfilled_intentions`: list of "name:intention" strings
  - `events_discussed`: event IDs that were actually mentioned (updates `known_by`)
  - `new_events`: gossip/conflicts/decisions that may spread to other scenes

**Phase 2: Per-Agent Self-Reflection** (`interaction/self_reflection.py`) — N concurrent LLM calls:
- For each agent in the group, build an agent-specific prompt with:
  - Full agent context (profile, relationships, memories, concerns, self-narrative) via `prepare_context()`
  - Agent-specific conversation log via `format_agent_transcript()` (includes whispers the agent heard)
- Render `self_reflection.j2` template (reflection temperature 0.7)
- Each agent independently evaluates the conversation from their own perspective
- Returns `AgentReflection` per agent:
  - `emotion`: Emotion enum — agent's post-dialogue emotional state
  - `relationship_changes`: list of `AgentRelChange` (to_agent, favorability/trust/understanding deltas) — no from_agent needed since the reflection belongs to the focal agent
  - `memories`: list of `AgentMemoryCandidate` (text, emotion, importance, people, location, topics) — no agent field needed
  - `new_concerns`: list of `AgentConcernCandidate` — persistent emotional preoccupations from the agent's perspective (can be positive or negative, flagged via `positive` field)
  - `concern_updates`: list of `AgentConcernUpdate` — intensity adjustments to the agent's existing concerns
- Error handling: if an individual agent's reflection fails (LLM error, timeout), a default `AgentReflection()` is used (NEUTRAL emotion, no changes) so one failure doesn't block the group

This two-phase design enables **asymmetric perception**: the same conversation can produce different emotions, relationship changes, and memories for each participant, based on their personality, history, and existing concerns.

**Step 2e — Apply Results** (`interaction/apply_results.py`):
- For each agent in the group (using their individual `AgentReflection`):
  - Update emotion directly from reflection (Emotion enum, no try/except needed)
  - Append key moments from shared `NarrativeExtraction` to `today.md` (formatted as `## time scene @ location`)
  - Save key memories with importance >= 7 from agent's own reflection to `key_memories.json`
  - Apply relationship deltas from agent's own reflection using baseline snapshot (for idempotency): `new_value = baseline + delta`, clamped to valid range
  - Mark fulfilled intentions from shared `NarrativeExtraction` in `daily_plan`
  - Apply new concerns from agent's own reflection (structural dedup: same day + same scene + overlapping people = duplicate). Max 4 concerns; evicts lowest intensity if full. Propagates `positive` flag from `AgentConcernCandidate`.
  - Apply concern intensity adjustments from agent's own reflection (substring matching on concern text). Remove concerns that reach intensity <= 0.
- Update event queue from shared `NarrativeExtraction`: mark discussed events as known by all group members, add new events
- Save result file to `logs/day_NNN/scene_name/group_N_result.json` with `{"narrative": ..., "reflections": {...}, "baselines": ...}`

### Phase 3: Nightly Compression (`day_phase = "compression"`)

For each student (concurrently):
1. Read `today.md` content, active concerns, and unfulfilled intentions from daily plan
2. Call LLM with `nightly_compress.j2` → returns `CompressionResult`:
   - `daily_summary`: 1-2 sentence summary of the day. If there are unfulfilled intentions, the prompt asks the LLM to briefly note why (no opportunity? changed mind? interrupted?) — reflections enter `recent.md` with natural ~3 day half-life
   - `permanent_memories`: candidates with importance scores
   - `new_concerns`: concerns surfaced by reviewing the whole day (safety net for scene-end misses). Can be positive (positive=true) — e.g. anticipation, warmth
3. Append daily summary to `recent.md` as `# Day N` section
4. Save memories with importance >= 7 to `key_memories.json`
5. Apply new concerns (same structural dedup + eviction as scene-end, with `source_scene=""`)
6. Clear `today.md`

### End of Day

- Reset all students' energy to 85 (sleep)
- Decay all active concern intensities by 1 (remove when <= 0)
- Save trajectory data to `logs/day_NNN/trajectory.json`
- Expire events older than `event_expire_days` (default 3)
- Decrement `next_exam_in_days`
- Advance progress to next day

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
  intentions: list[Intention]    # max 3, each has target/goal/reason/fulfilled
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
source_scene: str                # e.g. "课间" — used for structural dedup
source_day: int
emotion: str                     # "羞耻"
intensity: int (1-10)            # Decays by 1 per day, removed at 0
related_people: list[str]
positive: bool                   # False=negative (worry/hurt), True=positive (warmth/excitement/anticipation)
```

Concerns are generated at two points: per-agent self-reflection (post-scene) and nightly compression. Structural dedup prevents duplicates (same day + same scene + overlapping people). Max 4 per agent; lowest intensity evicted when full (positive and negative concerns compete equally on intensity). Self-reflection `concern_updates` can adjust intensity up or down based on events (e.g. being comforted → -2, being mocked again → +3). Templates display positive concerns separately under "你最近心里期待的事" and negative concerns under "你最近心里挥之不去的事".

### Relationship (`models/relationship.py`)

```
target_name: str
target_id: str
favorability: int (-100 to 100)  # How much you like them
trust: int (-100 to 100)         # How much you trust them
understanding: int (0 to 100)    # How well you know them
label: str                       # 同学 | 室友 | 同桌 | 前后桌
recent_interactions: list[str]   # Last few key interactions
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

`SceneConfig` also has `opening_events: list[str]` — pool of environment descriptions for the PDA loop's initial tick, and `is_free_period: bool` — marks 课间/午饭 for location-split scene generation.

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
```

### Dialogue Models (`models/dialogue.py`)

```
ActionType: speak | whisper | non_verbal | observe | exit

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
  key_moments: list[str]                     # Significant events as one-line summaries
  fulfilled_intentions: list[str]            # "name:intention" format
  events_discussed: list[str]                # Event IDs
  new_events: list[NewEventCandidate]        # Gossip/conflicts that may spread

AgentReflection:                             # Per-agent subjective reflection (1 per agent per group)
  emotion: Emotion                           # Post-dialogue emotional state
  relationship_changes: list[AgentRelChange] # to_agent, favorability/trust/understanding deltas
  memories: list[AgentMemoryCandidate]       # text, emotion, importance, people, location, topics
  new_concerns: list[AgentConcernCandidate]  # text, source_event, emotion, intensity, related_people
  concern_updates: list[AgentConcernUpdate]  # concern_text, adjustment (±int)

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
next_exam_in_days: int           # Default 30, decremented daily
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

```
pressure = base + countdown_delta + exam_shock + recovery
```
- `base`: HIGH family → 50, MEDIUM → 30, LOW → 15
- `countdown_delta`: exam in ≤3 days → +15, ≤7 → +8, ≤14 → +3, else 0
- `exam_shock`: rank_drop × 2
- `recovery`: exam day resets to base, then -2/day

### Emotion Decay (`agent/state_update.py`)

Extreme emotions (angry, excited, sad, embarrassed, jealous, guilty, frustrated, touched) decay to neutral with 50% probability after 2+ scenes since onset.

### Concern Decay (`agent/state_update.py`)

All active concern intensities decrease by 1 at end of day. Concerns reaching intensity 0 are removed. This is the baseline decay — per-agent self-reflection `concern_updates` provide event-driven adjustments on top (concerns can be soothed faster by comforting interactions or intensified by triggering events).

### Exam Score Generation (`world/exam.py`)

Not LLM-driven — pure formula:
```
score = base(overall_rank) + subject_mod(±5 for strengths/weaknesses)
      + effort_mod(pressure/100 × attitude_coeff × 5) + gaussian_noise(0, variance)
```
- Base scores: top=88, 上游=78, 中上=70, 中游=62, 中下=54, 下游=45
- Variance inversely correlated with rank: top=3.0, 下游=10.0 (stronger students more consistent)
- Attitude coefficient maps `study_attitude` text → 0.0-1.2 multiplier
- Post-exam effects: rank drop ≥5 → SAD, rank rise ≥5 → EXCITED, high-pressure family + rank>5 → ANXIOUS, energy -15

### PDA Tick Resolution (`interaction/resolution.py`)

Pure Python, no LLM calls. Resolves one tick of the Perception-Decision-Action loop.

**State** (`ResolutionState`): tracks queued speakers (agent_id → PerceptionOutput + ticks_queued), consecutive all-observe count, tick count, and active agent set.

**Speaker arbitration**: when multiple agents want to SPEAK in the same tick, a resolution score determines who speaks:
```
resolution_score = urgency + bonuses
```
Bonuses:
- +5 if agent was addressed in the previous resolved speech (action_target matches agent name)
- +3 if agent has an unfulfilled intention targeting someone present
- +3 per tick queued (from previous ticks)

**Urgency clustering fallback**: if variance of urgency values among this tick's speakers is ≤ 2 (everyone equally urgent), bonuses become the primary signal and urgency is demoted to a 0.1× tiebreaker. This prevents urgency from dominating when LLM outputs cluster.

Ties broken randomly via the provided `rng`.

**Queue management**: losers are queued with their PerceptionOutput. Queued agents whose action_target has exited are discarded. Queued outputs expire after 3 ticks.

**Action resolution by type**:
| ActionType | Resolution |
|------------|-----------|
| SPEAK | Competes for single speaker slot via scoring |
| WHISPER | Goes to whisper_events as (from_id, to_id, content) |
| NON_VERBAL | All resolve simultaneously into resolved_actions. If is_disruptive=True, generates environmental_event string: `【动作】{name}: {content}` |
| OBSERVE | No action. Contributes to all-observe count |
| EXIT | Agent removed from active set |

**Scene termination**: scene ends when `consecutive_all_observe >= settings.consecutive_observe_to_end` (default 3) AND `tick_count >= settings.min_ticks_before_termination` (default 3). "All observe" requires all active agents chose OBSERVE and no queued speakers are waiting.

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

### Homeroom Teacher (`world/homeroom_teacher.py`)

Rule-driven, not a full agent:
- **Post-exam talks**: 70% chance of talking to students whose rank dropped by 3+. Creates a `teacher_talk` event with 0.7 spread probability.
- **Patrol events**: 30% chance during 晚自习/早读 of generating discipline/patrol events. During 上课, generates random classroom events (点名, 传纸条被发现, etc.).
- **Suppression effect**: When `teacher_present=true`, the perception template includes a warning ("班主任正在附近，说话注意点！") that naturally suppresses agent speech urgency.

---

## LLM Calls

All LLM calls go through `llm/client.py:structured_call()` which uses Instructor + LiteLLM to guarantee Pydantic model output. Each call has a dedicated Jinja2 template in `src/sim/templates/`.

| Call Type | Template | Response Model | Temperature | Max Tokens | Per Scene |
|-----------|----------|---------------|-------------|------------|-----------|
| Perception (PDA) | `perception_decision.j2` | `PerceptionOutput` | 0.9 | 32000 | N × ticks |
| Daily plan | `daily_plan.j2` | `DailyPlan` | 0.7 | 32000 | — |
| Solo reflection | `solo_reflection.j2` | `SoloReflection` | 0.9 | 32000 | 1 per solo |
| Narrative extraction | `scene_end_analysis.j2` | `NarrativeExtraction` | 0.3 | 32000 | 1 per group |
| Self-reflection | `self_reflection.j2` | `AgentReflection` | 0.7 | 32000 | N per group |
| Nightly compression | `nightly_compress.j2` | `CompressionResult` | 0.5 | 32000 | — |
| Self-narrative | `self_narrative.j2` | `SelfNarrativeResult` | 0.7 | 32000 | — |
| Re-plan | `replan.j2` | `ReplanResult` | 0.7 | 32000 | — |

Narrative extraction + N self-reflections run concurrently after each group dialogue (replacing the single `SceneEndAnalysis` call). Effective latency ≈ 1 LLM call despite N+1 total calls.

All templates include `system_base.j2` (shared system prompt establishing the Chinese high school setting, natural dialogue requirements, role consistency rules, few-shot examples of natural Chinese teen speech patterns, and inner_thought voice guidelines with bad/good examples to prevent self-analysis-report style thinking).

Context assembly (`agent/context.py:prepare_context()`):
- Profile summary (name, gender, personality, speaking style, academic rank/strengths/weaknesses/study attitude/homework habit/target, position, family expectation/situation, long-term goals, backstory, inner_conflicts)
- Relationships filtered to agents present in the scene
- Today's events so far (`today.md`)
- Recent memory (last 3 days from `recent.md`)
- Relevant key memories (tag-overlap retrieval, max 10)
- Pending unfulfilled intentions
- **Active concerns** — persistent emotional preoccupations (text, emotion, intensity)
- **Self-narrative** — periodic first-person identity reflection from `self_narrative.md`
- Scene info (time, location, who's present)
- Known events (gossip the agent knows about)
- Exam countdown context
- **Inner conflicts** — character's internal contradictions (e.g. "渴望友情但社交笨拙") from `inner_conflicts` field. Displayed in perception, daily plan, and self-narrative prompts as "你内心的矛盾" section
- PDA tick loop params (used by `perception_decision.j2`):
  - `latest_event`: what just happened (string)
  - `scene_transcript`: formatted public events so far
  - `private_history`: agent's own prior observations + inner thoughts
  - `tick_emotion`: in-memory emotion override (updated each tick without persisting to state)
  - `emotion_trace`: last 5 emotion values from the current scene's tick history (displayed as "你的情绪变化" chain when >1 entry)

Every LLM call is logged to `logs/day_NNN/scene_name/group_id/calltype_timestamp.json` with full input/output, latency, and token counts. Costs are appended to `logs/costs.jsonl`.

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
    self_narrative.md            # Periodic first-person self-reflection (regenerated every N days)
    key_memories.json            # Permanent memories (importance >= 7)
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
    trajectory.json              # Per-agent location/emotion trajectory for frontend
    scene_name/
      group_N_result.json        # Narrative + per-agent reflections + baselines
      group_id/
        calltype_timestamp.json  # Individual LLM call logs

tests/                           # Unit tests (pytest)
  test_resolution.py             # PDA tick resolution logic (31 tests)
  test_narrative.py              # Transcript formatting and summarization
  test_models.py                 # Pydantic model validation (PerceptionOutput, ActionType)

scripts/
  init_world.py                  # Initialize agents/ and world/ from data/characters/
  inspect_state.py               # Debug tool to view current simulation state

src/sim/
  main.py                        # CLI entry point (argparse → Orchestrator.run)
  config.py                      # Settings via pydantic-settings (SIM_ env prefix)
  models/                        # Pydantic models (agent, dialogue, event, memory, progress, relationship, scene, trajectory)
  agent/                         # Agent-level logic
    storage.py                   # AgentStorage + WorldStorage (file I/O, atomic writes)
    context.py                   # prepare_context() — assembles full LLM context for an agent
    daily_plan.py                # generate_daily_plan() — morning intention + location generation
    self_narrative.py            # generate_self_narrative() — periodic identity reflection
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
    orchestrator.py              # Orchestrator — main simulation loop
    turn.py                      # run_perception() + run_group_dialogue() — PDA tick loop
    resolution.py                # resolve_tick() — PDA tick resolution (speaker arbitration, queue, scene end)
    narrative.py                 # format_public_transcript(), format_agent_transcript(), format_latest_event()
    scene_end.py                 # run_scene_end_analysis() — objective narrative extraction (post-dialogue)
    self_reflection.py           # run_agent_reflection() + run_all_reflections() — per-agent subjective reflection
    apply_results.py             # apply_scene_end_results() + apply_solo_result()
    solo.py                      # run_solo_reflection() — solo agent inner monologue
  llm/                           # LLM infrastructure
    client.py                    # structured_call() via Instructor + LiteLLM
    prompts.py                   # render() — Jinja2 template rendering
    logger.py                    # log_llm_call() — per-call JSON logging + cost tracking
  memory/                        # Memory management
    compression.py               # nightly_compress() — summarize today → recent, extract key memories
    retrieval.py                 # get_relevant_memories() — tag-overlap retrieval
    writer.py                    # Helper wrappers for today.md and key_memory writes
  templates/                     # Jinja2 prompt templates (all in Chinese)
    system_base.j2               # Shared system prompt (high school setting + dialogue rules + few-shot teen speech examples)
    perception_decision.j2       # PDA tick loop perception prompt (+ concerns split by positive/negative + inner conflicts + emotion trace + self-narrative context)
    dialogue_turn.j2             # Legacy per-turn dialogue (kept for A/B comparison reference)
    daily_plan.j2                # Morning plan + location preference generation (+ concerns split by positive/negative + inner conflicts + need-awareness prompt + self-narrative)
    solo_reflection.j2           # Solo inner monologue (+ concerns + self-narrative)
    scene_end_analysis.j2        # Post-dialogue analysis (+ concern generation + concern updates)
    nightly_compress.j2          # Daily summary (with failure reflection for unfulfilled intentions) + permanent memory + concern extraction (supports positive concerns)
    self_narrative.j2            # Periodic first-person self-reflection generation
    replan.j2                    # Reactive location re-planning between scenes
```

---

## Configuration (`config.py`)

All settings via `pydantic-settings` `BaseSettings`, loaded from `.env` file, overridable with `SIM_` env prefix:

| Setting | Default | Description |
|---------|---------|-------------|
| `llm_model` | `deepseek/deepseek-chat` | LiteLLM model identifier |
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
| `max_ticks_per_scene` | 30 | Hard cap on ticks per PDA scene |
| `min_ticks_before_termination` | 3 | Minimum ticks before scene can end |
| `consecutive_observe_to_end` | 3 | Consecutive all-observe ticks to trigger scene end |
| `perception_temperature` | 0.9 | PDA perception LLM call temperature |
| `max_tokens_perception` | 32000 | PDA perception max tokens |
| `max_concurrent_llm_calls` | 5 | Async semaphore limit |
| `exam_interval_days` | 30 | Days between exams |
| `event_expire_days` | 3 | Days before events become inactive |
| `recent_md_max_weeks` | 4 | Rolling window for recent.md |
| `max_key_memories` | 10 | Max key memories in context |
| `solo_energy_threshold` | 25 | Energy below this → solo |
| `free_period_locations` | 教室,走廊,操场,小卖部,图书馆,天台 | Valid locations for 课间 |
| `lunch_locations` | 食堂,教室,操场,小卖部 | Valid locations for 午饭 |
| `self_narrative_interval_days` | 3 | Days between self-narrative regeneration |
| `self_narrative_temperature` | 0.7 | Self-narrative LLM temperature |
| `max_tokens_self_narrative` | 32000 | Self-narrative max tokens |
| `replan_temperature` | 0.7 | Re-plan LLM temperature |
| `max_tokens_replan` | 32000 | Re-plan max tokens |
| `max_active_concerns` | 4 | Max concerns per agent |

---

## Initialization (`scripts/init_world.py`)

1. Wipes `agents/`, `world/`, and `logs/` directories
2. For each character in `data/characters/*.json`:
   - Copies profile to `agents/<id>/profile.json`
   - Creates initial state (energy=85, pressure based on family: 高→60, 中→35, 低→15, emotion=neutral, active_concerns=[])
   - Creates relationships from preset pairs (defined in `PRESET_RELATIONSHIPS` — roommates, seatmates, desk neighbors with initial favorability/trust values)
   - Creates empty `key_memories.json`, `today.md`, `recent.md`, `self_narrative.md`
3. Creates `world/progress.json` (day 1, daily_plan phase, next_exam_in_days=30)
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

- **Atomic writes** (`agent/storage.py:atomic_write_json`): All JSON writes use temp file + `os.fsync` + `os.replace` to prevent corruption on crash.
- **Checkpoint-based recovery**: Every phase transition saves progress. On restart, the orchestrator skips completed phases/scenes/groups. Group status tracks: `pending` → `llm_done` → `applied`.
- **Pre-scene snapshot/restore**: Before interaction begins, agent files are snapshotted. If the scene is interrupted and resumed, the snapshot is restored, the scene resets to grouping, and re-runs from scratch. This prevents silent scene skips caused by lost in-memory group assignments and avoids double-applying partially-written state changes.
- **Per-day deterministic scene generation**: Scene generation uses a separate RNG seeded with `hash((base_seed, "scenes", day))`, ensuring the scene list (which LOW density scenes triggered) is identical across resume. The base seed is persisted in `progress.json` on first run; resume always reloads it. CLI `--seed` overrides the saved seed. Without this, the main RNG's consumption history would differ on resume, causing scene indices to shift.
- **Idempotent result application**: Scene-end results are saved with baseline relationship snapshots. Deltas are applied to baselines, not current values, so re-applying the same result is safe.
- **Structured LLM output**: All LLM calls use Instructor's `response_model` parameter to guarantee Pydantic model parsing. No free-form text parsing anywhere.
- **Async concurrency**: Daily plans and nightly compression run all agents concurrently, throttled by `asyncio.Semaphore(max_concurrent_llm_calls)`. Scene execution is sequential (each scene depends on the previous scene's state changes).
- **Name ↔ ID mapping**: LLM prompts use Chinese names (林昭宇). Code uses snake_case IDs (lin_zhaoyu). `name_to_id` mapping is built from profiles during result application.
