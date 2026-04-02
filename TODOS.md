# TODOS

## Phase 2: Legendary Episodes (Agent-Initiated Micro-Events)

**What:** Allow agents to propose micro-events (secret notes, classroom incidents, overheard conversations) that propagate between scenes via the event queue.

**Why:** Adds narrative agency beyond conversational autonomy. Agents don't just react to scenes, they create drama. Codex independently proposed this as the "coolest version" of the simulation.

**Pros:**
- Emergent storylines that span multiple scenes (a secret note in 课间 becomes gossip at 午饭)
- Leverages the existing `event_queue.py` spread_probability mechanics
- Makes the simulation genuinely surprising, even to the creator

**Cons:**
- Requires a new action type or intention mechanism in PerceptionOutput
- Risk of event spam if not gated (agents proposing too many events)
- Needs tuning: which events are worth spreading vs. noise

**Context:** The event queue system (`src/sim/world/event_queue.py`) already handles event creation, spread probability, witness tracking, and expiry. Phase 2 would add: (1) a `PROPOSE_EVENT` action type in PerceptionOutput, or (2) a post-scene "reflection" step where agents can propose events based on what happened. The design doc from /office-hours defers this explicitly. Build after the PDA loop is stable and producing good output.

**Depends on:** PDA loop implementation (Phase 1) must be complete and stable.
