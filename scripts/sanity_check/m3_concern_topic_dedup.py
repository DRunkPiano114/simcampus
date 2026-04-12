"""M3: Concern topic dedup audit.

Walks every agent's state.json and audits whether `add_concern` is doing
its job. The merge rules in apply_results.py are:

  - Categorized topics (everything except 其他): same topic + any non-empty
    related_people overlap → merge into one concern.
  - 其他: same topic + EXACT related_people set match → merge. Empty-people
    其他 buckets never merge (Frankenstein guard).

Multiple concerns under the same categorized topic are legitimate when
the people sets are disjoint — one 学业焦虑 about 张伟 and another about
李明 are two separate worries, not a merge bug.

Pass condition: for every agent, no pair of same-topic concerns has
overlapping people. The 其他 bucket is reported as OBSERVE only because
its merge rule is intentionally strict and multiple coexisting entries
are expected.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sim.config import settings  # noqa: E402


def _has_people_overlap(a: dict, b: dict) -> bool:
    """Two concerns share at least one person — the only signal that
    `add_concern` should have merged them but didn't."""
    pa = set(a.get("related_people") or [])
    pb = set(b.get("related_people") or [])
    return bool(pa & pb)


def run() -> dict:
    violations: list[dict] = []  # categorized topics with people overlap
    other_observations: list[dict] = []  # 其他 bucket observations (informational)
    multiple_disjoint: list[dict] = []  # categorized topics with multiple but disjoint people (legitimate)
    total_concerns = 0

    for agent_dir in sorted(settings.agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        state_path = agent_dir / "state.json"
        if not state_path.exists():
            continue
        state = json.loads(state_path.read_text(encoding="utf-8"))
        concerns = state.get("active_concerns", [])
        total_concerns += len(concerns)

        per_topic: dict[str, list[dict]] = defaultdict(list)
        for c in concerns:
            per_topic[c.get("topic", "其他")].append(c)

        for topic, items in per_topic.items():
            if len(items) <= 1:
                continue
            if topic == "其他":
                # Frankenstein guard intentionally lets multiple coexist;
                # report as OBSERVE only.
                other_observations.append({
                    "agent": agent_dir.name,
                    "topic": topic,
                    "count": len(items),
                })
                continue

            # Check every pair for people overlap. Any overlap = add_concern
            # missed a merge it should have made.
            overlapping_pairs: list[tuple[str, str]] = []
            for a, b in combinations(items, 2):
                if _has_people_overlap(a, b):
                    overlapping_pairs.append((
                        ",".join(sorted(a.get("related_people") or [])) or "(空)",
                        ",".join(sorted(b.get("related_people") or [])) or "(空)",
                    ))

            if overlapping_pairs:
                violations.append({
                    "agent": agent_dir.name,
                    "topic": topic,
                    "count": len(items),
                    "overlapping_pairs": overlapping_pairs,
                })
            else:
                # Multiple concerns same topic but disjoint people — legitimate
                multiple_disjoint.append({
                    "agent": agent_dir.name,
                    "topic": topic,
                    "count": len(items),
                })

    return {
        "status": "PASS" if not violations else "FAIL",
        "total_concerns": total_concerns,
        "violations": violations,
        "other_observations": other_observations,
        "multiple_disjoint": multiple_disjoint,
    }


def main() -> int:
    result = run()
    print(f"M3 concern_topic_dedup: {result['status']} "
          f"(total_concerns={result['total_concerns']}, "
          f"violations={len(result['violations'])})")
    for v in result["violations"][:10]:
        pairs = "; ".join(f"[{a}] vs [{b}]" for a, b in v["overlapping_pairs"][:3])
        print(f"  - {v['agent']}: topic '{v['topic']}' has {v['count']} entries with people overlap → {pairs}")
    if result["multiple_disjoint"]:
        print(f"  multiple disjoint (legitimate, informational):")
        for o in result["multiple_disjoint"][:5]:
            print(f"    - {o['agent']}: topic '{o['topic']}' has {o['count']} entries (disjoint people)")
    if result["other_observations"]:
        print(f"  其他 bucket observations (Frankenstein guard, informational):")
        for o in result["other_observations"][:5]:
            print(f"    - {o['agent']}: {o['count']} entries")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
