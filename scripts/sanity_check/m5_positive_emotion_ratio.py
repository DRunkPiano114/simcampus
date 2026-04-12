"""M5: Positive emotion ratio.

Walks every scene file in `logs/day_*/` and counts the post-reflection
emotions across all agents. Reports the share that fall in the positive
bucket (happy / excited / touched / proud / calm); the threshold is 25%.

This is a necessary but not sufficient condition: the LLM may obediently
fill emotion=calm while still writing 小说化 inner_thought / reflection.
The qualitative side-by-side transcript is the final arbiter.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sim.config import settings  # noqa: E402


POSITIVE_EMOTIONS = {"happy", "excited", "touched", "proud", "calm"}
THRESHOLD = 0.25


def _scene_files() -> list:
    files: list = []
    if not settings.logs_dir.exists():
        return files
    for day_dir in sorted(settings.logs_dir.iterdir()):
        if not day_dir.is_dir() or not day_dir.name.startswith("day_"):
            continue
        for p in sorted(day_dir.glob("*.json")):
            if p.name == "scenes.json" or p.name == "trajectory.json":
                continue
            files.append(p)
    return files


def run() -> dict:
    counter: Counter[str] = Counter()
    for path in _scene_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for group in data.get("groups", []):
            # Group dialogue: per-agent reflections
            for refl in (group.get("reflections") or {}).values():
                emotion = (refl or {}).get("emotion")
                if emotion:
                    counter[emotion] += 1
            # Solo group: solo_reflection.emotion
            solo = group.get("solo_reflection")
            if solo:
                emotion = solo.get("emotion")
                if emotion:
                    counter[emotion] += 1

    total = sum(counter.values())
    if total == 0:
        return {"status": "MISSING", "ratio": 0.0, "total": 0, "counts": {}}

    positive_count = sum(c for e, c in counter.items() if e in POSITIVE_EMOTIONS)
    ratio = positive_count / total
    return {
        "status": "PASS" if ratio >= THRESHOLD else "FAIL",
        "ratio": ratio,
        "total": total,
        "positive_count": positive_count,
        "counts": dict(counter.most_common()),
    }


def main() -> int:
    result = run()
    if result["status"] == "MISSING":
        print(f"M5 positive_emotion_ratio: MISSING (no scene files)")
        return 1
    print(f"M5 positive_emotion_ratio: {result['status']} "
          f"({result['positive_count']}/{result['total']} = "
          f"{result['ratio']:.1%}, threshold {THRESHOLD:.0%})")
    for e, c in list(result["counts"].items())[:10]:
        marker = "+" if e in POSITIVE_EMOTIONS else " "
        print(f"  {marker} {e}: {c}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
