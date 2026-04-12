"""Tests for the M3 sanity check (concern topic dedup audit).

These tests construct synthetic agents/agent_id/state.json files in a temp
dir, monkeypatch sim.config.settings.agents_dir, and import M3's run()
function to verify it correctly distinguishes:

- legitimate disjoint-people concerns (informational)
- 其他 Frankenstein-guard coexistence (informational)
- actual people-overlap merge bugs (FAIL)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts" / "sanity_check"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _write_agent(agents_dir: Path, aid: str, concerns: list[dict]) -> None:
    agent_dir = agents_dir / aid
    agent_dir.mkdir(parents=True, exist_ok=True)
    state = {"active_concerns": concerns}
    (agent_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8",
    )


def _concern(topic: str, people: list[str], text: str = "x") -> dict:
    return {
        "text": text,
        "topic": topic,
        "related_people": people,
        "intensity": 5,
        "source_day": 1,
    }


@pytest.fixture
def patched_paths(tmp_path, monkeypatch):
    from sim.config import settings as sim_settings

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    monkeypatch.setattr(sim_settings, "agents_dir", agents_dir)

    import importlib
    import m3_concern_topic_dedup
    importlib.reload(m3_concern_topic_dedup)
    return agents_dir, m3_concern_topic_dedup


def test_m3_passes_when_disjoint_people_under_same_topic(patched_paths):
    """Two 学业焦虑 concerns about disjoint students do not fail —
    add_concern's merge rule requires people overlap, so disjoint
    coexistence is legitimate."""
    agents_dir, m3 = patched_paths
    _write_agent(agents_dir, "a", concerns=[
        _concern("学业焦虑", ["张伟"]),
        _concern("学业焦虑", ["李明"]),
    ])

    result = m3.run()
    assert result["status"] == "PASS"
    assert len(result["multiple_disjoint"]) == 1
    assert result["multiple_disjoint"][0]["agent"] == "a"
    assert result["multiple_disjoint"][0]["topic"] == "学业焦虑"


def test_m3_fails_when_people_overlap_under_same_topic(patched_paths):
    """Two same-topic concerns sharing a person — add_concern should have
    merged them, so this is the real bug surface M3 guards."""
    agents_dir, m3 = patched_paths
    _write_agent(agents_dir, "a", concerns=[
        _concern("学业焦虑", ["张伟", "李明"]),
        _concern("学业焦虑", ["张伟", "王芳"]),  # 张伟 overlaps
    ])

    result = m3.run()
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["agent"] == "a"
    assert v["topic"] == "学业焦虑"
    assert len(v["overlapping_pairs"]) == 1


def test_m3_other_bucket_multiple_is_observe_only(patched_paths):
    """The Frankenstein guard intentionally lets multiple 其他 concerns
    coexist. Must report as observation, never fail."""
    agents_dir, m3 = patched_paths
    _write_agent(agents_dir, "a", concerns=[
        _concern("其他", []),
        _concern("其他", []),
        _concern("其他", ["张伟"]),
    ])

    result = m3.run()
    assert result["status"] == "PASS"
    assert len(result["other_observations"]) == 1
    assert result["other_observations"][0]["count"] == 3


def test_m3_passes_with_single_concern_per_topic(patched_paths):
    """One concern per topic across multiple topics = healthy state."""
    agents_dir, m3 = patched_paths
    _write_agent(agents_dir, "a", concerns=[
        _concern("学业焦虑", ["张伟"]),
        _concern("家庭压力", []),
        _concern("兴趣爱好", []),
    ])

    result = m3.run()
    assert result["status"] == "PASS"
    assert len(result["violations"]) == 0
    assert len(result["multiple_disjoint"]) == 0


def test_m3_handles_missing_state_files(patched_paths):
    """Agent dirs without state.json are silently skipped."""
    agents_dir, m3 = patched_paths
    (agents_dir / "ghost").mkdir()  # No state.json

    result = m3.run()
    assert result["status"] == "PASS"
    assert result["total_concerns"] == 0


def test_m3_aggregates_violations_across_agents(patched_paths):
    """Multiple agents with violations are all reported."""
    agents_dir, m3 = patched_paths
    _write_agent(agents_dir, "a", concerns=[
        _concern("学业焦虑", ["张伟"]),
        _concern("学业焦虑", ["张伟", "李明"]),  # overlap → violation
    ])
    _write_agent(agents_dir, "b", concerns=[
        _concern("人际矛盾", ["王芳"]),
        _concern("人际矛盾", ["王芳"]),  # overlap → violation
    ])
    _write_agent(agents_dir, "c", concerns=[
        _concern("学业焦虑", ["陈强"]),  # only one → fine
    ])

    result = m3.run()
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 2
    agents_with_violations = {v["agent"] for v in result["violations"]}
    assert agents_with_violations == {"a", "b"}
