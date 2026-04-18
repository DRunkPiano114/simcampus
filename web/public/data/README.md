# Generated data — do not edit

These files are the frontend's runtime data and visual assets. They are
**generated artifacts**; hand edits will be overwritten the next time
the corresponding pipeline runs.

## What lives here

| Path | Produced by | Source |
| --- | --- | --- |
| `days/`, `agents/`, `daily/`, `meta.json`, `events.json`, `agent_colors.json` | `scripts/export_frontend_data.py` | `simulation/` + `canon/` |
| `portraits/` | `scripts/generate_portraits.py` | `assets/` (LimeZu sprite sheets) + `canon/cast/visual_bible.json` |
| `animated/` | `scripts/generate_animated.py` | `assets/` sprite sheets |
| `balloons/` | `scripts/generate_balloons.py` | `assets/` (wento balloon pack) |
| `map_sprites/`, `tilesets/` | `scripts/generate_map_sprites.py`, `scripts/generate_tilesets.py` | `assets/` tilesets |

## Regenerate

Narrative data (most common — rerun after every sim run):

```
uv run python scripts/export_frontend_data.py
```

Visual assets (only needed when sprite sheets or `visual_bible.json`
change — rare):

```
uv run python scripts/generate_portraits.py
uv run python scripts/generate_animated.py
# etc. — see scripts/ for the full set
```
