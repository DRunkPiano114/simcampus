"""M1: Ungrounded events.

Counts LLM-grounded events in `world/event_queue.json` whose `cite_ticks`
are missing or do not resolve to any tick visible to the LLM in the
specific group the event came out of. The 3-layer validation in
`apply_scene_end_results` should make this 0 on a clean run.

Scope: only events with `group_index is not None` are checked.
System-generated events (e.g. HomeroomTeacher.post_exam_actions) leave
group_index=None and are excluded from both numerator and denominator —
they were never claimed to be LLM-grounded.

Per-group scoping: cite_ticks are group-local (each group's tick numbering
starts at 0), so validation must scope by (scene_name, group_index)
rather than unioning visible ticks across groups of the same scene.

Events without cite_ticks or group_index are silently skipped. For a
clean baseline, run after a fresh `init_world.py + sim --days N` rerun.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sim.config import settings  # noqa: E402


def _scene_files_for_day(day: int) -> list[Path]:
    day_dir = settings.logs_dir / f"day_{day:03d}"
    if not day_dir.exists():
        return []
    return sorted(p for p in day_dir.glob("*.json") if not p.name.startswith("scenes"))


def _visible_ticks_for_group(group: dict) -> set[int]:
    """Return the 1-indexed tick numbers visible to the LLM for one group.

    Mirrors narrative.py: when a group has > 12 ticks, ticks 0-5 (0-indexed)
    are summarized away and the LLM only sees ticks 6+ as raw tick lines.
    """
    ticks = group.get("ticks") or []
    if not ticks:
        return set()
    cutoff = 6 if len(ticks) > 12 else 0
    return {t.get("tick", 0) + 1 for t in ticks if t.get("tick", 0) >= cutoff}


def _build_group_index(day: int) -> dict[tuple[str, int], set[int]]:
    """Build {(scene_name, group_index): visible_ticks_set} for one day.

    The key is the same (scene, group) pair we now persist on Event, so M1
    can do a direct lookup instead of fuzzy unioning across groups.
    """
    index: dict[tuple[str, int], set[int]] = {}
    for path in _scene_files_for_day(day):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        scene_name = data.get("scene", {}).get("name", "")
        for group in data.get("groups") or []:
            gi = group.get("group_index")
            if gi is None:
                continue
            index[(scene_name, gi)] = _visible_ticks_for_group(group)
    return index


def run() -> dict:
    eq_path = settings.world_dir / "event_queue.json"
    if not eq_path.exists():
        return {"status": "MISSING", "ungrounded": 0, "total": 0}

    eq = json.loads(eq_path.read_text(encoding="utf-8"))
    all_events = eq.get("events", [])

    # Only LLM-grounded events are in scope. System-generated events
    # (homeroom teacher post-exam talks, etc.) leave group_index=None
    # and are excluded from both numerator and denominator.
    in_scope = [e for e in all_events if e.get("group_index") is not None]

    # Lazy per-day cache so we only read each day's scene files once
    day_cache: dict[int, dict[tuple[str, int], set[int]]] = {}

    ungrounded: list[dict] = []
    for event in in_scope:
        cite = event.get("cite_ticks")
        if not cite:
            ungrounded.append({
                "id": event.get("id"),
                "text": event.get("text", "")[:60],
                "reason": "no cite_ticks",
            })
            continue

        day = event.get("source_day", 0)
        if day not in day_cache:
            day_cache[day] = _build_group_index(day)
        scene_groups = day_cache[day]
        key = (event.get("source_scene", ""), event.get("group_index"))
        visible = scene_groups.get(key)

        if visible is None:
            ungrounded.append({
                "id": event.get("id"),
                "text": event.get("text", "")[:60],
                "reason": f"scene/group {key} not found in logs",
            })
            continue

        if not all(t in visible for t in cite):
            ungrounded.append({
                "id": event.get("id"),
                "text": event.get("text", "")[:60],
                "reason": f"cite {cite} not in group's visible ticks {sorted(visible)[:5]}...",
            })

    return {
        "status": "PASS" if not ungrounded else "FAIL",
        "ungrounded": len(ungrounded),
        "total": len(in_scope),
        "total_all_events": len(all_events),
        "skipped_system_events": len(all_events) - len(in_scope),
        "details": ungrounded[:10],
    }


def main() -> int:
    result = run()
    print(f"M1 ungrounded_events: {result['status']} "
          f"(ungrounded={result['ungrounded']}/{result['total']})")
    for d in result.get("details", []):
        print(f"  - {d['id']}: {d['text']} → {d['reason']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
