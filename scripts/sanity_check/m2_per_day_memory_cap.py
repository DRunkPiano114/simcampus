"""M2: Per-day memory cap.

Walks every agent's `key_memories.json` and counts memories per day. Any
agent holding more than `settings.per_day_memory_cap` memories on a single
day is a violation — the post-pass cap in `nightly_compress` should keep
this at zero on a clean run.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sim.config import settings  # noqa: E402


def run() -> dict:
    cap = settings.per_day_memory_cap
    violations: list[dict] = []
    total_memories = 0

    for agent_dir in sorted(settings.agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        km_path = agent_dir / "key_memories.json"
        if not km_path.exists():
            continue
        km = json.loads(km_path.read_text(encoding="utf-8"))
        memories = km.get("memories", [])
        total_memories += len(memories)

        per_day: dict[int, int] = defaultdict(int)
        for m in memories:
            per_day[m.get("day", 0)] += 1

        for day, count in per_day.items():
            if count > cap:
                violations.append({
                    "agent": agent_dir.name,
                    "day": day,
                    "count": count,
                })

    return {
        "status": "PASS" if not violations else "FAIL",
        "cap": cap,
        "total_memories": total_memories,
        "violations": violations,
    }


def main() -> int:
    result = run()
    print(f"M2 per_day_memory_cap: {result['status']} "
          f"(cap={result['cap']}, total_memories={result['total_memories']}, "
          f"violations={len(result['violations'])})")
    for v in result["violations"][:10]:
        print(f"  - {v['agent']} day {v['day']}: {v['count']} memories (cap {result['cap']})")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
