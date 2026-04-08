# SimClass

Multi-agent LLM simulation of a Chinese high school class. AI-powered students and a teacher live through three years of school life — attending classes, forming friendships, navigating conflicts, and growing up — generating emergent narratives with no human intervention.

## Tech Stack

- **Simulation** — Python 3.12+, DeepSeek V3.2 (via LiteLLM), Instructor, Pydantic, Jinja2
- **Frontend** — React 19, TypeScript, PixiJS, D3, Tailwind CSS, Vite
- **Storage** — flat JSON + Markdown files (no database)

## Quick Start

```bash
uv sync                                          # install dependencies
uv run python scripts/init_world.py              # init world (wipes agents/ and world/)
uv run sim --days 5                              # run simulation
uv run sim --days 1 --start-day 3 --seed 42      # resume from day 3, reproducible
```

## Inspect & Export

```bash
uv run python scripts/inspect_state.py           # inspect state (--agent lin_zhaoyu / --world)
uv run python scripts/export_frontend_data.py    # export sim data → web/public/data/
```

## Frontend

```bash
cd web && pnpm install                           # install dependencies
cd web && pnpm dev                               # dev server at localhost:5173
cd web && pnpm build                             # production build → web/dist/
```

## Tests

```bash
uv run python -m pytest                         # run all tests
uv run python -m pytest tests/test_foo.py -v    # run one test file, verbose
uv run python -m pytest -k "test_name"          # run tests matching a name
```

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — full technical deep-dive (data models, simulation loop, LLM integration, algorithms)
