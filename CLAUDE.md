# CLAUDE.md

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
