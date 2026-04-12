"""Tests for AgentStorage.write_key_memories."""

from sim.agent.storage import AgentStorage
from sim.models.memory import KeyMemory, KeyMemoryFile


def test_write_key_memories_roundtrip(tmp_path):
    """write_key_memories overwrites the file; load_key_memories returns
    exactly what was written."""
    storage = AgentStorage("a", base_dir=tmp_path)

    # Build a fresh KeyMemoryFile with three memories
    km = KeyMemoryFile(memories=[
        KeyMemory(date="Day 1", day=1, text="m1", importance=4),
        KeyMemory(date="Day 1", day=1, text="m2", importance=6),
        KeyMemory(date="Day 2", day=2, text="m3", importance=5),
    ])
    storage.write_key_memories(km)

    loaded = storage.load_key_memories()
    assert len(loaded.memories) == 3
    texts = [m.text for m in loaded.memories]
    assert texts == ["m1", "m2", "m3"]


def test_write_key_memories_overwrites_existing(tmp_path):
    """A second write replaces the file rather than appending."""
    storage = AgentStorage("a", base_dir=tmp_path)
    storage.write_key_memories(KeyMemoryFile(memories=[
        KeyMemory(date="Day 1", day=1, text="initial", importance=3),
    ]))
    storage.write_key_memories(KeyMemoryFile(memories=[
        KeyMemory(date="Day 2", day=2, text="replaced", importance=5),
    ]))
    loaded = storage.load_key_memories()
    assert len(loaded.memories) == 1
    assert loaded.memories[0].text == "replaced"
