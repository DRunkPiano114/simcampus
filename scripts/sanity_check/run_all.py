"""Run all M1-M6 sanity checks and emit a Markdown summary.

Output goes to stdout — typical usage:
    uv run python scripts/sanity_check/run_all.py > docs/PHASE1_RESULTS.md
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))   # so sibling m*.py modules import directly
sys.path.insert(0, str(ROOT / "src"))  # so sim.* imports work

import m1_ungrounded_events  # noqa: E402
import m2_per_day_memory_cap  # noqa: E402
import m3_concern_topic_dedup  # noqa: E402
import m4_empty_relationships  # noqa: E402
import m5_positive_emotion_ratio  # noqa: E402
import m6_per_agent_memory_count  # noqa: E402


CHECKS = [
    ("M1", "ungrounded_events", m1_ungrounded_events.run),
    ("M2", "per_day_memory_cap", m2_per_day_memory_cap.run),
    ("M3", "concern_topic_dedup", m3_concern_topic_dedup.run),
    ("M4", "empty_relationships", m4_empty_relationships.run),
    ("M5", "positive_emotion_ratio", m5_positive_emotion_ratio.run),
    ("M6", "per_agent_memory_count", m6_per_agent_memory_count.run),
]


def main() -> int:
    print("# Sanity Check Report")
    print()
    print(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    print()
    print("## Summary")
    print()
    print("| Check | Status | Notes |")
    print("|-------|--------|-------|")

    results: list[tuple[str, str, dict]] = []
    overall_failures = 0
    for code, name, fn in CHECKS:
        try:
            r = fn()
        except Exception as exc:
            r = {"status": "ERROR", "error": str(exc)}
        status = r.get("status", "?")
        if status == "FAIL":
            overall_failures += 1
        notes = ""
        if code == "M1":
            skipped = r.get("skipped_system_events", 0)
            notes = f"{r.get('ungrounded', 0)}/{r.get('total', 0)} ungrounded"
            if skipped:
                notes += f" ({skipped} system events skipped)"
        elif code == "M2":
            notes = f"{len(r.get('violations', []))} violations (cap={r.get('cap', '?')})"
        elif code == "M3":
            notes = f"{len(r.get('violations', []))} violations"
        elif code == "M4":
            notes = f"{len(r.get('empty_agents', []))} empty agents"
        elif code == "M5":
            ratio = r.get("ratio")
            if ratio is not None:
                notes = f"{ratio:.1%} positive ({r.get('positive_count', 0)}/{r.get('total', 0)})"
        elif code == "M6":
            warns = len(r.get("warnings", []))
            notes = f"{warns} low-key warnings (informational)"
        print(f"| {code} {name} | **{status}** | {notes} |")
        results.append((code, name, r))

    print()
    print("---")
    print()

    for code, name, r in results:
        print(f"## {code} — {name}")
        print()
        status = r.get("status", "?")
        print(f"**status**: `{status}`")
        print()

        if code == "M1":
            print(f"- ungrounded events: {r.get('ungrounded', 0)} / {r.get('total', 0)}")
            for d in r.get("details", []):
                print(f"  - `{d.get('id')}` `{d.get('text')}` → {d.get('reason')}")
        elif code == "M2":
            print(f"- per-day cap: {r.get('cap', '?')}")
            print(f"- total memories: {r.get('total_memories', 0)}")
            for v in r.get("violations", []):
                print(f"  - {v['agent']} day {v['day']}: {v['count']} memories")
        elif code == "M3":
            print(f"- total concerns: {r.get('total_concerns', 0)}")
            for v in r.get("violations", []):
                pairs = v.get("overlapping_pairs") or []
                pair_str = "; ".join(f"[{a}] vs [{b}]" for a, b in pairs[:3])
                print(f"  - {v['agent']}: topic '{v['topic']}' has {v['count']} entries with people overlap → {pair_str}")
            disjoint = r.get("multiple_disjoint") or []
            if disjoint:
                print(f"- multiple disjoint concerns (legitimate post-Fix-2 state, not failures):")
                for o in disjoint:
                    print(f"  - {o['agent']}: topic '{o['topic']}' has {o['count']} entries (disjoint people)")
            other = r.get("other_observations") or []
            if other:
                print(f"- 其他 bucket observations (Frankenstein guard, not failures):")
                for o in other:
                    print(f"  - {o['agent']}: {o['count']} entries")
        elif code == "M4":
            print(f"- total agents: {r.get('total_agents', 0)}")
            for a in r.get("empty_agents", []):
                print(f"  - {a}")
        elif code == "M5":
            print(f"- positive ratio: {r.get('ratio', 0):.1%}")
            print(f"- positive count: {r.get('positive_count', 0)} / {r.get('total', 0)}")
            counts = r.get("counts") or {}
            if counts:
                print()
                print("  | emotion | count |")
                print("  |---------|-------|")
                for emotion, count in counts.items():
                    print(f"  | {emotion} | {count} |")
        elif code == "M6":
            print(f"- importance histogram: `{r.get('overall_histogram', {})}`")
            print()
            print("  | agent | count | histogram | low-key |")
            print("  |-------|-------|-----------|---------|")
            for row in r.get("rows", []):
                lk = "✓" if row["low_key"] else ""
                print(f"  | {row['agent']} | {row['count']} | `{row['hist']}` | {lk} |")
            warns = r.get("warnings") or []
            if warns:
                print()
                print("  **warnings**:")
                for w in warns:
                    print(f"  - {w}")
        print()

    if overall_failures:
        print(f"\n**Overall: {overall_failures} hard-fail check(s) failed.**")
    else:
        print("\n**Overall: M1-M5 PASS (M6 is observe-only).**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
