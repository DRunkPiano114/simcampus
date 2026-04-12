"""M6: Per-agent memory count + importance distribution.

Walks every agent's `key_memories.json` and reports total memory count
along with an importance histogram. The goal is to detect over-suppression
of low-key personas (姜皓天 / 程雨桐 / 何家骏 / 苏念瑶 ...), who should
still accumulate at least a few memories.

This script has no hard pass/fail. Output is OBSERVE only — humans should
read it after a rerun and decide whether to back off the importance
threshold.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sim.config import settings  # noqa: E402


# Personas described as "low-key / cheerful / quiet / introvert" — these are
# the canaries for over-suppression. List drawn from the codex1.md profile
# notes; adjust as personas evolve.
LOW_KEY_AGENTS = {
    "jiang_haotian",   # 姜皓天 — 乐天
    "cheng_yutong",    # 程雨桐 — 安静
    "he_jiajun",       # 何家骏 — 内向
    "su_nianyao",      # 苏念瑶 — 低调
}

LOW_KEY_MIN_COUNT = 2  # warning threshold for 4-day rerun


def _bucket(importance: int) -> str:
    if importance <= 4:
        return "3-4"
    if importance == 5:
        return "5"
    if importance == 6:
        return "6"
    return "7+"


def run() -> dict:
    rows: list[dict] = []
    overall_hist: Counter[str] = Counter()
    warnings: list[str] = []

    for agent_dir in sorted(settings.agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        km_path = agent_dir / "key_memories.json"
        memories: list[dict] = []
        if km_path.exists():
            km = json.loads(km_path.read_text(encoding="utf-8"))
            memories = km.get("memories", [])

        hist: Counter[str] = Counter()
        for m in memories:
            bucket = _bucket(m.get("importance", 0))
            hist[bucket] += 1
            overall_hist[bucket] += 1

        rows.append({
            "agent": agent_dir.name,
            "count": len(memories),
            "hist": dict(hist),
            "low_key": agent_dir.name in LOW_KEY_AGENTS,
        })

        if agent_dir.name in LOW_KEY_AGENTS and len(memories) <= LOW_KEY_MIN_COUNT:
            warnings.append(
                f"{agent_dir.name}: only {len(memories)} memories — the importance "
                f"threshold may be over-suppressing low-key personas. Consider "
                f"raising key_memory_write_threshold with a per-agent daily minimum."
            )

    return {
        "status": "OBSERVE",  # this script never hard-fails
        "rows": rows,
        "overall_histogram": dict(overall_hist.most_common()),
        "warnings": warnings,
    }


def main() -> int:
    result = run()
    print(f"M6 per_agent_memory_count: OBSERVE")
    print(f"  Importance histogram (all agents): {result['overall_histogram']}")
    print()
    print("  per-agent counts:")
    for r in result["rows"]:
        marker = "*" if r["low_key"] else " "
        print(f"    {marker} {r['agent']}: count={r['count']}, hist={r['hist']}")
    if result["warnings"]:
        print()
        print("  WARNINGS:")
        for w in result["warnings"]:
            print(f"    ! {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
