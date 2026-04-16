# SimCampus

Multi-agent LLM simulation of a Chinese high school class. AI-powered students and a teacher live through three years of school life — attending classes, forming friendships, navigating conflicts, and growing up — generating emergent narratives with no human intervention.

## Tech Stack

- **Simulation** — Python 3.12+, DeepSeek V3.2 (via LiteLLM), Instructor, Pydantic, Jinja2
- **Frontend** — React 19, TypeScript, PixiJS, D3, Tailwind CSS, Vite
- **Storage** — flat JSON + Markdown files (no database)

## Quick Start

```bash
uv sync                                          # install dependencies
uv run python scripts/init_world.py              # init world (wipes simulation/state/, simulation/world/, simulation/days/)
uv run sim --days 5                              # run simulation
uv run sim --days 1 --start-day 3 --seed 42      # resume from day 3, reproducible
```

## Customize Your Class

The default cast is a Chinese high school class — 10 students and 1 homeroom
teacher (`he_min`). To run the simulation with your own characters, edit
`canon/cast/profiles/*.json` (one file per character).

**Important constraint**: don't add, remove, or rename `agent_id` slots. The
10 student slots + `he_min` are hardcoded in `scripts/init_world.py`,
`src/sim/world/scene_generator.py`, `src/sim/interaction/orchestrator.py`, and
`web/src/components/world/CharacterSprite.ts`. Replace the *content* of each
slot, not the slot itself.

### For humans (manual editing)

1. Open a file under `canon/cast/profiles/` and modify the fields. Schema is
   defined in `src/sim/models/agent.py` (`AgentProfile`).
2. Validate after editing:
   ```bash
   python -m json.tool canon/cast/profiles/<id>.json > /dev/null
   uv run python -c "from src.sim.models.agent import AgentProfile; AgentProfile.model_validate_json(open('canon/cast/profiles/<id>.json').read())"
   ```
3. Rebuild the world (this **wipes** `simulation/state/`, `simulation/world/`,
   and `simulation/days/`, including all previous runs):
   ```bash
   uv run python scripts/init_world.py
   uv run sim --days 5
   ```

If you change relationships between characters, also edit
`PRESET_RELATIONSHIPS` in `scripts/init_world.py`.

### For coding agents (Claude Code, Cursor, Codex, …)

Paste this to your agent:

> I want to use this project to simulate my own class. Please follow the workflow in `skills/build-cast.md` to guide me through editing the characters.

The agent will read the schema, walk you through fields batch-by-batch,
validate the JSON, update relationship presets if needed, and tell you what
to run next.

## Inspect & Export

```bash
uv run python scripts/inspect_state.py           # inspect state (--agent lin_zhaoyu / --world)
uv run python scripts/export_frontend_data.py    # export sim data → web/public/data/
```

## 素材配置 (Art Assets)

Share-card rendering needs the LimeZu Modern Interiors premade sprite sheets
and a few UI theme packs. These are **commercial assets** and are not in git.
Place them locally before running anything under `src/sim/cards/`:

```bash
cp -r /path/to/your/assets/* ./assets/
# ./assets/moderninteriors-win/... and ./assets/Complete_UI_Essential_Pack_v2.4/...
```

Contents of `./assets/` are gitignored by default; only `./assets/fonts/`
(OFL-licensed Chinese fonts) is whitelisted and tracked. The **derived** 10
character portrait PNGs under `canon/cast/portraits/` *are* checked in so
freshly cloned workspaces can render cards without re-running the generator.

**Convention:** after editing `canon/cast/visual_bible.json` (sprite_source or
crop fields), re-run the portrait generator or the PNGs will drift from the
config:

```bash
uv run python scripts/generate_portraits.py     # regenerate canon/cast/portraits/*.png
uv run python -m sim.cards.self_test            # sanity-check → .cache/self_test/
```

The share-card render cache lives in `.cache/cards/` (gitignored). After a sim
rerun, clear it so cards reflect the new data:

```bash
rm -rf .cache/cards
```

## API Server

```bash
uv run api                                       # start API at localhost:8000
```

God Mode and Role Play chat features require the API server running alongside the frontend.

## Frontend

```bash
cd web && pnpm install                           # install dependencies
cd web && pnpm dev                               # dev server at localhost:5173
cd web && pnpm build                             # production build → web/dist/
```

## Tests

```bash
uv run python -m pytest                         # run all Python tests
uv run python -m pytest tests/test_foo.py -v    # run one test file, verbose
uv run python -m pytest -k "test_name"          # run tests matching a name
cd web && pnpm vitest run                       # run frontend unit tests
```

