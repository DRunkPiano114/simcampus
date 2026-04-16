"""Pure-function tests for card selection + caption logic.

These never touch Pillow — they test the heuristics and data contracts that
decide *what* goes on a card. Pixel output is tested separately (render smoke
tests) because Pillow output isn't byte-deterministic across platforms.
"""

from __future__ import annotations

from sim.cards.captions import (
    BASE_HASHTAGS,
    pick_hashtags,
    scene_caption,
    scene_filename,
)
from sim.cards.scene_card import select_featured_group


# --- select_featured_group ------------------------------------------------


def _scene(groups: list[dict]) -> dict:
    return {"scene": {"day": 1, "time": "07:00", "name": "早读", "location": "教室"}, "groups": groups}


def _mind(urgency: int, thought: str = "") -> dict:
    return {
        "observation": "",
        "inner_thought": thought,
        "emotion": "neutral",
        "action_type": "observe",
        "action_content": None,
        "action_target": None,
        "urgency": urgency,
        "is_disruptive": False,
    }


def _tick(speaker: str | None, content: str | None, minds: dict[str, dict]) -> dict:
    return {
        "tick": 0,
        "public": {
            "speech": {"agent": speaker, "target": None, "content": content} if speaker else None,
            "actions": [],
            "environmental_event": None,
            "exits": [],
        },
        "minds": minds,
    }


def test_select_returns_none_when_all_groups_solo():
    scene = _scene([
        {"group_index": 0, "participants": ["a"], "is_solo": True},
        {"group_index": 1, "participants": ["b"], "is_solo": True},
    ])
    assert select_featured_group(scene) is None


def test_select_prefers_multi_agent_over_solo():
    scene = _scene([
        {"group_index": 0, "participants": ["a"], "is_solo": True},
        {
            "group_index": 1,
            "participants": ["b", "c"],
            "ticks": [_tick("b", "hi", {"b": _mind(3, "想"), "c": _mind(2, "对")})],
        },
    ])
    assert select_featured_group(scene) == 1


def test_select_ranks_by_urgency_and_thought_length():
    """Group 1 has higher total urgency + longer thoughts → should win."""
    scene = _scene([
        {
            "group_index": 0,
            "participants": ["a", "b"],
            "ticks": [_tick("a", "x", {"a": _mind(1, "短"), "b": _mind(1, "短")})],
        },
        {
            "group_index": 1,
            "participants": ["c", "d"],
            "ticks": [
                _tick("c", "y", {"c": _mind(9, "这是一段较长的内心独白"), "d": _mind(7, "也很长的")})
            ],
        },
    ])
    assert select_featured_group(scene) == 1


def test_select_ignores_multi_agent_groups_with_no_ticks():
    scene = _scene([
        {"group_index": 0, "participants": ["a", "b"], "ticks": []},
        {
            "group_index": 1,
            "participants": ["c", "d"],
            "ticks": [_tick("c", "x", {"c": _mind(2, "…")})],
        },
    ])
    assert select_featured_group(scene) == 1


def test_select_ignores_lone_participants_even_without_is_solo_flag():
    """A 'group' of one, with no is_solo flag, is still not a multi-agent scene."""
    scene = _scene([
        {"group_index": 0, "participants": ["a"], "ticks": [_tick(None, None, {"a": _mind(8, "x")})]},
    ])
    assert select_featured_group(scene) is None


def test_select_tie_break_prefers_earlier_group():
    scene = _scene([
        {
            "group_index": 0,
            "participants": ["a", "b"],
            "ticks": [_tick("a", "x", {"a": _mind(3, "abc"), "b": _mind(2, "de")})],
        },
        {
            "group_index": 1,
            "participants": ["c", "d"],
            "ticks": [_tick("c", "y", {"c": _mind(3, "abc"), "d": _mind(2, "de")})],
        },
    ])
    assert select_featured_group(scene) == 0


# --- caption / filename ---------------------------------------------------


def test_scene_filename_sanitizes_unsafe_chars():
    f = scene_filename(1, 'bad:name', 'loc|here')
    assert ":" not in f
    assert "|" not in f
    assert f.endswith(".png")


def test_scene_filename_includes_zero_padded_day():
    assert scene_filename(7, "早读", "教室").startswith("simcampus_第007天_")


def test_pick_hashtags_includes_base_set():
    tags = pick_hashtags(location=None, time=None)
    for t in BASE_HASHTAGS:
        assert t in tags


def test_pick_hashtags_adds_location_tag_when_matched():
    tags = pick_hashtags(location="教室", time=None)
    assert "#教室日常" in tags


def test_pick_hashtags_adds_time_tag_when_matched():
    tags = pick_hashtags(location=None, time="22:00")
    assert "#宿舍夜聊" in tags


def test_pick_hashtags_caps_at_five():
    tags = pick_hashtags(
        location="教室",
        time="07:00",
        extra=("#a", "#b", "#c", "#d"),
    )
    assert len(tags) <= 5


def test_pick_hashtags_dedupes():
    tags = pick_hashtags(
        location="宿舍",
        time="22:00",
        extra=(),
    )
    # Both location and time map to #宿舍夜聊 — should appear only once.
    assert tags.count("#宿舍夜聊") == 1


def test_scene_caption_structure():
    out = scene_caption(
        day=3,
        scene_name="早读",
        location="教室",
        time="07:00",
        featured_quote="英语真烦",
        featured_speaker="林昭宇",
        motif_emoji="☀️",
    )
    assert set(out) == {"caption", "hashtags", "filename"}
    assert "第003天" in out["caption"]
    assert "林昭宇" in out["caption"]
    assert "英语真烦" in out["caption"]
    assert 3 <= len(out["hashtags"]) <= 5


def test_scene_caption_handles_no_quote():
    out = scene_caption(
        day=1,
        scene_name="早读",
        location="教室",
        time="07:00",
        featured_quote=None,
        featured_speaker=None,
    )
    # Still produces a caption (title-only).
    assert out["caption"].strip()
    assert "SimCampus" in out["caption"]
