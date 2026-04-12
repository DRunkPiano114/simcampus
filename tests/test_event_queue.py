"""Tests for EventQueueManager."""

from random import Random

from sim.models.event import Event, EventQueue
from sim.world.event_queue import EventQueueManager


def _make_manager(events=None, rng=None) -> EventQueueManager:
    eq = EventQueue(events=events or [], next_id=len(events or []) + 1)
    return EventQueueManager(eq, rng=rng or Random(42))


# --- add_event ---

def test_add_event():
    mgr = _make_manager()
    event = mgr.add_event(
        text="张伟和李明吵架了", category="冲突",
        source_scene="课间", source_day=1,
        witnesses=["a", "b"],
    )
    assert event.id == "evt_1"
    assert event.text == "张伟和李明吵架了"
    assert event.known_by == ["a", "b"]
    assert event.active is True
    assert len(mgr.eq.events) == 1
    assert mgr.eq.next_id == 2


def test_add_event_increments_id():
    mgr = _make_manager()
    mgr.add_event("e1", "cat", "s1", 1, ["a"])
    mgr.add_event("e2", "cat", "s2", 1, ["b"])
    assert mgr.eq.events[0].id == "evt_1"
    assert mgr.eq.events[1].id == "evt_2"
    assert mgr.eq.next_id == 3


def test_add_event_persists_cite_ticks_and_group_index():
    """cite_ticks and group_index round-trip onto the persisted Event."""
    mgr = _make_manager()
    event = mgr.add_event(
        text="八卦",
        category="八卦",
        source_scene="课间",
        source_day=2,
        witnesses=["a"],
        cite_ticks=[3, 5],
        group_index=1,
    )
    assert event.cite_ticks == [3, 5]
    assert event.group_index == 1
    stored = mgr.eq.events[0]
    assert stored.cite_ticks == [3, 5]
    assert stored.group_index == 1


def test_add_event_defaults_for_system_events():
    """System-generated events leave cite_ticks empty and group_index None."""
    mgr = _make_manager()
    event = mgr.add_event(
        text="何老师找张伟谈话了",
        category="teacher_talk",
        source_scene="办公室",
        source_day=1,
        witnesses=["zhang"],
    )
    assert event.cite_ticks == []
    assert event.group_index is None


# --- get_active_events_for_group ---

def test_get_active_events_spreads():
    """Event known by some group members but not others → can spread."""
    event = Event(id="evt_1", text="秘密", source_day=1,
                  known_by=["a"], spread_probability=1.0)
    mgr = _make_manager([event])
    # Group has a (knows) and b (doesn't know)
    result = mgr.get_active_events_for_group(["a", "b"])
    assert len(result) == 1
    assert result[0].id == "evt_1"


def test_get_active_events_all_know():
    """Event known by everyone in group → no spread needed."""
    event = Event(id="evt_1", text="秘密", source_day=1,
                  known_by=["a", "b"], spread_probability=1.0)
    mgr = _make_manager([event])
    result = mgr.get_active_events_for_group(["a", "b"])
    assert len(result) == 0


def test_get_active_events_none_know():
    """No group member knows the event → can't spread."""
    event = Event(id="evt_1", text="秘密", source_day=1,
                  known_by=["c"], spread_probability=1.0)
    mgr = _make_manager([event])
    result = mgr.get_active_events_for_group(["a", "b"])
    assert len(result) == 0


def test_get_active_events_probability_filter():
    """Low spread probability → event may not spread."""
    event = Event(id="evt_1", text="秘密", source_day=1,
                  known_by=["a"], spread_probability=0.0)
    mgr = _make_manager([event])
    result = mgr.get_active_events_for_group(["a", "b"])
    assert len(result) == 0


def test_get_active_events_skips_inactive():
    event = Event(id="evt_1", text="旧事", source_day=1,
                  known_by=["a"], spread_probability=1.0, active=False)
    mgr = _make_manager([event])
    result = mgr.get_active_events_for_group(["a", "b"])
    assert len(result) == 0


# --- get_known_events ---

def test_get_known_events():
    events = [
        Event(id="evt_1", text="e1", source_day=1, known_by=["a", "b"]),
        Event(id="evt_2", text="e2", source_day=1, known_by=["b"]),
        Event(id="evt_3", text="e3", source_day=1, known_by=["a"], active=False),
    ]
    mgr = _make_manager(events)
    known_a = mgr.get_known_events("a")
    assert len(known_a) == 1  # evt_1 only (evt_3 is inactive)
    assert known_a[0].id == "evt_1"

    known_b = mgr.get_known_events("b")
    assert len(known_b) == 2  # evt_1 and evt_2


# --- mark_discussed ---

def test_mark_discussed_adds_knowers():
    event = Event(id="evt_1", text="e1", source_day=1, known_by=["a"])
    mgr = _make_manager([event])
    mgr.mark_discussed("evt_1", ["b", "c"])
    assert set(mgr.eq.events[0].known_by) == {"a", "b", "c"}


def test_mark_discussed_no_duplicate():
    event = Event(id="evt_1", text="e1", source_day=1, known_by=["a", "b"])
    mgr = _make_manager([event])
    mgr.mark_discussed("evt_1", ["a", "c"])
    assert mgr.eq.events[0].known_by == ["a", "b", "c"]


def test_mark_discussed_unknown_id():
    event = Event(id="evt_1", text="e1", source_day=1, known_by=["a"])
    mgr = _make_manager([event])
    mgr.mark_discussed("evt_999", ["b"])  # No-op, shouldn't crash
    assert mgr.eq.events[0].known_by == ["a"]


# --- expire_old_events ---

def test_expire_old_events():
    events = [
        Event(id="evt_1", text="old", source_day=1),
        Event(id="evt_2", text="recent", source_day=4),
    ]
    mgr = _make_manager(events)
    mgr.expire_old_events(current_day=4, expire_days=3)
    assert mgr.eq.events[0].active is False  # day 1, 4-1 >= 3
    assert mgr.eq.events[1].active is True   # day 4, 4-4 < 3


def test_expire_already_inactive():
    event = Event(id="evt_1", text="old", source_day=1, active=False)
    mgr = _make_manager([event])
    mgr.expire_old_events(current_day=10)
    assert event.active is False  # Still inactive, no crash


def test_expire_boundary():
    """Exactly at expire_days → should expire."""
    event = Event(id="evt_1", text="e", source_day=1)
    mgr = _make_manager([event])
    mgr.expire_old_events(current_day=4, expire_days=3)  # 4 - 1 = 3 >= 3
    assert event.active is False
