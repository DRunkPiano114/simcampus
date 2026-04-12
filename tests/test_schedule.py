"""Sanity guard on data/schedule.json: long-form scene max_rounds caps."""

import json
from pathlib import Path


def test_schedule_max_rounds_sane():
    """Long-form scenes (课间 / 午饭 / 宿舍夜聊) must stay below their caps.

    Longer scenes accumulate emotional drift the prompt anchors cannot
    fully recover from. The caps below are upper bounds; lowering further
    is fine, raising is a regression.
    """
    schedule_path = Path(__file__).resolve().parents[1] / "data" / "schedule.json"
    scenes = json.loads(schedule_path.read_text(encoding="utf-8"))

    caps = {
        "课间": 15,        # currently 12, allow some slack
        "午饭": 22,        # currently 20
        "宿舍夜聊": 25,    # currently 22
    }
    for s in scenes:
        if s["name"] in caps:
            assert s["max_rounds"] <= caps[s["name"]], (
                f"{s['name']} @ {s['time']} max_rounds={s['max_rounds']} "
                f"exceeds cap {caps[s['name']]}"
            )
