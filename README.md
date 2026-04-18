# SimCampus

**[Live Demo](https://www.simcampus.top/)** · [中文](README.zh.md) · [MIT License](LICENSE)

A multi-agent LLM simulation engine. Define a cast of characters — each with a personality, goals, concerns, and relationships — plus a daily schedule of shared scenes, and the simulation runs day-by-day, producing emergent dialogue, memories, and narrative with no hand-written script.

---

## Table of Contents

- [What is this](#what-is-this)
- [Quick Start](#quick-start)
- [Customize the cast](#customize-the-cast)

---

## What is this

Each character is an independent agent with:

- A **profile** (personality, backstory, goals, behavioral anchors) — immutable during simulation
- **State** — emotion, energy, and up to 4 active concerns (each with intensity 1–10 and a TTL)
- **Memory** — up to 10 key memories ranked by importance, a self-narrative refreshed every few days, and a rolling recent log
- **Relationships** with every other agent, quantified by favorability, trust, and understanding

Simulating one day means running every scene in the daily schedule. Inside each scene, agents perceive, think, speak, and act; after scenes end, they summarize, write memories, and update relationships and concerns. Storage is flat JSON + Markdown — no database; every file is directly inspectable.

**Why it's worth a look:**

- **Agents with minds** — dialogue is driven by concerns and intentions, not random chatter. Agents recall and cite events from days ago.
- **Configurable daily loop** — scenes, density, grouping rules, and free periods all live in `canon/worldbook/schedule.json`.
- **Emergent narrative** — run enough days and multi-day storylines surface on their own: rumors propagate, rivalries form, alliances shift.
- **Whole cast is replaceable** — edit `canon/cast/profiles/*.json` to swap in your own scenario.

## Quick Start

### A. Explore the shipped demo (no API key needed)

The repo ships with a 9-day pre-run simulation, already exported to the frontend. Prereqs: Node 18+ with [pnpm](https://pnpm.io/).

```bash
cd web
pnpm install
pnpm dev # → http://localhost:5173
```

Open the URL in your browser and click around — daily report, pixel world, character archive, relationship graph.


### B. Run your own simulation

> Want to build a highschool with your own characters? See [Customize the cast](#customize-the-cast) to edit character profiles first.

Prereqs: Python 3.12+ via [uv](https://docs.astral.sh/uv/), Node 18+ with [pnpm](https://pnpm.io/), plus an LLM provider API key. Defaults to **OpenRouter** (Gemini 3.1 Flash Lite as primary model, cheap and stable); DeepSeek / OpenAI / Anthropic also supported via LiteLLM.

> **Heads up**: step 2 below wipes `simulation/state|world|days` — including the pre-run data.

```bash
uv sync

# Configure your LLM API key
cp .env.example .env
# Edit .env and fill in OPENROUTER_API_KEY (or switch to another provider — see .env.example notes + src/sim/config.py)

# Initialize the world
uv run python scripts/init_world.py

# Run 5 days of simulation
uv run sim --days 5

# Start the API server — required for Role Play / God Mode chat in the frontend.
# Run in a separate terminal.
uv run api                           # → http://localhost:8000

# Export to the frontend + view
uv run python scripts/export_frontend_data.py
cd web && pnpm install && pnpm dev   # → http://localhost:5173
```


## Customize the cast

Edit `canon/cast/profiles/*.json` — one file per character.

### Hard constraint

**Do not add, remove, or rename `agent_id` slots.** The slot set is hardcoded across the codebase:

- `scripts/init_world.py` → `PRESET_RELATIONSHIPS`
- `src/sim/world/scene_generator.py` → location and grouping logic
- `src/sim/interaction/orchestrator.py` → special-role hook
- `src/sim/world/homeroom_teacher.py` → special-role logic

**Replace the content of each slot, never the slot itself.** Adding/removing slots requires coordinated edits across these files — out of scope for the standard workflow.

### Option 1: edit by hand

1. Open `canon/cast/profiles/<id>.json` and edit against the schema in `src/sim/models/agent.py` (`AgentProfile`)
2. Validate JSON + Pydantic:
   ```bash
   python -m json.tool canon/cast/profiles/<id>.json > /dev/null
   uv run python -c "from src.sim.models.agent import AgentProfile; AgentProfile.model_validate_json(open('canon/cast/profiles/<id>.json').read())"
   ```
3. If relationships changed, sync `PRESET_RELATIONSHIPS` in `scripts/init_world.py`
4. Rebuild the world (**this wipes `simulation/state|world|days`**, including all past runs):
   ```bash
   uv run python scripts/init_world.py
   uv run sim --days 5
   ```

### Option 2: let an AI agent do it (recommended)

Paste this to Claude Code / Cursor / Codex:

> I want to use this project to simulate my own scenario. Please follow the workflow in `skills/build-cast.md` to guide me through editing the characters.

The agent reads the schema, asks you for fields in batches, polishes backstory drafts, validates JSON, updates the relationship preset, and tells you what to run next. A full cast swap takes 30–60 minutes of back-and-forth.
