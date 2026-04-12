"""Tests for scene pacing label injection (`_compute_pacing_label` and the
threshold-only emission rule in `run_group_dialogue`)."""

from sim.interaction.turn import _compute_pacing_label


def test_compute_pacing_label_start():
    """Tick 0 of any non-zero scene → 刚开始."""
    assert _compute_pacing_label(0, 12) == "刚开始"
    assert _compute_pacing_label(0, 20) == "刚开始"


def test_compute_pacing_label_middle():
    """Mid-scene → 在聊."""
    # 12-tick scene: 0.3 < t/12 < 0.7 → t in {4, 5, 6, 7, 8}
    assert _compute_pacing_label(4, 12) == "在聊"
    assert _compute_pacing_label(7, 12) == "在聊"
    assert _compute_pacing_label(8, 12) == "在聊"


def test_compute_pacing_label_end():
    """t/max ≥ 0.7 → 差不多该散了."""
    assert _compute_pacing_label(9, 12) == "差不多该散了"
    assert _compute_pacing_label(11, 12) == "差不多该散了"
    assert _compute_pacing_label(15, 20) == "差不多该散了"


def test_compute_pacing_label_zero_max():
    """max_rounds=0 (degenerate) → empty string."""
    assert _compute_pacing_label(0, 0) == ""
    assert _compute_pacing_label(5, 0) == ""


def test_pacing_label_only_on_threshold_crossing():
    """Simulate the in-loop suppression logic in run_group_dialogue: only emit
    a non-empty label when the bucket changes from the previous tick.
    For max_rounds=20, tick 0 (刚开始) is silently consumed by the init value;
    only the transitions to 在聊 (tick 6) and 差不多该散了 (tick 14) should
    surface as non-empty labels."""
    max_rounds = 20
    prev = "刚开始"  # init: tick 0 is silently skipped
    emitted: list[str] = []
    for t in range(max_rounds):
        cur = _compute_pacing_label(t, max_rounds)
        if cur != prev:
            emitted.append(cur)
            prev = cur
    assert emitted == ["在聊", "差不多该散了"]


def test_pacing_label_short_scene():
    """For an 8-tick scene, the boundary transitions should still appear
    exactly once each."""
    max_rounds = 8
    prev = "刚开始"
    emitted: list[str] = []
    for t in range(max_rounds):
        cur = _compute_pacing_label(t, max_rounds)
        if cur != prev:
            emitted.append(cur)
            prev = cur
    assert emitted == ["在聊", "差不多该散了"]
