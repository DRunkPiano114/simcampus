"""Tests for apply_results helpers: concern_match, _is_duplicate_concern."""

from sim.models.agent import ActiveConcern
from sim.interaction.apply_results import concern_match, _is_duplicate_concern


# --- concern_match ---

def test_concern_match_exact():
    assert concern_match("被嘲笑", "被嘲笑") is True


def test_concern_match_substring_forward():
    assert concern_match("被江浩天当众嘲笑数学成绩", "当众嘲笑") is True


def test_concern_match_substring_reverse():
    assert concern_match("当众嘲笑", "被江浩天当众嘲笑数学成绩") is True


def test_concern_match_non_contiguous_fails():
    """Non-contiguous substring does NOT match."""
    assert concern_match("被江浩天当众嘲笑数学成绩", "被嘲笑") is False


def test_concern_match_no_match():
    assert concern_match("考试压力", "被嘲笑") is False


def test_concern_match_none():
    assert concern_match("anything", None) is False


def test_concern_match_empty_string():
    """Empty text_b is falsy → returns False."""
    assert concern_match("被嘲笑", "") is False


def test_concern_match_both_empty():
    """Both empty → text_b is falsy → returns False."""
    assert concern_match("", "") is False


# --- _is_duplicate_concern ---

def _make_concern(day=1, scene="课间", people=None, **kw) -> ActiveConcern:
    return ActiveConcern(
        text="test", source_day=day, source_scene=scene,
        related_people=people or [], **kw,
    )


def test_duplicate_same_day_scene_people():
    existing = [_make_concern(day=1, scene="课间", people=["张伟"])]
    new = _make_concern(day=1, scene="课间", people=["张伟"])
    assert _is_duplicate_concern(new, existing) is True


def test_duplicate_overlapping_people():
    """Overlapping (not identical) people → still duplicate."""
    existing = [_make_concern(day=1, scene="课间", people=["张伟", "李明"])]
    new = _make_concern(day=1, scene="课间", people=["张伟", "王芳"])
    assert _is_duplicate_concern(new, existing) is True


def test_not_duplicate_different_day():
    existing = [_make_concern(day=1, scene="课间", people=["张伟"])]
    new = _make_concern(day=2, scene="课间", people=["张伟"])
    assert _is_duplicate_concern(new, existing) is False


def test_not_duplicate_different_scene():
    existing = [_make_concern(day=1, scene="课间", people=["张伟"])]
    new = _make_concern(day=1, scene="午饭", people=["张伟"])
    assert _is_duplicate_concern(new, existing) is False


def test_not_duplicate_no_people_overlap():
    existing = [_make_concern(day=1, scene="课间", people=["张伟"])]
    new = _make_concern(day=1, scene="课间", people=["李明"])
    assert _is_duplicate_concern(new, existing) is False


def test_not_duplicate_empty_existing():
    new = _make_concern(day=1, scene="课间", people=["张伟"])
    assert _is_duplicate_concern(new, []) is False
