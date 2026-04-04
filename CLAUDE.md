# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                          # Install dependencies
uv run python scripts/init_world.py              # Init world (wipes agents/ and world/)
uv run sim --days 5                              # Run simulation
uv run sim --days 1 --start-day 3 --seed 42      # Resume from day 3, reproducible
uv run python scripts/inspect_state.py           # Inspect state (--agent lin_zhaoyu / --world)
```

No tests or linting configured. Env: `cp .env.example .env` then set `DEEPSEEK_API_KEY`.

## Documentation Sync Rule

Detailed technical documentation lives in `ARCHITECTURE.md`. **Every time you modify code, you MUST also update that file to reflect the changes.** A task is not complete until the doc is in sync.

What triggers a doc update:
- Add/remove/rename a module or file
- Change a data model (add/remove/rename fields)
- Change the simulation loop, phase logic, or orchestration flow
- Change algorithms (grouping, speaker selection, energy, pressure, exam scoring, etc.)
- Add/change LLM call types, templates, or temperature/token settings
- Add/change configuration options
- Change file storage format, paths, or initialization logic

The goal: a stranger should be able to fully understand this project's technical implementation, engineering details, and framework logic by reading `ARCHITECTURE.md` alone, without looking at source code.

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
