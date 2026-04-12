"""Tests for the M1 sanity check (ungrounded events).

These tests construct a synthetic world/event_queue.json + logs/day_*.json
layout in a temp dir, monkeypatch sim.config.settings, and import M1's
run() function to exercise its per-group scoping logic end-to-end.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the sanity_check sibling modules importable
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts" / "sanity_check"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _write_world(world_dir: Path, events: list[dict]) -> None:
    world_dir.mkdir(parents=True, exist_ok=True)
    (world_dir / "event_queue.json").write_text(
        json.dumps({"events": events, "next_id": len(events) + 1}, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_scene(
    logs_dir: Path,
    day: int,
    file_name: str,
    scene_name: str,
    groups: list[dict],
) -> None:
    day_dir = logs_dir / f"day_{day:03d}"
    day_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "scene": {"name": scene_name, "day": day},
        "groups": groups,
    }
    (day_dir / file_name).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )


def _make_group(group_index: int, n_ticks: int) -> dict:
    return {
        "group_index": group_index,
        "ticks": [{"tick": i} for i in range(n_ticks)],
    }


@pytest.fixture
def patched_paths(tmp_path, monkeypatch):
    """Point settings.world_dir / logs_dir at a temp tree and reload M1."""
    from sim.config import settings as sim_settings

    world_dir = tmp_path / "world"
    logs_dir = tmp_path / "logs"
    world_dir.mkdir()
    logs_dir.mkdir()

    monkeypatch.setattr(sim_settings, "world_dir", world_dir)
    monkeypatch.setattr(sim_settings, "logs_dir", logs_dir)

    # Force fresh import so the script's run() reads the patched settings
    import importlib
    import m1_ungrounded_events
    importlib.reload(m1_ungrounded_events)
    return tmp_path, world_dir, logs_dir, m1_ungrounded_events


def test_m1_pass_when_event_cite_in_visible_ticks(patched_paths):
    _, world_dir, logs_dir, m1 = patched_paths
    _write_scene(
        logs_dir, day=1, file_name="0845_课间.json", scene_name="课间",
        groups=[_make_group(group_index=0, n_ticks=5)],
    )
    _write_world(world_dir, events=[
        {
            "id": "evt_1", "text": "ok event", "source_scene": "课间",
            "source_day": 1, "group_index": 0, "cite_ticks": [3],
        },
    ])
    result = m1.run()
    assert result["status"] == "PASS"
    assert result["ungrounded"] == 0
    assert result["total"] == 1


def test_m1_fails_when_cite_ticks_missing(patched_paths):
    _, world_dir, logs_dir, m1 = patched_paths
    _write_scene(
        logs_dir, day=1, file_name="0845_课间.json", scene_name="课间",
        groups=[_make_group(group_index=0, n_ticks=5)],
    )
    _write_world(world_dir, events=[
        {
            "id": "evt_1", "text": "no cite", "source_scene": "课间",
            "source_day": 1, "group_index": 0, "cite_ticks": [],
        },
    ])
    result = m1.run()
    assert result["status"] == "FAIL"
    assert result["ungrounded"] == 1
    assert "no cite_ticks" in result["details"][0]["reason"]


def test_m1_fails_when_cite_ticks_out_of_range(patched_paths):
    _, world_dir, logs_dir, m1 = patched_paths
    _write_scene(
        logs_dir, day=1, file_name="0845_课间.json", scene_name="课间",
        groups=[_make_group(group_index=0, n_ticks=5)],  # visible 1..5
    )
    _write_world(world_dir, events=[
        {
            "id": "evt_1", "text": "out of range", "source_scene": "课间",
            "source_day": 1, "group_index": 0, "cite_ticks": [99],
        },
    ])
    result = m1.run()
    assert result["status"] == "FAIL"
    assert result["ungrounded"] == 1


def test_m1_per_group_scoping_blocks_cross_group_cite(patched_paths):
    """An event from group 1 citing tick 8 must FAIL even when group 0
    in the same scene has 10 ticks — cite_ticks are group-local."""
    _, world_dir, logs_dir, m1 = patched_paths
    _write_scene(
        logs_dir, day=1, file_name="0845_课间.json", scene_name="课间",
        groups=[
            _make_group(group_index=0, n_ticks=10),
            _make_group(group_index=1, n_ticks=3),
        ],
    )
    _write_world(world_dir, events=[
        {
            "id": "evt_1", "text": "from group 1, cites tick 8",
            "source_scene": "课间", "source_day": 1,
            "group_index": 1, "cite_ticks": [8],
        },
    ])
    result = m1.run()
    assert result["status"] == "FAIL"
    assert result["ungrounded"] == 1
    assert "not in group's visible ticks" in result["details"][0]["reason"]


def test_m1_skips_system_generated_events(patched_paths):
    """Events with group_index=None are system-generated and excluded
    from both numerator and denominator."""
    _, world_dir, logs_dir, m1 = patched_paths
    _write_scene(
        logs_dir, day=1, file_name="0845_课间.json", scene_name="课间",
        groups=[_make_group(group_index=0, n_ticks=5)],
    )
    _write_world(world_dir, events=[
        {
            "id": "evt_1", "text": "何老师找张伟谈话", "source_scene": "办公室",
            "source_day": 1, "group_index": None, "cite_ticks": [],
        },
        {
            "id": "evt_2", "text": "ok llm event", "source_scene": "课间",
            "source_day": 1, "group_index": 0, "cite_ticks": [3],
        },
    ])
    result = m1.run()
    assert result["status"] == "PASS"
    assert result["ungrounded"] == 0
    assert result["total"] == 1  # only the LLM-grounded one is in scope
    assert result["total_all_events"] == 2
    assert result["skipped_system_events"] == 1


def test_m1_summarized_range_excluded_from_visible_ticks(patched_paths):
    """When a group has > 12 ticks, the LLM only sees ticks 6+ (0-indexed)
    because narrative.py summarizes the prefix. M1 must mirror that:
    cite_ticks=[3] (1-indexed → tick 2) on a 15-tick group is invalid."""
    _, world_dir, logs_dir, m1 = patched_paths
    _write_scene(
        logs_dir, day=1, file_name="0845_课间.json", scene_name="课间",
        groups=[_make_group(group_index=0, n_ticks=15)],
    )
    _write_world(world_dir, events=[
        {
            "id": "evt_1", "text": "summarized cite", "source_scene": "课间",
            "source_day": 1, "group_index": 0, "cite_ticks": [3],
        },
    ])
    result = m1.run()
    assert result["status"] == "FAIL"
    assert result["ungrounded"] == 1


def test_m1_missing_event_queue_returns_missing(patched_paths):
    _, world_dir, logs_dir, m1 = patched_paths
    # No event_queue.json written
    result = m1.run()
    assert result["status"] == "MISSING"
