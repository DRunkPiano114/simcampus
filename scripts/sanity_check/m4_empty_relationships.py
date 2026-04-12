"""M4: Empty relationships.

Walks every agent's `relationships.json` and reports any agent whose
relationship map is empty. After a few simulated days every active student
should have at least one relationship — `apply_scene_end_results`
auto-inserts a zero-state entry the first time the LLM mentions another
agent, so empty maps signal something has gone wrong upstream.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sim.config import settings  # noqa: E402


def run() -> dict:
    empty_agents: list[str] = []
    total_agents = 0

    for agent_dir in sorted(settings.agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        rels_path = agent_dir / "relationships.json"
        if not rels_path.exists():
            empty_agents.append(agent_dir.name)
            continue
        rels = json.loads(rels_path.read_text(encoding="utf-8"))
        total_agents += 1
        if not rels.get("relationships"):
            empty_agents.append(agent_dir.name)

    return {
        "status": "PASS" if not empty_agents else "FAIL",
        "total_agents": total_agents,
        "empty_agents": empty_agents,
    }


def main() -> int:
    result = run()
    print(f"M4 empty_relationships: {result['status']} "
          f"(empty={len(result['empty_agents'])}/{result['total_agents']})")
    for a in result["empty_agents"]:
        print(f"  - {a}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
